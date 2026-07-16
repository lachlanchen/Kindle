from __future__ import annotations

import concurrent.futures
import ctypes
import ipaddress
import json
import os
import platform
import posixpath
import shlex
import socket
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urlsplit

import paramiko
import psutil
from scp import SCPClient
from PySide6.QtCore import (
    QEasingCurve,
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
    QCheckBox,
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
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


APP_NAME = "Kindle Book Sender"
APP_VERSION = "1.1.0"
ORGANIZATION = "AgInTi Flow"
WEBSITE = "https://lachlanchen.github.io/Kindle/"
SSH_PORT = 2222
REMOTE_BOOK_DIRECTORY = "/mnt/us/documents/Books"
KEY_COMMENT = "AgInTi-Kindle-Book-Sender"

BOOK_FILTER = (
    "KOReader books (*.pdf *.epub *.mobi *.azw *.azw3 *.djvu *.cbz *.cbr "
    "*.cbt *.docx *.rtf *.txt *.html *.htm *.fb2 *.xps *.md);;"
    "PDF books (*.pdf);;EPUB books (*.epub);;All files (*)"
)


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

    paper_x = int(size * 0.27)
    paper_y = int(size * 0.20)
    paper_w = int(size * 0.46)
    paper_h = int(size * 0.60)
    painter.setBrush(QColor("#FBFAF6"))
    painter.drawRoundedRect(paper_x, paper_y, paper_w, paper_h, 7, 7)

    painter.setPen(QPen(QColor("#0D5C4B"), max(3, size // 28)))
    for offset in (0.34, 0.44, 0.54):
        y = int(size * offset)
        painter.drawLine(int(size * 0.36), y, int(size * 0.64), y)

    painter.setPen(QPen(QColor("#D78A2A"), max(5, size // 20)))
    painter.drawLine(int(size * 0.40), int(size * 0.69), int(size * 0.60), int(size * 0.69))
    painter.drawLine(int(size * 0.55), int(size * 0.64), int(size * 0.60), int(size * 0.69))
    painter.drawLine(int(size * 0.55), int(size * 0.74), int(size * 0.60), int(size * 0.69))
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


class KeyStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.private_key_path = root / "kindle_sender_rsa"
        self.public_key_path = root / "kindle_sender_rsa.pub"

    def ensure(self) -> paramiko.RSAKey:
        self.root.mkdir(parents=True, exist_ok=True)
        if self.private_key_path.exists():
            return paramiko.RSAKey.from_private_key_file(str(self.private_key_path))

        key = paramiko.RSAKey.generate(bits=3072)
        key.write_private_key_file(str(self.private_key_path))
        try:
            self.private_key_path.chmod(0o600)
        except OSError:
            pass
        self.public_key_path.write_text(
            f"{key.get_name()} {key.get_base64()} {KEY_COMMENT}\n",
            encoding="ascii",
        )
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
        lines = {line.strip() for line in existing.splitlines() if line.strip()}
        if public_line not in lines:
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


def install_public_key_over_ssh(endpoint: Endpoint, key_store: KeyStore) -> None:
    client: paramiko.SSHClient | None = None
    try:
        client = connect_ssh_without_password(endpoint, timeout=6)
        if not verify_koreader_client(client):
            raise RuntimeError(f"{endpoint.display} accepts SSH but is not a KOReader Kindle.")
        public_line = shlex.quote(key_store.public_key_line)
        ssh_directory = shlex.quote("/mnt/us/koreader/settings/SSH")
        authorized_keys = shlex.quote("/mnt/us/koreader/settings/SSH/authorized_keys")
        command = (
            f"mkdir -p {ssh_directory} && touch {authorized_keys} && "
            f"(grep -F -x -q {public_line} {authorized_keys} 2>/dev/null || "
            f"printf '%s\\n' {public_line} >> {authorized_keys})"
        )
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
        "SSH is reachable, but this computer's key is not authorized. "
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
                    raise RuntimeError(f"The supplied Kindle address is invalid: {error}") from error
                self.signals.status.emit(f"Testing the supplied address {preferred_endpoint.display} first...")
                try:
                    auth = authenticate_koreader(
                        preferred_endpoint,
                        self.key_store,
                        self.allow_no_password,
                    )
                    self.signals.result.emit(
                        {"ip": preferred_endpoint.display, "auth": auth, "supplied": True}
                    )
                    return
                except Exception as error:
                    preferred_error = str(error)

            networks = private_local_networks()
            if not networks:
                raise RuntimeError(
                    "No private Wi-Fi or Ethernet network was found on this computer."
                )

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

            self.signals.status.emit(
                f"Searching {len(networks)} active private network(s) for KOReader SSH..."
            )
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
                self.signals.status.emit(f"Checking a possible Kindle at {endpoint.display}...")
                try:
                    auth = authenticate_koreader(
                        endpoint,
                        self.key_store,
                        self.allow_no_password,
                    )
                    self.signals.result.emit(
                        {"ip": endpoint.display, "auth": auth, "supplied": False}
                    )
                    return
                except Exception as error:
                    authentication_errors.append(f"{endpoint.display}: {error}")

            details: list[str] = []
            if preferred_endpoint:
                details.append(
                    f"The supplied address {preferred_endpoint.display} was tested first: {preferred_error}"
                )
            if open_hosts:
                details.append(
                    f"Found {len(open_hosts)} SSH endpoint(s) locally, but none verified as this KOReader Kindle."
                )
            else:
                details.append(
                    "No local device answered on TCP 2222. Confirm KOReader SSH is started and the Wi-Fi does not isolate clients."
                )
            if authentication_errors:
                details.append(authentication_errors[0])
            if not self.allow_no_password:
                details.append(
                    "For a new computer, stop KOReader SSH, enable 'Login without password (DANGEROUS)', start SSH, check the app's no-password option, and connect again."
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
            f"Sending {filename} - {human_size(current_sent)} of {human_size(current_size)}",
        )

    def run(self) -> None:
        client: paramiko.SSHClient | None = None
        try:
            valid_files = [path for path in self.files if path.is_file()]
            if not valid_files:
                raise RuntimeError("No readable book files were selected.")

            total_size = sum(path.stat().st_size for path in valid_files)
            key = self.key_store.load()
            self.signals.status.emit(f"Connecting securely to {self.ip}...")
            client = connect_ssh(self.endpoint, key, timeout=6)

            command = f"mkdir -p {shlex.quote(REMOTE_BOOK_DIRECTORY)}"
            _, stdout, stderr = client.exec_command(command, timeout=8)
            if stdout.channel.recv_exit_status() != 0:
                detail = stderr.read().decode("utf-8", errors="replace").strip()
                raise RuntimeError(detail or "Could not create the Books folder.")

            completed = 0
            try:
                sftp = client.open_sftp()
            except Exception:
                sftp = None

            if sftp is not None:
                try:
                    for path in valid_files:
                        if self.cancelled.is_set():
                            raise RuntimeError("Transfer cancelled.")
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
                    raise RuntimeError("The Kindle connection closed unexpectedly.")
                with SCPClient(transport, socket_timeout=30) as scp_client:
                    for path in valid_files:
                        if self.cancelled.is_set():
                            raise RuntimeError("Transfer cancelled.")
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

            self.signals.progress.emit(100, f"Sent {len(valid_files)} book(s).")
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
        title = QLabel("Drop books here")
        title.setObjectName("dropTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        subtitle = QLabel("or click to choose PDF, EPUB, MOBI and other KOReader files")
        subtitle.setObjectName("muted")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)

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
        self.key_store = KeyStore(self.data_root / "keys")
        self.key_store.ensure()
        self.thread_pool = QThreadPool.globalInstance()
        self.active_worker: DiscoveryWorker | TransferWorker | None = None
        self.discovered_ip = ""
        self.selected_files: dict[str, Path] = {}

        self.setWindowTitle(f"{APP_NAME} | {ORGANIZATION}")
        self.setWindowIcon(make_app_icon())
        self.resize(1120, 820)
        self.setMinimumSize(840, 680)
        self.build_ui()
        self.apply_style()
        QTimer.singleShot(350, self.automatic_usb_pairing)
        QTimer.singleShot(80, self.animate_in)

    def build_ui(self) -> None:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.setCentralWidget(scroll)
        canvas = QWidget()
        canvas.setObjectName("canvas")
        scroll.setWidget(canvas)
        outer = QVBoxLayout(canvas)
        outer.setContentsMargins(28, 20, 28, 28)
        outer.setSpacing(18)

        content = QWidget()
        content.setMaximumWidth(1080)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(18)
        outer.addWidget(content, 0, Qt.AlignmentFlag.AlignHCenter)

        header = QFrame()
        header.setObjectName("header")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 2, 0, 4)
        mark = QLabel("K")
        mark.setObjectName("mark")
        mark.setFixedSize(42, 42)
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(mark)
        brand_box = QVBoxLayout()
        brand_box.setSpacing(0)
        brand = QLabel(APP_NAME)
        brand.setObjectName("brand")
        brand_box.addWidget(brand)
        byline = QLabel("by AgInTi Flow · LazyingArt LLC")
        byline.setObjectName("muted")
        brand_box.addWidget(byline)
        header_layout.addLayout(brand_box)
        header_layout.addStretch(1)
        website_button = QPushButton("Guide & downloads")
        website_button.setObjectName("ghostButton")
        website_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(WEBSITE)))
        header_layout.addWidget(website_button)
        content_layout.addWidget(header)

        hero = QFrame()
        hero.setObjectName("hero")
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(30, 28, 30, 28)
        hero_layout.setSpacing(34)
        hero_copy = QVBoxLayout()
        hero_copy.setSpacing(9)
        eyebrow = QLabel("BOOKS, NOT SETUP")
        eyebrow.setObjectName("eyebrow")
        hero_copy.addWidget(eyebrow)
        headline = QLabel("Send a book in under a minute.")
        headline.setWordWrap(True)
        headline.setObjectName("headline")
        hero_copy.addWidget(headline)
        description = QLabel(
            "No terminal commands. Pair over Wi-Fi with KOReader's no-password option, "
            "or use USB when Kindle storage is available."
        )
        description.setWordWrap(True)
        description.setObjectName("heroDescription")
        hero_copy.addWidget(description)
        self.primary_status = QLabel("Preparing your private Kindle key...")
        self.primary_status.setObjectName("statusPill")
        self.primary_status.setWordWrap(True)
        hero_copy.addWidget(self.primary_status, 0, Qt.AlignmentFlag.AlignLeft)
        hero_layout.addLayout(hero_copy, 3)

        steps = QFrame()
        steps.setObjectName("steps")
        steps_layout = QVBoxLayout(steps)
        steps_layout.setContentsMargins(20, 18, 20, 18)
        steps_layout.setSpacing(10)
        steps_title = QLabel("On your Kindle")
        steps_title.setObjectName("cardTitle")
        steps_layout.addWidget(steps_title)
        for number, text in (
            ("1", "Use the same or another routed local network"),
            ("2", "Open KOReader"),
            ("3", "First use: allow no password, then start SSH"),
        ):
            row = QHBoxLayout()
            badge = QLabel(number)
            badge.setObjectName("stepBadge")
            badge.setFixedSize(26, 26)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            row.addWidget(badge)
            label = QLabel(text)
            label.setWordWrap(True)
            label.setObjectName("stepText")
            row.addWidget(label, 1)
            steps_layout.addLayout(row)
        hero_layout.addWidget(steps, 2)
        content_layout.addWidget(hero)

        device_card = QFrame()
        device_card.setObjectName("card")
        device_layout = QVBoxLayout(device_card)
        device_layout.setContentsMargins(22, 18, 22, 18)
        device_layout.setSpacing(15)
        device_top = QHBoxLayout()
        device_info = QVBoxLayout()
        device_info.setSpacing(2)
        heading = QLabel("Your Kindle")
        heading.setObjectName("cardTitle")
        device_info.addWidget(heading)
        self.device_detail = QLabel(
            "Enter any reachable Kindle address, or leave it blank to scan every active private interface."
        )
        self.device_detail.setObjectName("muted")
        self.device_detail.setWordWrap(True)
        device_info.addWidget(self.device_detail)
        device_top.addLayout(device_info, 1)
        self.manual_ip = QLineEdit()
        self.manual_ip.setPlaceholderText("IP, hostname, host:port, or [IPv6]:port")
        self.manual_ip.setText(self.settings.last_ip)
        self.manual_ip.setMaximumWidth(270)
        self.manual_ip.setClearButtonEnabled(True)
        device_top.addWidget(self.manual_ip)
        self.usb_button = QPushButton("Pair over USB")
        self.usb_button.setObjectName("secondaryButton")
        self.usb_button.clicked.connect(self.pair_over_usb)
        device_top.addWidget(self.usb_button)
        self.find_button = QPushButton("Connect / find Kindle")
        self.find_button.setObjectName("primaryButton")
        self.find_button.clicked.connect(self.start_discovery)
        device_top.addWidget(self.find_button)
        device_layout.addLayout(device_top)

        connection_options = QHBoxLayout()
        self.no_password_checkbox = QCheckBox(
            "First connection: KOReader allows login without password"
        )
        self.no_password_checkbox.setToolTip(
            "The app will use no-password access once, install this computer's public key, and verify key login. It will not disable the Kindle setting."
        )
        connection_options.addWidget(self.no_password_checkbox)
        connection_options.addStretch(1)
        self.firewall_button = QPushButton("Windows firewall help")
        self.firewall_button.setObjectName("textButton")
        self.firewall_button.setVisible(platform.system() == "Windows")
        self.firewall_button.clicked.connect(self.firewall_help)
        connection_options.addWidget(self.firewall_button)
        device_layout.addLayout(connection_options)
        content_layout.addWidget(device_card)

        books_card = QFrame()
        books_card.setObjectName("card")
        books_layout = QVBoxLayout(books_card)
        books_layout.setContentsMargins(22, 20, 22, 20)
        books_layout.setSpacing(13)
        books_header = QHBoxLayout()
        title = QLabel("Books to send")
        title.setObjectName("cardTitle")
        books_header.addWidget(title)
        books_header.addStretch(1)
        self.book_count = QLabel("0 books")
        self.book_count.setObjectName("countPill")
        books_header.addWidget(self.book_count)
        books_layout.addLayout(books_header)
        self.drop_area = DropArea()
        self.drop_area.clicked.connect(self.choose_files)
        self.drop_area.files_dropped.connect(self.add_files)
        books_layout.addWidget(self.drop_area)

        self.file_list = QTreeWidget()
        self.file_list.setObjectName("fileList")
        self.file_list.setColumnCount(3)
        self.file_list.setHeaderLabels(["Book", "Format", "Size"])
        self.file_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.file_list.setRootIsDecorated(False)
        self.file_list.setMinimumHeight(125)
        self.file_list.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.file_list.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.file_list.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.file_list.hide()
        books_layout.addWidget(self.file_list)

        file_actions = QHBoxLayout()
        choose_button = QPushButton("Choose books")
        choose_button.setObjectName("secondaryButton")
        choose_button.clicked.connect(self.choose_files)
        file_actions.addWidget(choose_button)
        remove_button = QPushButton("Remove selected")
        remove_button.setObjectName("textButton")
        remove_button.clicked.connect(self.remove_selected)
        file_actions.addWidget(remove_button)
        file_actions.addStretch(1)
        destination = QLabel(f"Destination: {REMOTE_BOOK_DIRECTORY}")
        destination.setObjectName("monoMuted")
        file_actions.addWidget(destination)
        books_layout.addLayout(file_actions)
        content_layout.addWidget(books_card)

        action_card = QFrame()
        action_card.setObjectName("actionCard")
        action_layout = QHBoxLayout(action_card)
        action_layout.setContentsMargins(22, 17, 22, 17)
        action_layout.setSpacing(16)
        status_box = QVBoxLayout()
        status_box.setSpacing(4)
        self.operation_status = QLabel("Ready for pairing and discovery.")
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
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setObjectName("textButton")
        self.cancel_button.clicked.connect(self.cancel_operation)
        self.cancel_button.hide()
        action_layout.addWidget(self.cancel_button)
        self.send_button = QPushButton("Send books")
        self.send_button.setObjectName("sendButton")
        self.send_button.setEnabled(False)
        self.send_button.clicked.connect(self.start_transfer)
        action_layout.addWidget(self.send_button)
        content_layout.addWidget(action_card)

        footer = QHBoxLayout()
        footer_text = QLabel(
            f"Version {APP_VERSION}  ·  Private key stays on this computer  ·  Stop KOReader SSH when finished"
        )
        footer_text.setObjectName("footer")
        footer.addWidget(footer_text)
        footer.addStretch(1)
        links = QLabel(
            '<a href="https://flow.lazying.art">flow.lazying.art</a> &nbsp;·&nbsp; '
            '<a href="https://lazying.art">lazying.art</a>'
        )
        links.setObjectName("footerLinks")
        links.setOpenExternalLinks(True)
        footer.addWidget(links)
        content_layout.addLayout(footer)

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
            self.primary_status.setText(f"USB pairing needs attention: {error}")
            return
        if mounted:
            roots = ", ".join(str(root) for root in mounted)
            self.primary_status.setText(
                "USB pairing is ready. Safely eject, open KOReader, and start its SSH server."
            )
            self.device_detail.setText(
                f"Paired automatically on {roots}. The private key stays on this computer."
            )
            self.operation_status.setText("USB pairing complete. Safely eject before using Wi-Fi.")
        elif self.settings.last_ip:
            self.primary_status.setText(
                f"Ready to look for the previously used Kindle at {self.settings.last_ip}."
            )
        else:
            self.primary_status.setText(
                "First use: connect the Kindle by USB once for automatic pairing."
            )

    def pair_over_usb(self) -> None:
        try:
            mounted = install_public_key_on_usb(self.key_store)
        except Exception as error:
            QMessageBox.critical(self, "USB pairing failed", str(error))
            return
        if not mounted:
            QMessageBox.information(
                self,
                "Connect the Kindle by USB",
                "No mounted KOReader Kindle storage was found.\n\n"
                "If KOReader is open, exit KOReader first. Then connect a USB data cable, "
                "wait for the Kindle drive to appear, and click Pair over USB again.\n\n"
                "To keep KOReader open, use Wi-Fi pairing with the no-password checkbox instead.",
            )
            return
        roots = ", ".join(str(root) for root in mounted)
        self.primary_status.setText(
            "Paired. Safely eject, open KOReader, and start Tools → SSH server."
        )
        self.device_detail.setText(f"Public key installed on {roots}. No password is needed.")
        self.operation_status.setText("USB pairing complete.")
        QMessageBox.information(
            self,
            "Kindle paired",
            "Pairing is complete.\n\nSafely eject and unplug the Kindle, connect it "
            "to the same Wi-Fi, open KOReader, and start Tools > SSH server.",
        )

    def firewall_help(self) -> None:
        port = SSH_PORT
        supplied = self.manual_ip.text().strip()
        if supplied:
            try:
                port = parse_endpoint(supplied).port
            except ValueError as error:
                QMessageBox.information(self, APP_NAME, str(error))
                return
        answer = QMessageBox.question(
            self,
            "Windows firewall help",
            f"Kindle Book Sender is an outbound SSH client. Windows normally permits this without a rule.\n\n"
            f"Create an explicit outbound allow rule for TCP port {port}? Windows will show a UAC administrator prompt.\n\n"
            "This cannot fix guest-Wi-Fi/client isolation, a wrong address, VPN routing, or a stopped Kindle SSH server.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if request_windows_firewall_rule(port):
            self.operation_status.setText(
                f"Windows requested an outbound TCP {port} firewall rule. Approve the UAC prompt, then connect again."
            )
        else:
            QMessageBox.warning(self, APP_NAME, "Windows could not start the elevated firewall helper.")

    def start_discovery(self) -> None:
        if self.active_worker:
            return
        preferred = self.manual_ip.text().strip() or self.settings.last_ip
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
        self.set_busy(True, "Looking for your Kindle on the local network...")
        self.primary_status.setText("Searching for KOReader SSH on the same Wi-Fi...")
        self.thread_pool.start(worker)

    def discovery_succeeded(self, result: object) -> None:
        if not isinstance(result, dict):
            return
        ip = str(result.get("ip", ""))
        if not ip:
            return
        self.discovered_ip = ip
        self.manual_ip.setText(ip)
        self.settings.last_ip = ip
        auth = str(result.get("auth", "key"))
        self.primary_status.setText(f"Kindle connected - {ip}")
        if auth == "bootstrapped":
            self.device_detail.setText(
                "Passwordless bootstrap succeeded. This computer's public key was installed and key login was verified."
            )
            self.no_password_checkbox.setChecked(False)
        else:
            self.device_detail.setText(
                "Verified with this computer's private pairing key and the KOReader installation."
            )
        self.operation_status.setText("Kindle found. Add books, then click Send books.")

    def choose_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Choose books to send to KOReader",
            str(Path.home()),
            BOOK_FILTER,
        )
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
        self.book_count.setText(
            f"{count} book{'s' if count != 1 else ''} · {human_size(total)}"
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
        self.set_busy(True, f"Connecting to {self.discovered_ip}...")
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
        self.primary_status.setText(
            f"Transfer complete · {count} book{'s' if count != 1 else ''} sent"
        )
        self.operation_status.setText(
            f"Sent {human_size(byte_count)}. Refresh KOReader's file browser."
        )
        verb = "were" if count != 1 else "was"
        QMessageBox.information(
            self,
            "Books sent",
            f"{count} book{'s' if count != 1 else ''} {verb} sent successfully.\n\n"
            "Find them in documents/Books in KOReader.",
        )

    def operation_failed(self, message: str) -> None:
        self.primary_status.setText("Action needed")
        self.operation_status.setText(message)
        QMessageBox.warning(self, APP_NAME, message)

    def worker_finished(self) -> None:
        self.active_worker = None
        self.set_busy(False)
        self.refresh_file_state()

    def cancel_operation(self) -> None:
        if self.active_worker:
            self.active_worker.cancel()
        self.operation_status.setText("Cancelling...")

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
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
