from __future__ import annotations

import base64
import binascii
import concurrent.futures
import ctypes
from datetime import datetime
import hashlib
import ipaddress
import json
import os
import platform
import posixpath
import shlex
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urlsplit

import paramiko
import psutil
from scp import SCPClient
from PySide6.QtCore import (
    QEasingCurve,
    QLocale,
    QObject,
    QPropertyAnimation,
    QRunnable,
    QThreadPool,
    QTimer,
    Qt,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QDragEnterEvent,
    QDropEvent,
    QFont,
    QIcon,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QBoxLayout,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

try:
    from .i18n import LANGUAGES, current_language, normalize_language, set_language, tr
except ImportError:
    from i18n import LANGUAGES, current_language, normalize_language, set_language, tr


APP_NAME = "Kindle Book Sender"
APP_VERSION = "1.3.4"
ORGANIZATION = "AgInTi Flow"
WEBSITE = "https://lazying.art/eink"
LEARN_WEBSITE = "https://learn.lazying.art"
SSH_PORT = 2222
REMOTE_BOOK_DIRECTORY = "/mnt/us/documents/Books"
KEY_COMMENT = "AgInTi-Kindle-Book-Sender"
SHARED_KEY_RELATIVE_PATH = Path("Handoff") / "keys" / "kindle_handoff_rsa"
SHARED_KEY_FINGERPRINT = "SHA256:Q/RgMY4wzHjQYuC3sfHDykwp8ejp9C7wyfAZLE8OMJE"

def application_data_directory() -> Path:
    system = platform.system()
    if system == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "AgInTi Flow" / "Kindle Book Sender"
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "AgInTi Flow" / "Kindle Book Sender"
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "aginti-flow" / "kindle-book-sender"


def human_size(byte_count: int) -> str:
    value = float(byte_count)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{byte_count} B"


def powershell_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def run_hidden_powershell(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
        text=True,
        timeout=20,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )


def windows_installed_paths() -> tuple[Path, Path]:
    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    roaming = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    executable = local / "Programs" / "LazyingArt" / "Kindle Book Sender" / "Kindle Book Sender.exe"
    shortcut = roaming / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "LazyingArt" / "Kindle Book Sender.lnk"
    return executable, shortcut


def install_windows_app() -> tuple[Path, Path]:
    if platform.system() != "Windows" or not getattr(sys, "frozen", False):
        raise RuntimeError(tr("install_requires_build"))
    source = Path(sys.executable).resolve()
    executable, shortcut = windows_installed_paths()
    executable.parent.mkdir(parents=True, exist_ok=True)
    shortcut.parent.mkdir(parents=True, exist_ok=True)
    if source != executable.resolve():
        temporary = executable.with_suffix(".new.exe")
        shutil.copy2(source, temporary)
        temporary.replace(executable)
    script = (
        "$ws=New-Object -ComObject WScript.Shell;"
        f"$s=$ws.CreateShortcut({powershell_literal(str(shortcut))});"
        f"$s.TargetPath={powershell_literal(str(executable))};"
        f"$s.WorkingDirectory={powershell_literal(str(executable.parent))};"
        f"$s.IconLocation={powershell_literal(str(executable) + ',0')};"
        "$s.Description='Kindle Book Sender by LazyingArt';$s.Save()"
    )
    result = run_hidden_powershell(script)
    if result.returncode != 0 or not shortcut.exists():
        raise RuntimeError(result.stderr.strip() or "Could not create the Start menu shortcut.")
    return executable, shortcut


def pin_windows_taskbar(shortcut: Path) -> bool:
    script = (
        "$shell=New-Object -ComObject Shell.Application;"
        f"$folder=$shell.Namespace({powershell_literal(str(shortcut.parent))});"
        f"$item=$folder.ParseName({powershell_literal(shortcut.name)});"
        "if($null -eq $item){'UNAVAILABLE';exit 2};"
        "$pattern='Pin to taskbar|固定到任务栏|固定到工作列|釘選到工作列|An Taskleiste anheften|Épingler à la barre des tâches|Anclar a la barra de tareas|Закрепить на панели задач';"
        "$verb=@($item.Verbs())|Where-Object{(($_.Name -replace '&','').Trim()) -match $pattern}|Select-Object -First 1;"
        "if($null -eq $verb){'UNAVAILABLE';exit 3};$verb.DoIt();Start-Sleep -Milliseconds 800;'PINNED'"
    )
    result = run_hidden_powershell(script)
    return result.returncode == 0 and "PINNED" in result.stdout


@dataclass(frozen=True)
class Endpoint:
    host: str
    port: int = SSH_PORT

    @property
    def display(self) -> str:
        host = f"[{self.host}]" if ":" in self.host and not self.host.startswith("[") else self.host
        return f"{host}:{self.port}"


def parse_endpoint(value: str, default_port: int = SSH_PORT) -> Endpoint:
    text = value.strip()
    if not text:
        raise ValueError("Enter a Kindle IP address or hostname.")

    username = ""
    host = ""
    port = default_port
    if "://" in text:
        parsed = urlsplit(text)
        if parsed.scheme.lower() != "ssh" or not parsed.hostname:
            raise ValueError("Use an address such as 192.168.1.109, kindle.local, or ssh://root@host:2222.")
        username = parsed.username or ""
        host = parsed.hostname
        try:
            port = parsed.port or default_port
        except ValueError as error:
            raise ValueError("The SSH port must be a number from 1 to 65535.") from error
    else:
        if "@" in text:
            username, text = text.rsplit("@", 1)
        if text.startswith("["):
            closing = text.find("]")
            if closing < 0:
                raise ValueError("An IPv6 address with a port must look like [fd00::26]:2222.")
            host = text[1:closing]
            remainder = text[closing + 1 :]
            if remainder:
                if not remainder.startswith(":") or not remainder[1:].isdigit():
                    raise ValueError("An IPv6 address with a port must look like [fd00::26]:2222.")
                port = int(remainder[1:])
        else:
            try:
                ipaddress.ip_address(text.split("%", 1)[0])
                host = text
            except ValueError:
                if text.count(":") == 1 and text.rsplit(":", 1)[1].isdigit():
                    host, port_text = text.rsplit(":", 1)
                    port = int(port_text)
                else:
                    host = text

    if username and username.lower() != "root":
        raise ValueError("KOReader SSH uses the root account. Use root@host or omit the username.")
    host = host.strip().strip("[]")
    if not host or any(character.isspace() for character in host):
        raise ValueError("The Kindle address is empty or contains spaces.")
    if not 1 <= int(port) <= 65535:
        raise ValueError("The SSH port must be from 1 to 65535.")
    return Endpoint(host, int(port))


def probe_endpoint(endpoint: Endpoint, timeout: float = 0.8) -> tuple[bool, str]:
    try:
        with socket.create_connection((endpoint.host, endpoint.port), timeout=timeout):
            return True, "SSH port is reachable"
    except socket.gaierror:
        return False, f"{endpoint.host} could not be resolved"
    except ConnectionRefusedError:
        return False, f"TCP {endpoint.port} is closed; stop and restart KOReader SSH"
    except TimeoutError:
        return False, (
            f"TCP {endpoint.port} timed out; check the address, Wi-Fi client isolation, VPN, routing, and that KOReader SSH is running"
        )
    except OSError as error:
        code = getattr(error, "winerror", None) or getattr(error, "errno", None)
        if code in (10013, 13):
            return False, f"Windows or security software blocked outbound TCP {endpoint.port}"
        if code in (10051, 10065, 101, 113):
            return False, f"Windows has no route to {endpoint.host}"
        if code in (10061, 111, 61):
            return False, f"TCP {endpoint.port} is closed; start KOReader SSH"
        return False, f"TCP connection failed: {error}"


def request_windows_firewall_rule(port: int) -> bool:
    if platform.system() != "Windows":
        return False
    name = f"Kindle Book Sender SSH Outbound {port}"
    script = (
        f"$name='{name}'; "
        "$rule=Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue; "
        "if(-not $rule){"
        f"New-NetFirewallRule -DisplayName $name -Direction Outbound -Action Allow -Protocol TCP -RemotePort {port} -Profile Any | Out-Null"
        "}"
    )
    arguments = f'-NoProfile -ExecutionPolicy Bypass -Command "{script}"'
    result = ctypes.windll.shell32.ShellExecuteW(None, "runas", "powershell.exe", arguments, None, 1)
    return int(result) > 32


def make_app_icon(size: int = 128) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#073C32"))
    painter.drawRoundedRect(4, 4, size - 8, size - 8, 26, 26)

    paper_x = int(size * 0.24)
    paper_y = int(size * 0.17)
    paper_w = int(size * 0.52)
    paper_h = int(size * 0.66)
    painter.setBrush(QColor("#17201C"))
    painter.drawEllipse(int(size * 0.27), int(size * 0.20), int(size * 0.18), int(size * 0.18))
    painter.drawEllipse(int(size * 0.55), int(size * 0.20), int(size * 0.18), int(size * 0.18))
    painter.setBrush(QColor("#FBFAF6"))
    painter.drawRoundedRect(paper_x, paper_y, paper_w, paper_h, 7, 7)

    painter.setBrush(QColor("#17201C"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(int(size * 0.33), int(size * 0.31), int(size * 0.13), int(size * 0.10))
    painter.drawEllipse(int(size * 0.54), int(size * 0.31), int(size * 0.13), int(size * 0.10))
    painter.drawEllipse(int(size * 0.47), int(size * 0.41), int(size * 0.06), int(size * 0.045))
    painter.setPen(QPen(QColor("#0D5C4B"), max(3, size // 30)))
    painter.drawLine(int(size * 0.35), int(size * 0.55), int(size * 0.65), int(size * 0.55))
    painter.drawLine(int(size * 0.35), int(size * 0.63), int(size * 0.57), int(size * 0.63))

    painter.setPen(QPen(QColor("#D78A2A"), max(5, size // 20)))
    painter.drawLine(int(size * 0.38), int(size * 0.73), int(size * 0.62), int(size * 0.73))
    painter.drawLine(int(size * 0.56), int(size * 0.67), int(size * 0.62), int(size * 0.73))
    painter.drawLine(int(size * 0.56), int(size * 0.79), int(size * 0.62), int(size * 0.73))
    painter.end()
    return QIcon(pixmap)


class SettingsStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.path = root / "settings.json"
        self.data: dict[str, object] = {}
        self.load()

    def load(self) -> None:
        try:
            if self.path.exists():
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            self.data = {}

    def save(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(self.data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        temporary.replace(self.path)

    @property
    def last_ip(self) -> str:
        value = self.data.get("last_ip", "")
        return value if isinstance(value, str) else ""

    @last_ip.setter
    def last_ip(self, value: str) -> None:
        self.data["last_ip"] = value
        self.save()

    @property
    def language(self) -> str:
        value = self.data.get("language", "")
        return value if isinstance(value, str) else ""

    @language.setter
    def language(self, value: str) -> None:
        self.data["language"] = value
        self.save()

    @property
    def no_password(self) -> bool:
        return bool(self.data.get("no_password", False))

    @no_password.setter
    def no_password(self, value: bool) -> None:
        self.data["no_password"] = bool(value)
        self.save()

    @property
    def last_directory(self) -> str:
        value = self.data.get("last_directory", "")
        return value if isinstance(value, str) else ""

    @last_directory.setter
    def last_directory(self, value: str) -> None:
        self.data["last_directory"] = value
        self.save()

    @property
    def recent_addresses(self) -> list[str]:
        value = self.data.get("recent_addresses", [])
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, str) and item.strip()][:12]

    def remember_address(self, value: str) -> None:
        address = value.strip()
        if not address:
            return
        addresses = [item for item in self.recent_addresses if item != address]
        self.data["recent_addresses"] = [address, *addresses][:12]
        self.save()

    @property
    def transfer_history(self) -> list[dict[str, object]]:
        value = self.data.get("transfer_history", [])
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)][:30]

    def add_transfer(self, record: dict[str, object]) -> None:
        self.data["transfer_history"] = [record, *self.transfer_history][:30]
        self.save()

    def clear_transfer_history(self) -> None:
        self.data["transfer_history"] = []
        self.save()

    @property
    def last_storage(self) -> dict[str, object]:
        value = self.data.get("last_storage", {})
        return value if isinstance(value, dict) else {}

    @last_storage.setter
    def last_storage(self, value: dict[str, object]) -> None:
        self.data["last_storage"] = value
        self.save()

    @property
    def installed_version(self) -> str:
        value = self.data.get("installed_version", "")
        return value if isinstance(value, str) else ""

    @installed_version.setter
    def installed_version(self, value: str) -> None:
        self.data["installed_version"] = value
        self.save()

    @property
    def taskbar_pin_attempted(self) -> bool:
        return bool(self.data.get("taskbar_pin_attempted", False))

    @taskbar_pin_attempted.setter
    def taskbar_pin_attempted(self, value: bool) -> None:
        self.data["taskbar_pin_attempted"] = bool(value)
        self.save()


def openssh_sha256_fingerprint(key: paramiko.PKey) -> str:
    digest = hashlib.sha256(key.asbytes()).digest()
    encoded = base64.b64encode(digest).decode("ascii").rstrip("=")
    return f"SHA256:{encoded}"


def bundled_shared_private_key_path() -> Path:
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        root = Path(bundle_root)
    else:
        root = Path(__file__).resolve().parent.parent
    return root / SHARED_KEY_RELATIVE_PATH


def load_pinned_shared_key(path: Path) -> paramiko.RSAKey:
    try:
        key = paramiko.RSAKey.from_private_key_file(str(path))
    except (OSError, paramiko.SSHException) as error:
        raise RuntimeError("The bundled shared Kindle key is missing or unreadable.") from error
    if openssh_sha256_fingerprint(key) != SHARED_KEY_FINGERPRINT:
        raise RuntimeError("The bundled shared Kindle key failed its pinned fingerprint check.")
    return key


def public_key_file_fingerprint(path: Path) -> str | None:
    try:
        fields = path.read_text(encoding="ascii").strip().split()
        if len(fields) < 2 or fields[0] != "ssh-rsa":
            return None
        blob = base64.b64decode(fields[1], validate=True)
        return openssh_sha256_fingerprint(paramiko.RSAKey(data=blob))
    except (OSError, ValueError, paramiko.SSHException):
        return None


def public_key_identity(public_line: str) -> tuple[str, str] | None:
    """Return the OpenSSH key type and blob, deliberately ignoring its comment."""
    fields = public_line.strip().split()
    if len(fields) < 2 or fields[0] != "ssh-rsa":
        return None
    try:
        base64.b64decode(fields[1], validate=True)
    except (ValueError, binascii.Error):
        return None
    return fields[0], fields[1]


def authorized_keys_contains_identity(contents: str, public_line: str) -> bool:
    identity = public_key_identity(public_line)
    if identity is None:
        raise ValueError("The app public key line is invalid.")
    return any(public_key_identity(line) == identity for line in contents.splitlines())


def authorized_key_install_command(public_line: str) -> str:
    identity = public_key_identity(public_line)
    if identity is None:
        raise ValueError("The app public key line is invalid.")
    key_type, key_blob = identity
    ssh_directory = shlex.quote("/mnt/us/koreader/settings/SSH")
    authorized_keys = shlex.quote("/mnt/us/koreader/settings/SSH/authorized_keys")
    awk_program = shlex.quote(
        "$1 == key_type && $2 == key_blob { found = 1 } "
        "END { exit(found ? 0 : 1) }"
    )
    return (
        f"mkdir -p {ssh_directory} && touch {authorized_keys} && "
        f"(awk -v key_type={shlex.quote(key_type)} "
        f"-v key_blob={shlex.quote(key_blob)} {awk_program} "
        f"{authorized_keys} 2>/dev/null || "
        f"printf '%s\\n' {shlex.quote(public_line)} >> {authorized_keys})"
    )


class KeyStore:
    def __init__(self, root: Path, shared_private_key_path: Path | None = None) -> None:
        self.root = root
        self.shared_private_key_path = shared_private_key_path or bundled_shared_private_key_path()
        self.legacy_private_key_path = root / "kindle_sender_rsa"
        self.legacy_public_key_path = root / "kindle_sender_rsa.pub"
        self.legacy_backup_root = root / "legacy-key-backups"
        self._shared_key: paramiko.RSAKey | None = None

    def _legacy_paths_to_back_up(self) -> list[Path]:
        return [
            path
            for path in (self.legacy_private_key_path, self.legacy_public_key_path)
            if path.is_file()
        ]

    def _back_up_legacy_keys(self) -> None:
        paths = self._legacy_paths_to_back_up()
        if not paths:
            return

        self.legacy_backup_root.mkdir(parents=True, exist_ok=True)
        try:
            self.legacy_backup_root.chmod(0o700)
        except OSError:
            pass
        timestamp = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%z")
        backup = self.legacy_backup_root / f"legacy-{timestamp}-{uuid.uuid4().hex[:12]}"
        backup.mkdir()
        try:
            backup.chmod(0o700)
        except OSError:
            pass
        for source in paths:
            destination = backup / source.name
            source.replace(destination)
            if source == self.legacy_private_key_path:
                try:
                    destination.chmod(0o600)
                except OSError:
                    pass

    def ensure(self) -> paramiko.RSAKey:
        if self._shared_key is not None:
            return self._shared_key
        key = load_pinned_shared_key(self.shared_private_key_path)
        self.root.mkdir(parents=True, exist_ok=True)
        self._back_up_legacy_keys()
        self._shared_key = key
        return key

    @property
    def public_key_line(self) -> str:
        key = self.load()
        return f"{key.get_name()} {key.get_base64()} {KEY_COMMENT}"

    def load(self) -> paramiko.RSAKey:
        return self.ensure()


def candidate_mount_roots() -> list[Path]:
    candidates: set[Path] = set()
    try:
        for partition in psutil.disk_partitions(all=True):
            if partition.mountpoint:
                candidates.add(Path(partition.mountpoint))
    except (OSError, RuntimeError):
        pass

    system = platform.system()
    if system == "Windows":
        for letter in "DEFGHIJKLMNOPQRSTUVWXYZ":
            candidates.add(Path(f"{letter}:\\"))
    elif system == "Darwin":
        candidates.update(Path("/Volumes").glob("*"))
    else:
        for parent in (
            Path("/media") / os.environ.get("USER", ""),
            Path("/run/media") / os.environ.get("USER", ""),
            Path("/mnt"),
        ):
            if parent.is_dir():
                candidates.update(parent.glob("*"))

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = str(candidate).rstrip("/\\").lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique.append(candidate)
    return unique


def find_mounted_kindles() -> list[Path]:
    kindles: list[Path] = []
    for root in candidate_mount_roots():
        try:
            if (root / "documents").is_dir() and (root / "koreader").is_dir():
                kindles.append(root)
        except (OSError, PermissionError):
            continue
    return kindles


def install_public_key_on_usb(key_store: KeyStore) -> list[Path]:
    installed: list[Path] = []
    public_line = key_store.public_key_line
    for root in find_mounted_kindles():
        ssh_directory = root / "koreader" / "settings" / "SSH"
        authorized_keys = ssh_directory / "authorized_keys"
        ssh_directory.mkdir(parents=True, exist_ok=True)

        existing = ""
        if authorized_keys.exists():
            existing = authorized_keys.read_text(encoding="utf-8", errors="replace")
        if not authorized_keys_contains_identity(existing, public_line):
            prefix = "" if not existing or existing.endswith(("\n", "\r")) else "\n"
            with authorized_keys.open("a", encoding="ascii", newline="\n") as handle:
                handle.write(prefix + public_line + "\n")
        installed.append(root)
    return installed


def private_local_networks() -> list[ipaddress.IPv4Network]:
    networks: set[ipaddress.IPv4Network] = set()
    try:
        interfaces = psutil.net_if_addrs()
    except (OSError, RuntimeError):
        interfaces = {}

    for addresses in interfaces.values():
        for address in addresses:
            if address.family != socket.AF_INET or not address.address or not address.netmask:
                continue
            try:
                interface = ipaddress.ip_interface(f"{address.address}/{address.netmask}")
            except ValueError:
                continue
            ip = interface.ip
            if not ip.is_private or ip.is_loopback or ip.is_link_local:
                continue
            network = interface.network
            if network.num_addresses > 256:
                network = ipaddress.ip_network(f"{ip}/24", strict=False)
            networks.add(network)
    return sorted(networks, key=lambda item: (int(item.network_address), item.prefixlen))


def connect_ssh(endpoint: Endpoint, key: paramiko.RSAKey, timeout: float = 5.0) -> paramiko.SSHClient:
    last_error: Exception | None = None
    attempts = (
        None,
        {"pubkeys": ["rsa-sha2-512", "rsa-sha2-256"]},
    )
    for disabled_algorithms in attempts:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                hostname=endpoint.host,
                port=endpoint.port,
                username="root",
                pkey=key,
                timeout=timeout,
                banner_timeout=timeout,
                auth_timeout=timeout,
                allow_agent=False,
                look_for_keys=False,
                compress=True,
                disabled_algorithms=disabled_algorithms,
            )
            return client
        except Exception as error:
            last_error = error
            client.close()
    if last_error:
        raise last_error
    raise RuntimeError("SSH connection failed")


def connect_ssh_without_password(endpoint: Endpoint, timeout: float = 5.0) -> paramiko.SSHClient:
    sock: socket.socket | None = None
    transport: paramiko.Transport | None = None
    try:
        sock = socket.create_connection((endpoint.host, endpoint.port), timeout=timeout)
        transport = paramiko.Transport(sock)
        transport.banner_timeout = timeout
        transport.auth_timeout = timeout
        transport.start_client(timeout=timeout)
        allowed: list[str] = []
        try:
            transport.auth_none("root")
        except paramiko.BadAuthenticationType as error:
            allowed = list(error.allowed_types)
        except paramiko.AuthenticationException:
            pass
        if not transport.is_authenticated() and (not allowed or "password" in allowed):
            try:
                transport.auth_password("root", "", fallback=False)
            except paramiko.AuthenticationException:
                pass
        if not transport.is_authenticated():
            raise paramiko.AuthenticationException(
                "KOReader rejected login without a password. Stop SSH, enable 'Login without password (DANGEROUS)', then start SSH again."
            )
        transport.set_keepalive(20)
        client = paramiko.SSHClient()
        client._transport = transport
        return client
    except Exception:
        if transport:
            transport.close()
        elif sock:
            sock.close()
        raise


def verify_koreader_client(client: paramiko.SSHClient) -> bool:
    _, stdout, _ = client.exec_command(
        "test -d /mnt/us/koreader && printf __AGINTI_KOREADER_KINDLE__",
        timeout=5,
    )
    output = stdout.read().decode("utf-8", errors="replace")
    return stdout.channel.recv_exit_status() == 0 and "__AGINTI_KOREADER_KINDLE__" in output


def kindle_disk_usage(endpoint: Endpoint, key_store: KeyStore) -> dict[str, int]:
    client: paramiko.SSHClient | None = None
    try:
        client = connect_ssh(endpoint, key_store.load(), timeout=6)
        _, stdout, _ = client.exec_command(
            "df -Pk /mnt/us 2>/dev/null | tail -n 1",
            timeout=6,
        )
        line = stdout.read().decode("utf-8", errors="replace").strip()
        if stdout.channel.recv_exit_status() != 0:
            return {}
        fields = line.split()
        if len(fields) < 6:
            return {}
        total = int(fields[-5]) * 1024
        used = int(fields[-4]) * 1024
        free = int(fields[-3]) * 1024
        return {"total": total, "used": used, "free": free}
    except (OSError, ValueError, paramiko.SSHException):
        return {}
    finally:
        if client:
            client.close()


def install_public_key_over_ssh(endpoint: Endpoint, key_store: KeyStore) -> None:
    client: paramiko.SSHClient | None = None
    try:
        client = connect_ssh_without_password(endpoint, timeout=6)
        if not verify_koreader_client(client):
            raise RuntimeError(f"{endpoint.display} accepts SSH but is not a KOReader Kindle.")
        command = authorized_key_install_command(key_store.public_key_line)
        _, stdout, stderr = client.exec_command(command, timeout=8)
        if stdout.channel.recv_exit_status() != 0:
            detail = stderr.read().decode("utf-8", errors="replace").strip()
            raise RuntimeError(detail or "Could not install the app public key on the Kindle.")
    finally:
        if client:
            client.close()

    verification: paramiko.SSHClient | None = None
    try:
        verification = connect_ssh(endpoint, key_store.load(), timeout=6)
        if not verify_koreader_client(verification):
            raise RuntimeError("The public key was written, but the endpoint is not a KOReader Kindle.")
    except Exception as error:
        raise RuntimeError(
            "The public key was installed, but key login was not accepted yet. Stop and restart KOReader SSH, then connect again."
        ) from error
    finally:
        if verification:
            verification.close()


def authenticate_koreader(endpoint: Endpoint, key_store: KeyStore, allow_no_password: bool) -> str:
    reachable, detail = probe_endpoint(endpoint, timeout=1.2)
    if not reachable:
        raise RuntimeError(detail)
    client: paramiko.SSHClient | None = None
    key_error = ""
    try:
        client = connect_ssh(endpoint, key_store.load(), timeout=4.5)
        if not verify_koreader_client(client):
            raise RuntimeError(f"{endpoint.display} is an SSH server but not a KOReader Kindle.")
        return "key"
    except Exception as error:
        key_error = str(error)
    finally:
        if client:
            client.close()

    if allow_no_password:
        install_public_key_over_ssh(endpoint, key_store)
        return "bootstrapped"
    raise RuntimeError(
        "SSH is reachable, but the pinned shared Kindle key is not authorized. "
        "Enable the no-password checkbox for first-time pairing, or pair by USB. "
        f"Technical detail: {key_error}"
    )


class WorkerSignals(QObject):
    status = Signal(str)
    progress = Signal(int, str)
    result = Signal(object)
    error = Signal(str)
    finished = Signal()


class DiscoveryWorker(QRunnable):
    def __init__(
        self,
        key_store: KeyStore,
        preferred_ip: str = "",
        allow_no_password: bool = False,
    ) -> None:
        super().__init__()
        self.key_store = key_store
        self.preferred_ip = preferred_ip.strip()
        self.allow_no_password = allow_no_password
        self.signals = WorkerSignals()
        self.cancelled = threading.Event()

    def cancel(self) -> None:
        self.cancelled.set()

    def run(self) -> None:
        try:
            self.key_store.load()
            preferred_endpoint: Endpoint | None = None
            preferred_error = ""
            if self.preferred_ip:
                try:
                    preferred_endpoint = parse_endpoint(self.preferred_ip)
                except ValueError as error:
                    raise RuntimeError(tr("supplied_invalid", error=error)) from error
                self.signals.status.emit(tr("testing_supplied", address=preferred_endpoint.display))
                try:
                    auth = authenticate_koreader(
                        preferred_endpoint,
                        self.key_store,
                        self.allow_no_password,
                    )
                    self.signals.result.emit(
                        {
                            "ip": preferred_endpoint.display,
                            "auth": auth,
                            "supplied": True,
                            "storage": kindle_disk_usage(preferred_endpoint, self.key_store),
                        }
                    )
                    return
                except Exception as error:
                    preferred_error = str(error)

            networks = private_local_networks()
            if not networks:
                raise RuntimeError(tr("no_private_network"))

            candidates: list[Endpoint] = []
            seen: set[str] = set()
            if preferred_endpoint:
                seen.add(preferred_endpoint.host)
            for network in networks:
                for host in network.hosts():
                    value = str(host)
                    if value not in seen:
                        seen.add(value)
                        candidates.append(Endpoint(value, SSH_PORT))

            self.signals.status.emit(tr("searching_networks", count=len(networks)))
            open_hosts: list[Endpoint] = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=96) as executor:
                futures = {
                    executor.submit(probe_endpoint, endpoint, 0.55): endpoint
                    for endpoint in candidates
                }
                for future in concurrent.futures.as_completed(futures):
                    if self.cancelled.is_set():
                        return
                    try:
                        if future.result()[0]:
                            open_hosts.append(futures[future])
                    except Exception:
                        continue

            authentication_errors: list[str] = []
            for endpoint in open_hosts:
                if self.cancelled.is_set():
                    return
                self.signals.status.emit(tr("checking_possible", address=endpoint.display))
                try:
                    auth = authenticate_koreader(
                        endpoint,
                        self.key_store,
                        self.allow_no_password,
                    )
                    self.signals.result.emit(
                        {
                            "ip": endpoint.display,
                            "auth": auth,
                            "supplied": False,
                            "storage": kindle_disk_usage(endpoint, self.key_store),
                        }
                    )
                    return
                except Exception as error:
                    authentication_errors.append(f"{endpoint.display}: {error}")

            details: list[str] = []
            if preferred_endpoint:
                details.append(
                    tr("supplied_tested", address=preferred_endpoint.display, error=preferred_error)
                )
            if open_hosts:
                details.append(
                    tr("endpoints_unverified", count=len(open_hosts))
                )
            else:
                details.append(
                    tr("no_tcp_answer")
                )
            if authentication_errors:
                details.append(authentication_errors[0])
            if not self.allow_no_password:
                details.append(
                    tr("new_computer_help")
                )
            raise RuntimeError("\n\n".join(details))
        except Exception as error:
            self.signals.error.emit(str(error))
        finally:
            self.signals.finished.emit()


class TransferWorker(QRunnable):
    def __init__(self, ip: str, files: list[Path], key_store: KeyStore) -> None:
        super().__init__()
        self.endpoint = parse_endpoint(ip)
        self.ip = self.endpoint.display
        self.files = files
        self.key_store = key_store
        self.signals = WorkerSignals()
        self.cancelled = threading.Event()
        self.last_progress_time = 0.0

    def cancel(self) -> None:
        self.cancelled.set()

    def emit_progress(
        self,
        completed_before: int,
        total_size: int,
        current_size: int,
        current_sent: int,
        filename: str,
    ) -> None:
        now = time.monotonic()
        if current_sent < current_size and now - self.last_progress_time < 0.08:
            return
        self.last_progress_time = now
        overall = completed_before + min(current_sent, current_size)
        percent = 100 if total_size <= 0 else int(overall * 100 / total_size)
        self.signals.progress.emit(
            max(0, min(100, percent)),
            tr(
                "sending_file",
                name=filename,
                sent=human_size(current_sent),
                size=human_size(current_size),
            ),
        )

    def run(self) -> None:
        client: paramiko.SSHClient | None = None
        try:
            valid_files = [path for path in self.files if path.is_file()]
            if not valid_files:
                raise RuntimeError(tr("no_readable_files"))

            total_size = sum(path.stat().st_size for path in valid_files)
            key = self.key_store.load()
            self.signals.status.emit(tr("connecting_secure", address=self.ip))
            client = connect_ssh(self.endpoint, key, timeout=6)

            command = f"mkdir -p {shlex.quote(REMOTE_BOOK_DIRECTORY)}"
            _, stdout, stderr = client.exec_command(command, timeout=8)
            if stdout.channel.recv_exit_status() != 0:
                detail = stderr.read().decode("utf-8", errors="replace").strip()
                raise RuntimeError(detail or tr("create_books_failed"))

            completed = 0
            try:
                sftp = client.open_sftp()
            except Exception:
                sftp = None

            if sftp is not None:
                try:
                    for path in valid_files:
                        if self.cancelled.is_set():
                            raise RuntimeError(tr("transfer_cancelled"))
                        size = path.stat().st_size
                        name = path.name
                        remote_path = posixpath.join(REMOTE_BOOK_DIRECTORY, name)

                        def sftp_progress(sent: int, expected: int, base=completed, filename=name) -> None:
                            self.emit_progress(base, total_size, expected, sent, filename)

                        sftp.put(str(path), remote_path, callback=sftp_progress, confirm=True)
                        completed += size
                finally:
                    sftp.close()
            else:
                transport = client.get_transport()
                if transport is None:
                    raise RuntimeError(tr("connection_closed"))
                with SCPClient(transport, socket_timeout=30) as scp_client:
                    for path in valid_files:
                        if self.cancelled.is_set():
                            raise RuntimeError(tr("transfer_cancelled"))
                        size = path.stat().st_size
                        name = path.name

                        def scp_progress(
                            remote_name: bytes,
                            expected: int,
                            sent: int,
                            base=completed,
                            filename=name,
                        ) -> None:
                            self.emit_progress(base, total_size, expected, sent, filename)

                        scp_client.progress = scp_progress
                        scp_client.put(
                            str(path),
                            remote_path=REMOTE_BOOK_DIRECTORY + "/",
                            preserve_times=True,
                        )
                        completed += size

            self.signals.progress.emit(100, tr("sent_book_count", count=len(valid_files)))
            self.signals.result.emit(
                {"count": len(valid_files), "bytes": total_size, "ip": self.ip}
            )
        except Exception as error:
            self.signals.error.emit(str(error))
        finally:
            if client:
                client.close()
            self.signals.finished.emit()


class DropArea(QFrame):
    files_dropped = Signal(object)
    clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("dropArea")
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(132)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(5)

        icon = QLabel("+")
        icon.setObjectName("dropIcon")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon)
        self.title = QLabel()
        self.title.setObjectName("dropTitle")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title)
        self.subtitle = QLabel()
        self.subtitle.setObjectName("muted")
        self.subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.subtitle)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [
            Path(url.toLocalFile())
            for url in event.mimeData().urls()
            if url.isLocalFile()
        ]
        self.files_dropped.emit(paths)
        event.acceptProposedAction()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.data_root = application_data_directory()
        self.settings = SettingsStore(self.data_root)
        detected_language = normalize_language(QLocale.system().name())
        self.language = set_language(self.settings.language or detected_language)
        if not self.settings.language:
            self.settings.language = self.language
        self.key_store = KeyStore(self.data_root / "keys")
        self.key_store.ensure()
        self.thread_pool = QThreadPool.globalInstance()
        self.active_worker: DiscoveryWorker | TransferWorker | None = None
        self.discovered_ip = ""
        self.selected_files: dict[str, Path] = {}
        self.current_storage = self.settings.last_storage
        self.localized_widgets: list[tuple[QWidget, str, dict[str, object]]] = []

        self.setWindowTitle(f"{APP_NAME} | {ORGANIZATION}")
        self.setWindowIcon(make_app_icon())
        self.resize(1180, 860)
        self.setMinimumSize(720, 620)
        self.build_ui()
        self.apply_style()
        self.retranslate_ui()
        QTimer.singleShot(350, self.automatic_usb_pairing)
        QTimer.singleShot(700, self.automatic_windows_install)
        QTimer.singleShot(80, self.animate_in)

    def localized(self, widget: QWidget, key: str, **values: object) -> QWidget:
        self.set_localized_text(widget, key, **values)
        return widget

    def set_localized_text(self, widget: QWidget, key: str, **values: object) -> None:
        for index, (known_widget, _, _) in enumerate(self.localized_widgets):
            if known_widget is widget:
                self.localized_widgets[index] = (widget, key, values)
                break
        else:
            self.localized_widgets.append((widget, key, values))
        widget.setText(tr(key, **values))

    def build_ui(self) -> None:
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setCentralWidget(self.scroll)
        canvas = QWidget()
        canvas.setObjectName("canvas")
        self.scroll.setWidget(canvas)
        outer = QVBoxLayout(canvas)
        outer.setContentsMargins(28, 20, 28, 28)
        outer.setSpacing(18)

        self.content = QWidget()
        content = self.content
        content.setMaximumWidth(1400)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(18)
        outer.addWidget(content, 0, Qt.AlignmentFlag.AlignHCenter)

        header = QFrame()
        header.setObjectName("header")
        self.header_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight, header)
        header_layout = self.header_layout
        header_layout.setContentsMargins(0, 2, 0, 6)
        header_layout.setSpacing(18)
        identity_row = QHBoxLayout()
        identity_row.setSpacing(11)
        mark = QLabel("K")
        mark.setObjectName("mark")
        mark.setFixedSize(42, 42)
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        identity_row.addWidget(mark)
        brand_box = QVBoxLayout()
        brand_box.setSpacing(2)
        brand = QLabel(APP_NAME)
        brand.setObjectName("brand")
        brand.setMinimumHeight(25)
        brand_box.addWidget(brand)
        byline = QLabel("by AgInTi Flow · LazyingArt LLC")
        byline.setObjectName("muted")
        byline.setWordWrap(True)
        byline.setMinimumHeight(18)
        brand_box.addWidget(byline)
        identity_row.addLayout(brand_box)
        identity_row.addStretch(1)
        header_layout.addLayout(identity_row, 1)

        self.header_actions = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        header_actions = self.header_actions
        header_actions.setSpacing(10)
        self.language_select = QComboBox()
        self.language_select.setObjectName("languageSelect")
        self.language_select.setMinimumWidth(210)
        self.language_select.setMaximumWidth(280)
        self.language_select.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        for code, native_name in LANGUAGES:
            self.language_select.addItem(native_name, code)
        selected_index = self.language_select.findData(self.language)
        self.language_select.setCurrentIndex(max(0, selected_index))
        self.language_select.currentIndexChanged.connect(self.change_language)
        header_actions.addWidget(self.language_select)
        self.books_button = self.localized(QPushButton(), "free_books")
        self.books_button.setObjectName("primaryButton")
        self.books_button.setMinimumWidth(210)
        self.books_button.setMaximumWidth(280)
        self.books_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(LEARN_WEBSITE)))
        header_actions.addWidget(self.books_button)
        self.website_button = self.localized(QPushButton(), "guide_downloads")
        self.website_button.setObjectName("ghostButton")
        self.website_button.setMinimumWidth(210)
        self.website_button.setMaximumWidth(280)
        self.website_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(WEBSITE)))
        header_actions.addWidget(self.website_button)
        header_actions.addStretch(1)
        header_layout.addLayout(header_actions, 0)
        content_layout.addWidget(header)

        hero = QFrame()
        hero.setObjectName("hero")
        self.hero_layout = QHBoxLayout(hero)
        self.hero_layout.setContentsMargins(34, 30, 34, 30)
        self.hero_layout.setSpacing(24)
        hero_copy = QVBoxLayout()
        hero_copy.setSpacing(9)
        eyebrow = self.localized(QLabel(), "hero_eyebrow")
        eyebrow.setObjectName("eyebrow")
        hero_copy.addWidget(eyebrow)
        headline = self.localized(QLabel(), "hero_title")
        headline.setWordWrap(True)
        headline.setObjectName("headline")
        headline.setMinimumHeight(46)
        headline.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding)
        self.headline = headline
        hero_copy.addWidget(headline)
        description = self.localized(QLabel(), "hero_description")
        description.setWordWrap(True)
        description.setObjectName("heroDescription")
        description.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding)
        hero_copy.addWidget(description)
        self.primary_status = self.localized(QLabel(), "preparing_key")
        self.primary_status.setObjectName("statusPill")
        self.primary_status.setWordWrap(True)
        hero_copy.addWidget(self.primary_status, 0, Qt.AlignmentFlag.AlignLeft)
        self.hero_layout.addLayout(hero_copy, 5)

        steps = QFrame()
        steps.setObjectName("steps")
        steps.setMinimumWidth(360)
        self.steps_panel = steps
        steps_layout = QVBoxLayout(steps)
        steps_layout.setContentsMargins(20, 18, 20, 18)
        steps_layout.setSpacing(10)
        steps_title = self.localized(QLabel(), "on_kindle")
        steps_title.setObjectName("cardTitle")
        steps_layout.addWidget(steps_title)
        for number, key in (
            ("1", "step_network"),
            ("2", "step_open"),
            ("3", "step_ssh"),
        ):
            row = QHBoxLayout()
            badge = QLabel(number)
            badge.setObjectName("stepBadge")
            badge.setFixedSize(26, 26)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            row.addWidget(badge)
            label = self.localized(QLabel(), key)
            label.setWordWrap(True)
            label.setObjectName("stepText")
            row.addWidget(label, 1)
            steps_layout.addLayout(row)
        self.hero_layout.addWidget(steps, 3)
        content_layout.addWidget(hero)

        device_card = QFrame()
        device_card.setObjectName("card")
        device_layout = QVBoxLayout(device_card)
        device_layout.setContentsMargins(22, 18, 22, 18)
        device_layout.setSpacing(15)
        self.device_top_layout = QHBoxLayout()
        device_info = QVBoxLayout()
        device_info.setSpacing(2)
        heading = self.localized(QLabel(), "your_kindle")
        heading.setObjectName("cardTitle")
        device_info.addWidget(heading)
        self.device_detail = self.localized(QLabel(), "device_hint")
        self.device_detail.setObjectName("muted")
        self.device_detail.setWordWrap(True)
        device_info.addWidget(self.device_detail)
        self.device_top_layout.addLayout(device_info, 1)
        self.manual_ip = QComboBox()
        self.manual_ip.setObjectName("addressBox")
        self.manual_ip.setEditable(True)
        self.manual_ip.addItems(self.settings.recent_addresses)
        self.manual_ip.setEditText(self.settings.last_ip)
        self.manual_ip.setMinimumWidth(260)
        self.manual_ip.setMaximumWidth(360)
        if self.manual_ip.lineEdit():
            self.manual_ip.lineEdit().setClearButtonEnabled(True)
        self.device_top_layout.addWidget(self.manual_ip)
        self.usb_button = self.localized(QPushButton(), "pair_usb")
        self.usb_button.setObjectName("secondaryButton")
        self.usb_button.clicked.connect(self.pair_over_usb)
        self.device_top_layout.addWidget(self.usb_button)
        self.find_button = self.localized(QPushButton(), "connect_find")
        self.find_button.setObjectName("primaryButton")
        self.find_button.clicked.connect(self.start_discovery)
        self.device_top_layout.addWidget(self.find_button)
        device_layout.addLayout(self.device_top_layout)

        self.connection_options_layout = QHBoxLayout()
        self.no_password_checkbox = self.localized(QCheckBox(), "no_password_label")
        self.no_password_checkbox.setChecked(self.settings.no_password)
        self.no_password_checkbox.toggled.connect(self.remember_no_password)
        self.connection_options_layout.addWidget(self.no_password_checkbox)
        self.connection_options_layout.addStretch(1)
        self.firewall_button = self.localized(QPushButton(), "firewall_help")
        self.firewall_button.setObjectName("textButton")
        self.firewall_button.setVisible(platform.system() == "Windows")
        self.firewall_button.clicked.connect(self.firewall_help)
        self.connection_options_layout.addWidget(self.firewall_button)
        device_layout.addLayout(self.connection_options_layout)

        storage_panel = QFrame()
        storage_panel.setObjectName("storagePanel")
        storage_layout = QVBoxLayout(storage_panel)
        storage_layout.setContentsMargins(14, 11, 14, 11)
        storage_layout.setSpacing(7)
        self.storage_top_layout = QHBoxLayout()
        storage_top = self.storage_top_layout
        storage_title = self.localized(QLabel(), "storage")
        storage_title.setObjectName("storageTitle")
        storage_top.addWidget(storage_title)
        storage_top.addStretch(1)
        self.storage_detail = QLabel()
        self.storage_detail.setObjectName("muted")
        self.storage_detail.setWordWrap(True)
        storage_top.addWidget(self.storage_detail)
        storage_layout.addLayout(storage_top)
        self.storage_bar = QProgressBar()
        self.storage_bar.setObjectName("storageBar")
        self.storage_bar.setRange(0, 100)
        self.storage_bar.setTextVisible(False)
        storage_layout.addWidget(self.storage_bar)
        device_layout.addWidget(storage_panel)
        content_layout.addWidget(device_card)

        books_card = QFrame()
        books_card.setObjectName("card")
        books_layout = QVBoxLayout(books_card)
        books_layout.setContentsMargins(22, 20, 22, 20)
        books_layout.setSpacing(13)
        self.books_header_layout = QHBoxLayout()
        books_header = self.books_header_layout
        title = self.localized(QLabel(), "books_to_send")
        title.setObjectName("cardTitle")
        title.setWordWrap(True)
        books_header.addWidget(title)
        books_header.addStretch(1)
        self.book_count = QLabel()
        self.book_count.setObjectName("countPill")
        books_header.addWidget(self.book_count)
        books_layout.addLayout(books_header)
        self.drop_area = DropArea()
        self.set_localized_text(self.drop_area.title, "drop_books")
        self.set_localized_text(self.drop_area.subtitle, "drop_subtitle")
        self.drop_area.clicked.connect(self.choose_files)
        self.drop_area.files_dropped.connect(self.add_files)
        books_layout.addWidget(self.drop_area)

        self.file_list = QTreeWidget()
        self.file_list.setObjectName("fileList")
        self.file_list.setColumnCount(3)
        self.file_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.file_list.setRootIsDecorated(False)
        self.file_list.setMinimumHeight(125)
        self.file_list.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.file_list.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.file_list.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.file_list.hide()
        books_layout.addWidget(self.file_list)

        self.file_actions_layout = QHBoxLayout()
        choose_button = self.localized(QPushButton(), "choose_books")
        choose_button.setObjectName("secondaryButton")
        choose_button.clicked.connect(self.choose_files)
        self.file_actions_layout.addWidget(choose_button)
        remove_button = self.localized(QPushButton(), "remove_selected")
        remove_button.setObjectName("textButton")
        remove_button.clicked.connect(self.remove_selected)
        self.file_actions_layout.addWidget(remove_button)
        self.file_actions_layout.addStretch(1)
        self.destination = QLabel()
        self.destination.setObjectName("monoMuted")
        self.destination.setWordWrap(True)
        self.file_actions_layout.addWidget(self.destination)
        books_layout.addLayout(self.file_actions_layout)
        content_layout.addWidget(books_card)

        history_card = QFrame()
        history_card.setObjectName("card")
        history_layout = QVBoxLayout(history_card)
        history_layout.setContentsMargins(22, 18, 22, 18)
        history_layout.setSpacing(10)
        self.history_header_layout = QHBoxLayout()
        history_header = self.history_header_layout
        history_title = self.localized(QLabel(), "recent_transfers")
        history_title.setObjectName("cardTitle")
        history_title.setWordWrap(True)
        history_header.addWidget(history_title)
        history_header.addStretch(1)
        clear_history_button = self.localized(QPushButton(), "clear_history")
        clear_history_button.setObjectName("textButton")
        clear_history_button.clicked.connect(self.clear_transfer_history)
        history_header.addWidget(clear_history_button)
        history_layout.addLayout(history_header)
        self.history_empty = self.localized(QLabel(), "no_history")
        self.history_empty.setObjectName("muted")
        history_layout.addWidget(self.history_empty)
        self.history_list = QTreeWidget()
        self.history_list.setObjectName("fileList")
        self.history_list.setColumnCount(4)
        self.history_list.setRootIsDecorated(False)
        self.history_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.history_list.setMaximumHeight(170)
        self.history_list.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.history_list.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.history_list.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.history_list.header().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        history_layout.addWidget(self.history_list)
        content_layout.addWidget(history_card)

        self.install_panel = QFrame()
        self.install_panel.setObjectName("installPanel")
        self.install_panel.setVisible(platform.system() == "Windows")
        self.install_layout = QHBoxLayout(self.install_panel)
        self.install_layout.setContentsMargins(18, 14, 18, 14)
        self.install_layout.setSpacing(12)
        install_copy = QVBoxLayout()
        install_title = self.localized(QLabel(), "install_title")
        install_title.setObjectName("storageTitle")
        install_copy.addWidget(install_title)
        install_body = self.localized(QLabel(), "install_body")
        install_body.setObjectName("muted")
        install_body.setWordWrap(True)
        install_copy.addWidget(install_body)
        self.install_layout.addLayout(install_copy, 1)
        start_button = self.localized(QPushButton(), "add_start")
        start_button.setObjectName("secondaryButton")
        start_button.clicked.connect(self.install_to_start)
        self.install_layout.addWidget(start_button)
        taskbar_button = self.localized(QPushButton(), "add_taskbar")
        taskbar_button.setObjectName("primaryButton")
        taskbar_button.clicked.connect(self.install_to_taskbar)
        self.install_layout.addWidget(taskbar_button)
        content_layout.addWidget(self.install_panel)

        action_card = QFrame()
        action_card.setObjectName("actionCard")
        self.action_layout = QHBoxLayout(action_card)
        action_layout = self.action_layout
        action_layout.setContentsMargins(22, 17, 22, 17)
        action_layout.setSpacing(16)
        status_box = QVBoxLayout()
        status_box.setSpacing(4)
        self.operation_status = self.localized(QLabel(), "ready_pairing")
        self.operation_status.setObjectName("operationStatus")
        self.operation_status.setWordWrap(True)
        status_box.addWidget(self.operation_status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.hide()
        status_box.addWidget(self.progress)
        action_layout.addLayout(status_box, 1)
        self.cancel_button = self.localized(QPushButton(), "cancel")
        self.cancel_button.setObjectName("textButton")
        self.cancel_button.clicked.connect(self.cancel_operation)
        self.cancel_button.hide()
        action_layout.addWidget(self.cancel_button)
        self.send_button = self.localized(QPushButton(), "send_books")
        self.send_button.setObjectName("sendButton")
        self.send_button.setEnabled(False)
        self.send_button.clicked.connect(self.start_transfer)
        action_layout.addWidget(self.send_button)
        content_layout.addWidget(action_card)

        self.footer_layout = QHBoxLayout()
        self.footer_text = QLabel()
        self.footer_text.setObjectName("footer")
        self.footer_text.setWordWrap(True)
        self.footer_layout.addWidget(self.footer_text)
        self.footer_layout.addStretch(1)
        links = QLabel(
            '<a href="https://flow.lazying.art">flow.lazying.art</a> &nbsp;·&nbsp; '
            '<a href="https://lazying.art">lazying.art</a>'
        )
        links.setObjectName("footerLinks")
        links.setOpenExternalLinks(True)
        self.footer_layout.addWidget(links)
        content_layout.addLayout(self.footer_layout)

    def apply_style(self) -> None:
        self.setStyleSheet(
            """
            QWidget#canvas { background: #F6F4ED; color: #17201C; }
            QFrame#header { background: transparent; }
            QLabel#mark {
                background: #073C32; color: #FBFAF6; border-radius: 12px;
                font-family: Georgia, serif; font-size: 22px; font-weight: 700;
            }
            QLabel#brand {
                color: #17201C; font-family: Georgia, "Palatino Linotype", serif;
                font-size: 18px; font-weight: 700;
            }
            QLabel#muted, QLabel#monoMuted, QLabel#footer { color: #64716B; }
            QLabel#monoMuted {
                font-family: Consolas, "SFMono-Regular", monospace; font-size: 11px;
            }
            QLabel#footer, QLabel#footerLinks { font-size: 11px; }
            QLabel#footerLinks { color: #0D5C4B; }
            QFrame#hero {
                background: #073C32; border: 1px solid #073C32; border-radius: 22px;
            }
            QLabel#eyebrow {
                color: #E7AC59; font-size: 11px; font-weight: 700; letter-spacing: 2px;
            }
            QLabel#headline {
                color: #FBFAF6; font-family: Georgia, "Palatino Linotype", serif;
                font-size: 31px; font-weight: 700;
            }
            QLabel#heroDescription { color: #C9E2D8; font-size: 14px; }
            QLabel#statusPill {
                color: #FBFAF6; background: rgba(255,255,255,0.10);
                border: 1px solid rgba(255,255,255,0.16); border-radius: 10px;
                padding: 7px 11px; font-size: 12px;
            }
            QFrame#steps { background: #FBFAF6; border-radius: 16px; }
            QLabel#stepBadge {
                background: #E8F3EE; color: #0D5C4B; border-radius: 13px; font-weight: 700;
            }
            QLabel#stepText { color: #27332E; font-size: 12px; }
            QFrame#card {
                background: #FFFFFF; border: 1px solid #DDDCD4; border-radius: 16px;
            }
            QFrame#actionCard {
                background: #FFF8EB; border: 1px solid #EBD9B9; border-radius: 16px;
            }
            QLabel#cardTitle {
                color: #17201C; font-family: Georgia, "Palatino Linotype", serif;
                font-size: 17px; font-weight: 700;
            }
            QLabel#countPill {
                color: #0D5C4B; background: #E8F3EE; border-radius: 10px;
                padding: 4px 9px; font-weight: 600;
            }
            QFrame#dropArea {
                background: #FAFCFA; border: 2px dashed #A8C9BC; border-radius: 13px;
            }
            QFrame#dropArea:hover { background: #F0F7F3; border-color: #0D5C4B; }
            QLabel#dropIcon { color: #0D5C4B; font-size: 25px; }
            QLabel#dropTitle { color: #17201C; font-size: 14px; font-weight: 700; }
            QPushButton {
                min-height: 36px; padding: 0 16px; border-radius: 10px;
                font-size: 12px; font-weight: 650;
            }
            QPushButton#primaryButton, QPushButton#sendButton {
                background: #0D5C4B; color: #FFFFFF; border: 1px solid #0D5C4B;
            }
            QPushButton#primaryButton:hover, QPushButton#sendButton:hover {
                background: #0A4A3D; border-color: #0A4A3D;
            }
            QPushButton#sendButton { min-width: 150px; min-height: 44px; font-size: 14px; }
            QPushButton#secondaryButton {
                background: #E8F3EE; color: #0D5C4B; border: 1px solid #C9E2D8;
            }
            QPushButton#secondaryButton:hover { background: #DCEDE6; }
            QPushButton#ghostButton, QPushButton#textButton {
                background: transparent; color: #0D5C4B; border: 1px solid #C8D4CF;
            }
            QPushButton#ghostButton:hover, QPushButton#textButton:hover { background: #E8F3EE; }
            QPushButton:disabled {
                background: #D8DDD9; color: #8D9691; border-color: #D8DDD9;
            }
            QLineEdit {
                min-height: 36px; padding: 0 10px; background: #FBFAF6;
                border: 1px solid #D3D7D4; border-radius: 9px; color: #17201C;
                font-family: Consolas, "SFMono-Regular", monospace;
            }
            QLineEdit:focus { border: 1px solid #0D5C4B; background: #FFFFFF; }
            QComboBox#languageSelect {
                min-height: 38px; padding: 0 12px; background: #FBFAF6;
                border: 1px solid #D3D7D4; border-radius: 9px; color: #17201C;
                font-size: 12px;
            }
            QComboBox#languageSelect:hover { border-color: #0D5C4B; }
            QComboBox#addressBox {
                min-height: 36px; padding: 0 8px; background: #FBFAF6;
                border: 1px solid #D3D7D4; border-radius: 9px; color: #17201C;
            }
            QComboBox#addressBox:focus, QComboBox#addressBox:hover { border-color: #0D5C4B; }
            QFrame#storagePanel { background: #F2F7F4; border-radius: 11px; }
            QFrame#installPanel {
                background: #EDF4F0; border: 1px solid #C9DDD4; border-radius: 14px;
            }
            QLabel#storageTitle { color: #17201C; font-size: 12px; font-weight: 700; }
            QProgressBar#storageBar {
                min-height: 9px; max-height: 9px; border: none;
                background: #D9E7E1; border-radius: 4px;
            }
            QProgressBar#storageBar::chunk { background: #0D5C4B; border-radius: 4px; }
            QTreeWidget#fileList {
                background: #FBFAF6; border: 1px solid #E0E2DD; border-radius: 10px;
                outline: none; padding: 4px;
            }
            QTreeWidget#fileList::item { min-height: 30px; border-bottom: 1px solid #ECEDE9; }
            QTreeWidget#fileList::item:selected { background: #DCEDE6; color: #17201C; }
            QHeaderView::section {
                background: #F2F1EC; color: #64716B; border: none;
                border-bottom: 1px solid #DDDCD4; padding: 7px 8px;
                font-size: 11px; font-weight: 650;
            }
            QLabel#operationStatus { color: #3C4943; font-size: 12px; font-weight: 600; }
            QProgressBar {
                max-height: 8px; border: none; background: #E8DDC8; border-radius: 4px;
            }
            QProgressBar::chunk { background: #D18427; border-radius: 4px; }
            QScrollArea { border: none; background: #F6F4ED; }
            QScrollBar:vertical { width: 11px; background: #F6F4ED; }
            QScrollBar::handle:vertical {
                background: #C8CEC9; border-radius: 5px; min-height: 32px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            """
        )

    def change_language(self, index: int) -> None:
        selected = self.language_select.itemData(index)
        self.language = set_language(str(selected or "en"))
        self.settings.language = self.language
        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        direction = (
            Qt.LayoutDirection.RightToLeft
            if current_language() == "ar"
            else Qt.LayoutDirection.LeftToRight
        )
        application = QApplication.instance()
        if application:
            application.setLayoutDirection(direction)
        self.setWindowTitle(f"{APP_NAME} | {ORGANIZATION}")
        for widget, key, values in self.localized_widgets:
            widget.setText(tr(key, **values))
            widget.updateGeometry()
        self.language_select.setToolTip(tr("language_tooltip"))
        self.language_select.setAccessibleName(tr("language_tooltip"))
        self.manual_ip.setToolTip(tr("address_history"))
        if self.manual_ip.lineEdit():
            self.manual_ip.lineEdit().setPlaceholderText(tr("address_placeholder"))
        self.no_password_checkbox.setToolTip(tr("no_password_tooltip"))
        self.file_list.setHeaderLabels([tr("col_book"), tr("col_format"), tr("col_size")])
        self.history_list.setHeaderLabels(
            [tr("history_time"), tr("history_books"), tr("history_size"), tr("history_kindle")]
        )
        self.destination.setText(tr("destination", path=REMOTE_BOOK_DIRECTORY))
        self.footer_text.setText(tr("footer", version=APP_VERSION))
        self.refresh_file_state()
        self.refresh_transfer_history()
        self.show_storage(self.current_storage, last_known=not bool(self.discovered_ip))
        self.content.layout().invalidate()
        self.content.updateGeometry()

    def remember_no_password(self, checked: bool) -> None:
        self.settings.no_password = checked

    def refresh_address_history(self) -> None:
        current = self.manual_ip.currentText().strip()
        self.manual_ip.clear()
        self.manual_ip.addItems(self.settings.recent_addresses)
        self.manual_ip.setEditText(current or self.settings.last_ip)

    def show_storage(self, storage: object, last_known: bool = False) -> None:
        if not isinstance(storage, dict):
            storage = {}
        try:
            total = int(storage.get("total", 0))
            used = int(storage.get("used", 0))
            free = int(storage.get("free", 0))
        except (TypeError, ValueError):
            total = used = free = 0
        if total <= 0:
            self.storage_bar.setValue(0)
            key = "storage_unavailable" if self.discovered_ip else "storage_waiting"
            self.set_localized_text(self.storage_detail, key)
            return
        percent = max(0, min(100, round(used * 100 / total)))
        self.storage_bar.setValue(percent)
        key = "storage_last_summary" if last_known else "storage_summary"
        self.set_localized_text(
            self.storage_detail,
            key,
            used=human_size(used),
            total=human_size(total),
            free=human_size(free),
            percent=percent,
        )

    def update_storage_from_path(self, root: Path) -> None:
        try:
            usage = shutil.disk_usage(root)
        except OSError:
            return
        self.current_storage = {
            "total": usage.total,
            "used": usage.used,
            "free": usage.free,
        }
        self.settings.last_storage = self.current_storage
        self.show_storage(self.current_storage)

    def refresh_transfer_history(self) -> None:
        self.history_list.clear()
        records = self.settings.transfer_history
        for record in records:
            count = int(record.get("count", 0) or 0)
            byte_count = int(record.get("bytes", 0) or 0)
            item = QTreeWidgetItem(
                [
                    str(record.get("time", "")),
                    str(count),
                    human_size(byte_count),
                    str(record.get("ip", "")),
                ]
            )
            files = record.get("files", [])
            if isinstance(files, list):
                item.setToolTip(0, "\n".join(str(name) for name in files))
            self.history_list.addTopLevelItem(item)
        self.history_empty.setVisible(not records)
        self.history_list.setVisible(bool(records))

    def clear_transfer_history(self) -> None:
        self.settings.clear_transfer_history()
        self.refresh_transfer_history()

    def automatic_windows_install(self) -> None:
        if platform.system() != "Windows" or not getattr(sys, "frozen", False):
            return
        try:
            _, shortcut = install_windows_app()
            self.settings.installed_version = APP_VERSION
            if not self.settings.taskbar_pin_attempted:
                pin_windows_taskbar(shortcut)
                self.settings.taskbar_pin_attempted = True
        except (OSError, RuntimeError, subprocess.SubprocessError):
            return

    def install_to_start(self) -> None:
        try:
            install_windows_app()
            self.settings.installed_version = APP_VERSION
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            QMessageBox.warning(self, APP_NAME, tr("install_failed", error=error))
            return
        QMessageBox.information(self, APP_NAME, tr("start_installed"))

    def install_to_taskbar(self) -> None:
        try:
            _, shortcut = install_windows_app()
            self.settings.installed_version = APP_VERSION
            pinned = pin_windows_taskbar(shortcut)
            self.settings.taskbar_pin_attempted = True
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            QMessageBox.warning(self, APP_NAME, tr("install_failed", error=error))
            return
        QMessageBox.information(
            self,
            APP_NAME,
            tr("taskbar_installed") if pinned else tr("taskbar_manual"),
        )

    def animate_in(self) -> None:
        effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b"opacity", self)
        animation.setDuration(420)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.finished.connect(lambda: self.setGraphicsEffect(None))
        self.entrance_animation = animation
        animation.start()

    def set_busy(self, busy: bool, message: str = "") -> None:
        self.find_button.setEnabled(not busy)
        self.usb_button.setEnabled(not busy)
        self.no_password_checkbox.setEnabled(not busy)
        self.firewall_button.setEnabled(not busy)
        self.language_select.setEnabled(not busy)
        self.send_button.setEnabled(
            not busy and bool(self.discovered_ip) and bool(self.selected_files)
        )
        self.manual_ip.setEnabled(not busy)
        self.cancel_button.setVisible(busy)
        if busy:
            self.progress.setRange(0, 0)
            self.progress.show()
        else:
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
            self.progress.hide()
        if message:
            self.operation_status.setText(message)

    def automatic_usb_pairing(self) -> None:
        try:
            mounted = install_public_key_on_usb(self.key_store)
        except Exception as error:
            self.set_localized_text(self.primary_status, "usb_attention", error=error)
            return
        if mounted:
            roots = ", ".join(str(root) for root in mounted)
            self.update_storage_from_path(mounted[0])
            self.set_localized_text(self.primary_status, "usb_ready")
            self.set_localized_text(self.device_detail, "paired_auto", roots=roots)
            self.set_localized_text(self.operation_status, "usb_complete_eject")
        elif self.settings.last_ip:
            self.set_localized_text(
                self.primary_status, "ready_previous", address=self.settings.last_ip
            )
        else:
            self.set_localized_text(self.primary_status, "first_use_usb")

    def pair_over_usb(self) -> None:
        try:
            mounted = install_public_key_on_usb(self.key_store)
        except Exception as error:
            QMessageBox.critical(self, tr("usb_pair_failed"), str(error))
            return
        if not mounted:
            QMessageBox.information(
                self,
                tr("connect_usb_title"),
                tr("usb_not_found"),
            )
            return
        roots = ", ".join(str(root) for root in mounted)
        self.update_storage_from_path(mounted[0])
        self.set_localized_text(self.primary_status, "paired_status")
        self.set_localized_text(self.device_detail, "key_installed", roots=roots)
        self.set_localized_text(self.operation_status, "usb_complete")
        QMessageBox.information(
            self,
            tr("kindle_paired"),
            tr("pairing_complete"),
        )

    def firewall_help(self) -> None:
        port = SSH_PORT
        supplied = self.manual_ip.currentText().strip()
        if supplied:
            try:
                port = parse_endpoint(supplied).port
            except ValueError as error:
                QMessageBox.information(self, APP_NAME, str(error))
                return
        answer = QMessageBox.question(
            self,
            tr("firewall_dialog_title"),
            tr("firewall_dialog", port=port),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if request_windows_firewall_rule(port):
            self.set_localized_text(self.operation_status, "firewall_requested", port=port)
        else:
            QMessageBox.warning(self, APP_NAME, tr("firewall_failed"))

    def start_discovery(self) -> None:
        if self.active_worker:
            return
        preferred = self.manual_ip.currentText().strip() or self.settings.last_ip
        worker = DiscoveryWorker(
            self.key_store,
            preferred,
            self.no_password_checkbox.isChecked(),
        )
        worker.signals.status.connect(self.show_worker_status)
        worker.signals.result.connect(self.discovery_succeeded)
        worker.signals.error.connect(self.operation_failed)
        worker.signals.finished.connect(self.worker_finished)
        self.active_worker = worker
        self.discovered_ip = ""
        self.set_busy(True, tr("looking"))
        self.set_localized_text(self.primary_status, "searching")
        self.thread_pool.start(worker)

    def discovery_succeeded(self, result: object) -> None:
        if not isinstance(result, dict):
            return
        ip = str(result.get("ip", ""))
        if not ip:
            return
        self.discovered_ip = ip
        self.manual_ip.setEditText(ip)
        self.settings.last_ip = ip
        self.settings.remember_address(ip)
        self.refresh_address_history()
        storage = result.get("storage", {})
        if isinstance(storage, dict) and storage:
            self.current_storage = storage
            self.settings.last_storage = storage
        else:
            self.current_storage = {}
        self.show_storage(self.current_storage)
        auth = str(result.get("auth", "key"))
        self.set_localized_text(self.primary_status, "connected", address=ip)
        if auth == "bootstrapped":
            self.set_localized_text(self.device_detail, "bootstrap_success")
            self.no_password_checkbox.setChecked(False)
        else:
            self.set_localized_text(self.device_detail, "key_verified")
        self.set_localized_text(self.operation_status, "kindle_found")

    def choose_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            tr("choose_dialog"),
            self.settings.last_directory or str(Path.home()),
            tr("book_filter"),
        )
        if paths:
            self.settings.last_directory = str(Path(paths[0]).parent)
        self.add_files([Path(path) for path in paths])

    def add_files(self, paths: Iterable[Path]) -> None:
        for path in paths:
            try:
                resolved = path.expanduser().resolve()
            except OSError:
                continue
            if not resolved.is_file():
                continue
            key = str(resolved)
            if key in self.selected_files:
                continue
            self.selected_files[key] = resolved
            item = QTreeWidgetItem(
                [
                    resolved.name,
                    resolved.suffix.lstrip(".").upper() or "FILE",
                    human_size(resolved.stat().st_size),
                ]
            )
            item.setToolTip(0, str(resolved))
            item.setData(0, Qt.ItemDataRole.UserRole, key)
            self.file_list.addTopLevelItem(item)
        self.refresh_file_state()

    def remove_selected(self) -> None:
        for item in self.file_list.selectedItems():
            key = item.data(0, Qt.ItemDataRole.UserRole)
            self.selected_files.pop(key, None)
            self.file_list.takeTopLevelItem(self.file_list.indexOfTopLevelItem(item))
        self.refresh_file_state()

    def refresh_file_state(self) -> None:
        count = len(self.selected_files)
        total = sum(
            path.stat().st_size
            for path in self.selected_files.values()
            if path.exists()
        )
        self.set_localized_text(
            self.book_count, "book_count", count=count, size=human_size(total)
        )
        self.file_list.setVisible(count > 0)
        self.drop_area.setVisible(count == 0)
        self.send_button.setEnabled(
            bool(self.discovered_ip) and count > 0 and self.active_worker is None
        )

    def start_transfer(self) -> None:
        if self.active_worker or not self.discovered_ip or not self.selected_files:
            return
        worker = TransferWorker(
            self.discovered_ip,
            list(self.selected_files.values()),
            self.key_store,
        )
        worker.signals.status.connect(self.show_worker_status)
        worker.signals.progress.connect(self.transfer_progress)
        worker.signals.result.connect(self.transfer_succeeded)
        worker.signals.error.connect(self.operation_failed)
        worker.signals.finished.connect(self.worker_finished)
        self.active_worker = worker
        self.set_busy(True, tr("connecting", address=self.discovered_ip))
        self.thread_pool.start(worker)

    def show_worker_status(self, message: str) -> None:
        self.operation_status.setText(message)

    def transfer_progress(self, percent: int, message: str) -> None:
        self.progress.setRange(0, 100)
        self.progress.setValue(percent)
        self.progress.show()
        self.operation_status.setText(message)

    def transfer_succeeded(self, result: object) -> None:
        if not isinstance(result, dict):
            return
        count = int(result.get("count", 0))
        byte_count = int(result.get("bytes", 0))
        self.set_localized_text(self.primary_status, "transfer_complete", count=count)
        self.set_localized_text(
            self.operation_status, "sent_size", size=human_size(byte_count)
        )
        self.settings.add_transfer(
            {
                "time": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M"),
                "count": count,
                "bytes": byte_count,
                "ip": self.discovered_ip,
                "files": [path.name for path in self.selected_files.values()],
            }
        )
        self.refresh_transfer_history()
        QMessageBox.information(
            self,
            tr("books_sent"),
            tr("books_sent_message", count=count),
        )

    def operation_failed(self, message: str) -> None:
        self.set_localized_text(self.primary_status, "action_needed")
        self.operation_status.setText(message)
        QMessageBox.warning(self, APP_NAME, message)

    def worker_finished(self) -> None:
        self.active_worker = None
        self.set_busy(False)
        self.refresh_file_state()

    def cancel_operation(self) -> None:
        if self.active_worker:
            self.active_worker.cancel()
        self.set_localized_text(self.operation_status, "cancelling")

    def resizeEvent(self, event) -> None:
        available_width = max(320, event.size().width() - 64)
        content_width = min(1400, available_width)
        self.content.setFixedWidth(content_width)
        header_compact = content_width < 900
        hero_compact = content_width < 980
        device_compact = content_width < 1160
        options_compact = content_width < 900
        files_compact = content_width < 820
        install_compact = content_width < 1080
        action_compact = content_width < 760
        footer_compact = content_width < 840
        ultra_narrow = content_width < 560
        header_actions_compact = content_width < 720
        horizontal = QBoxLayout.Direction.LeftToRight
        vertical = QBoxLayout.Direction.TopToBottom
        self.header_layout.setDirection(vertical if header_compact else horizontal)
        self.header_actions.setDirection(vertical if header_actions_compact else horizontal)
        self.hero_layout.setDirection(vertical if hero_compact else horizontal)
        self.steps_panel.setMinimumWidth(0 if hero_compact else 360)
        self.device_top_layout.setDirection(vertical if device_compact else horizontal)
        self.connection_options_layout.setDirection(vertical if options_compact else horizontal)
        self.file_actions_layout.setDirection(vertical if files_compact else horizontal)
        self.footer_layout.setDirection(vertical if footer_compact else horizontal)
        self.install_layout.setDirection(vertical if install_compact else horizontal)
        self.action_layout.setDirection(vertical if action_compact else horizontal)
        self.storage_top_layout.setDirection(vertical if ultra_narrow else horizontal)
        self.books_header_layout.setDirection(vertical if ultra_narrow else horizontal)
        self.history_header_layout.setDirection(vertical if ultra_narrow else horizontal)
        self.manual_ip.setMaximumWidth(16777215 if device_compact else 360)
        self.language_select.setMaximumWidth(16777215 if header_actions_compact else 280)
        self.books_button.setMaximumWidth(16777215 if header_actions_compact else 280)
        self.website_button.setMaximumWidth(16777215 if header_actions_compact else 280)
        super().resizeEvent(event)

    def closeEvent(self, event) -> None:
        if self.active_worker:
            self.active_worker.cancel()
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(ORGANIZATION)
    app.setWindowIcon(make_app_icon())
    app.setStyle("Fusion")
    font = QFont()
    if platform.system() == "Windows":
        font.setFamilies(["Segoe UI", "Arial"])
    elif platform.system() == "Darwin":
        font.setFamilies(["Avenir Next", "Helvetica Neue"])
    else:
        font.setFamilies(["Ubuntu", "Noto Sans", "DejaVu Sans"])
    font.setPointSizeF(10.0)
    app.setFont(font)
    window = MainWindow()
    window.showMaximized()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
