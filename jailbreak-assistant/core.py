from __future__ import annotations

import ctypes
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable


APP_NAME = "Kindle Jailbreak Assistant"
APP_VERSION = "0.1.1"
USER_AGENT = f"LazyingArt-{APP_NAME.replace(' ', '-')}/{APP_VERSION}"
MIB = 1024 * 1024


class AssistantError(RuntimeError):
    pass


@dataclass
class KindleDevice:
    root: Path
    label: str
    score: int
    total: int
    free: int
    firmware: str = ""
    serial: str = ""

    @property
    def display(self) -> str:
        free_gib = self.free / (1024 ** 3)
        return f"{self.label} - {self.root} - {free_gib:.1f} GiB free"


def resource_path(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / name


def app_data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    path = base / "LazyingArt" / "KindleJailbreakAssistant"
    path.mkdir(parents=True, exist_ok=True)
    return path


def platform_key() -> str:
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def _read_json_url(url: str, timeout: int = 8) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def load_catalog(refresh: bool = False) -> dict[str, Any]:
    with resource_path("compatibility.json").open("r", encoding="utf-8") as handle:
        local = json.load(handle)
    if not refresh:
        return local
    try:
        remote = _read_json_url(local["catalog_url"])
        if remote.get("schema_version") == local.get("schema_version"):
            return remote
    except Exception:
        pass
    return local


def load_models(catalog: dict[str, Any], online: bool = True) -> tuple[list[dict[str, Any]], bool]:
    if online:
        try:
            models = _read_json_url(catalog["models_url"])
            if isinstance(models, list) and len(models) >= 20:
                return models, True
        except Exception:
            pass
    return catalog["fallback_models"], False


def _version_tuple(value: str) -> tuple[int, ...] | None:
    if not value:
        return None
    numbers = re.findall(r"\d+", value)
    if not numbers:
        return None
    parts = [int(part) for part in numbers[:5]]
    return tuple((parts + [0] * 5)[:5])


def _firmware_match(value: str, rule: dict[str, Any]) -> tuple[bool | None, str]:
    if not rule:
        return True, "Firmware is not constrained by this catalog entry"
    actual = _version_tuple(value)
    if actual is None:
        return None, "Enter the exact firmware version to confirm compatibility"
    exact = rule.get("exact", [])
    if exact:
        allowed = [_version_tuple(item) for item in exact]
        ok = actual in allowed
        return ok, "Firmware is explicitly supported" if ok else "Firmware is outside the documented exact builds"
    minimum = _version_tuple(rule.get("min", ""))
    maximum = _version_tuple(rule.get("max", ""))
    if minimum is not None and actual < minimum:
        return False, f"Firmware is below the documented minimum {rule['min']}"
    if maximum is not None and actual > maximum:
        return False, f"Firmware is above the documented maximum {rule['max']}"
    return True, "Firmware is inside the documented range"


def _model_aliases(model: dict[str, Any] | None) -> set[str]:
    if not model:
        return set()
    aliases = model.get("nicknames", [])
    if isinstance(aliases, str):
        aliases = [aliases]
    return {str(alias).strip().upper() for alias in aliases if str(alias).strip()}


def identify_model(serial: str, models: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
    serial = re.sub(r"\s+", "", serial.upper())
    if len(serial) in (2, 3):
        code = serial
        serial_version = 0 if len(serial) == 2 else 1
    elif serial.startswith("G") and len(serial) >= 6:
        code = serial[3:6]
        serial_version = 1
    elif serial and serial[0] in "0123456789ABCDEF" and len(serial) >= 4:
        code = serial[2:4]
        serial_version = 0
    else:
        return None
    for model in models:
        if int(model.get("serial_version", serial_version)) < serial_version:
            continue
        codes = model.get("device_codes", {})
        if code in codes:
            return model
    return None


def analyze(
    catalog: dict[str, Any],
    model: dict[str, Any] | None,
    firmware: str,
    state: dict[str, str],
) -> list[dict[str, Any]]:
    aliases = _model_aliases(model)
    host = platform_key()
    results: list[dict[str, Any]] = []
    for method in catalog["methods"]:
        if method.get("hidden"):
            continue
        matched_variant = None
        firmware_state: bool | None = False
        firmware_reason = "Model is not listed for this method"
        for variant in method.get("variants", []):
            allowed_models = {item.upper() for item in variant.get("models", [])}
            if "*" not in allowed_models and not aliases.intersection(allowed_models):
                continue
            current_state, current_reason = _firmware_match(firmware, variant.get("firmware", {}))
            if current_state is False:
                firmware_reason = current_reason
                continue
            matched_variant = variant
            firmware_state = current_state
            firmware_reason = current_reason
            break
        if matched_variant is None:
            continue

        missing: list[str] = []
        unmet: list[str] = []
        for requirement in matched_variant.get("requirements", []):
            current = state.get(requirement["key"], "unknown")
            if current == "unknown":
                missing.append(requirement["label"])
            elif current not in requirement["allowed"]:
                unmet.append(requirement["label"])

        platform_ok = host in method.get("platforms", [])
        if firmware_state is True and not missing and not unmet and platform_ok:
            status = "compatible"
        elif not platform_ok:
            status = "manual"
        else:
            status = "conditional"

        score = int(method.get("priority", 0))
        if status == "compatible":
            score += 1000
        elif status == "conditional":
            score += 500
        results.append(
            {
                "method": method,
                "status": status,
                "score": score,
                "firmware_reason": firmware_reason,
                "missing": missing,
                "unmet": unmet,
                "platform_ok": platform_ok,
            }
        )
    results.sort(key=lambda item: item["score"], reverse=True)
    return results


def _volume_label(root: Path) -> str:
    if sys.platform != "win32":
        return root.name or str(root)
    buffer = ctypes.create_unicode_buffer(261)
    fs_buffer = ctypes.create_unicode_buffer(261)
    serial = ctypes.c_ulong()
    max_component = ctypes.c_ulong()
    flags = ctypes.c_ulong()
    ok = ctypes.windll.kernel32.GetVolumeInformationW(
        str(root), buffer, len(buffer), ctypes.byref(serial), ctypes.byref(max_component), ctypes.byref(flags), fs_buffer, len(fs_buffer)
    )
    return buffer.value if ok and buffer.value else "Removable drive"


def _candidate_mounts() -> set[Path]:
    candidates: set[Path] = set()
    if sys.platform == "win32":
        mask = ctypes.windll.kernel32.GetLogicalDrives()
        for index in range(26):
            if mask & (1 << index):
                root = Path(f"{chr(65 + index)}:\\")
                drive_type = ctypes.windll.kernel32.GetDriveTypeW(str(root))
                if drive_type in (2, 3):
                    candidates.add(root)
    else:
        roots = [Path("/Volumes"), Path("/media"), Path("/run/media"), Path("/mnt")]
        run_user = Path(f"/run/user/{os.getuid()}/gvfs") if hasattr(os, "getuid") else None
        if run_user:
            roots.append(run_user)
        for base in roots:
            if not base.is_dir():
                continue
            try:
                for child in base.iterdir():
                    if child.is_dir():
                        candidates.add(child)
                        try:
                            for grandchild in child.iterdir():
                                if grandchild.is_dir():
                                    candidates.add(grandchild)
                        except OSError:
                            pass
            except OSError:
                pass
        if Path("/proc/mounts").exists():
            try:
                for line in Path("/proc/mounts").read_text(encoding="utf-8", errors="ignore").splitlines():
                    fields = line.split()
                    if len(fields) > 1:
                        mount = Path(fields[1].replace("\\040", " "))
                        if str(mount).startswith(("/media/", "/run/media/", "/mnt/", "/run/user/")):
                            candidates.add(mount)
            except OSError:
                pass
    return candidates


def _marker_score(root: Path) -> int:
    weights = {
        "documents": 5,
        "system": 3,
        "audible": 1,
        "fonts": 1,
        "extensions": 2,
        ".active_content_sandbox": 5,
    }
    score = 0
    for name, weight in weights.items():
        try:
            if (root / name).exists():
                score += weight
        except OSError:
            pass
    try:
        if "kindle" in _volume_label(root).lower():
            score += 5
    except OSError:
        pass
    return score


def _inspect_text(root: Path, names: list[str], pattern: str) -> str:
    regex = re.compile(pattern, re.IGNORECASE)
    for name in names:
        path = root / name
        try:
            if path.is_file() and path.stat().st_size < 512 * 1024:
                match = regex.search(path.read_text(encoding="utf-8", errors="ignore"))
                if match:
                    return match.group(1)
        except OSError:
            continue
    return ""


def inspect_device(root: Path) -> KindleDevice:
    root = root.resolve()
    if not root.is_dir():
        raise AssistantError(f"Kindle path does not exist: {root}")
    usage = shutil.disk_usage(root)
    firmware = _inspect_text(
        root,
        ["system/version.txt", "system/firmware_version.txt", "version.txt"],
        r"(?:firmware|version)?[^0-9]*(5(?:\.\d+){1,4})",
    )
    if not firmware:
        try:
            for candidate in root.glob("update*.bin*"):
                match = re.search(r"(5(?:\.\d+){1,4})", candidate.name)
                if match:
                    firmware = match.group(1)
                    break
        except OSError:
            pass
    serial = _inspect_text(
        root,
        ["system/serial.txt", ".kindle_serial", "serial.txt"],
        r"\b([A-Z0-9][A-Z0-9 ]{7,24})\b",
    )
    label = _volume_label(root)
    return KindleDevice(root, label, _marker_score(root), usage.total, usage.free, firmware, serial)


def discover_kindles() -> list[KindleDevice]:
    devices: list[KindleDevice] = []
    for root in _candidate_mounts():
        try:
            score = _marker_score(root)
            if score >= 5:
                device = inspect_device(root)
                device.score = score
                devices.append(device)
        except (OSError, AssistantError):
            continue
    devices.sort(key=lambda device: (-device.score, str(device.root).lower()))
    return devices


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_package(method: dict[str, Any], progress: Callable[[str], None] | None = None) -> Path:
    package = method.get("package")
    if not package:
        raise AssistantError(f"{method['name']} has no host package; use the official guide.")
    cache = app_data_dir() / "packages" / method["id"]
    cache.mkdir(parents=True, exist_ok=True)
    destination = cache / package["filename"]
    expected = package.get("sha256", "").lower()
    if destination.exists() and (not expected or _hash_file(destination) == expected):
        return destination
    partial = destination.with_suffix(destination.suffix + ".part")
    partial.unlink(missing_ok=True)
    if progress:
        progress(f"Downloading official {method['name']} package...")
    request = urllib.request.Request(package["url"], headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=30) as response, partial.open("wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
    except Exception as exc:
        partial.unlink(missing_ok=True)
        raise AssistantError(f"Download failed: {exc}") from exc
    actual = _hash_file(partial)
    if expected and actual != expected:
        partial.unlink(missing_ok=True)
        raise AssistantError(f"SHA-256 verification failed for {package['filename']}.")
    partial.replace(destination)
    metadata = {"url": package["url"], "sha256": actual, "downloaded": datetime.now().isoformat(timespec="seconds")}
    (cache / "download.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return destination


def _safe_target(base: Path, name: str) -> Path:
    target = (base / name).resolve()
    try:
        target.relative_to(base.resolve())
    except ValueError as exc:
        raise AssistantError(f"Unsafe archive path rejected: {name}") from exc
    return target


def safe_extract(archive: Path, archive_type: str, destination: Path) -> Path:
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    if archive_type == "zip":
        with zipfile.ZipFile(archive) as bundle:
            for info in bundle.infolist():
                target = _safe_target(destination, info.filename)
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise AssistantError(f"Archive symlink rejected: {info.filename}")
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(info) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
                if mode:
                    target.chmod(mode & 0o777)
    elif archive_type == "tar.gz":
        with tarfile.open(archive, "r:gz") as bundle:
            for member in bundle.getmembers():
                target = _safe_target(destination, member.name)
                if member.issym() or member.islnk() or member.isdev():
                    raise AssistantError(f"Unsafe tar entry rejected: {member.name}")
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if not member.isfile():
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                source = bundle.extractfile(member)
                if source is None:
                    continue
                with source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
                target.chmod(member.mode & 0o777)
    else:
        raise AssistantError(f"Unsupported archive type: {archive_type}")
    return _payload_root(destination)


def _payload_root(directory: Path) -> Path:
    entries = [entry for entry in directory.iterdir() if entry.name not in {"__MACOSX", ".DS_Store"}]
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return directory


def _backup_dir(method_id: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = app_data_dir() / "backups" / f"{stamp}-{method_id}"
    path.mkdir(parents=True, exist_ok=False)
    return path


def _iter_payload_files(source: Path) -> Iterable[tuple[Path, Path]]:
    for path in source.rglob("*"):
        if not path.is_file() or "__MACOSX" in path.parts or path.name == ".DS_Store":
            continue
        yield path, path.relative_to(source)


def stage_tree(source: Path, kindle_root: Path, method_id: str) -> dict[str, Any]:
    kindle_root = kindle_root.resolve()
    backup = _backup_dir(method_id)
    copied = 0
    backed_up = 0
    for payload, relative in _iter_payload_files(source):
        destination = _safe_target(kindle_root, relative.as_posix())
        if destination.exists() and destination.is_file():
            backup_target = backup / relative
            backup_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(destination, backup_target)
            backed_up += 1
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(payload, destination)
        copied += 1
    if copied == 0:
        raise AssistantError("The official package contained no stageable files.")
    manifest = {"method": method_id, "kindle": str(kindle_root), "copied": copied, "backed_up": backed_up}
    (backup / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {"copied": copied, "backed_up": backed_up, "backup": backup}


def _prepare_adbreak(payload: Path, kindle_root: Path) -> dict[str, Any]:
    candidates = [kindle_root / "system" / ".assets", kindle_root / ".assets"]
    assets = next((path for path in candidates if path.is_dir()), None)
    if assets is None:
        raise AssistantError("Could not find system/.assets. Confirm ads are downloaded and hidden files are accessible.")
    adbreak_html = next(payload.rglob("adbreak.html"), None)
    if adbreak_html is None:
        raise AssistantError("The verified AdBreak package is missing adbreak.html.")
    backup = _backup_dir("adbreak")
    shutil.copytree(assets, backup / ".assets")
    work = Path(tempfile.mkdtemp(prefix="adbreak-", dir=app_data_dir())) / ".assets"
    shutil.copytree(assets, work)
    overlay_root = _payload_root(payload)
    for source, relative in _iter_payload_files(overlay_root):
        if source.suffix.lower() in {".bat", ".cmd"}:
            continue
        destination = work / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    replacements = list(work.rglob("details.html"))
    if not replacements:
        shutil.rmtree(work.parent, ignore_errors=True)
        raise AssistantError("No ad details.html files were found; let the Kindle download multiple ads first.")
    for details in replacements:
        shutil.copy2(adbreak_html, details)
    new_assets = assets.parent / ".assets.lazyingart-new"
    old_assets = assets.parent / ".assets.lazyingart-old"
    if new_assets.exists() or old_assets.exists():
        shutil.rmtree(work.parent, ignore_errors=True)
        raise AssistantError("A previous .assets staging folder exists. Restore or remove it before retrying.")
    shutil.copytree(work, new_assets)
    assets.rename(old_assets)
    try:
        new_assets.rename(assets)
    except Exception:
        old_assets.rename(assets)
        raise
    shutil.rmtree(old_assets)
    shutil.rmtree(work.parent, ignore_errors=True)
    (backup / "manifest.json").write_text(
        json.dumps({"method": "adbreak", "kindle": str(kindle_root), "replaced_ads": len(replacements)}, indent=2),
        encoding="utf-8",
    )
    return {"copied": len(replacements), "backed_up": 1, "backup": backup}


def prepare_method(
    method: dict[str, Any],
    kindle_root: Path | None,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    package = method.get("package")
    if not package:
        return {"kind": "guide", "guide": method["guide_url"]}
    archive = download_package(method, progress)
    mode = package["mode"]
    if mode == "copy_file":
        if kindle_root is None:
            raise AssistantError("Connect or select the Kindle first.")
        backup = _backup_dir(method["id"])
        destination = kindle_root / archive.name
        if destination.exists():
            shutil.copy2(destination, backup / destination.name)
        shutil.copy2(archive, destination)
        (backup / "manifest.json").write_text(json.dumps({"copied": destination.name}, indent=2), encoding="utf-8")
        return {"kind": "staged", "copied": 1, "backed_up": int((backup / destination.name).exists()), "backup": backup}
    extract_dir = app_data_dir() / "extracted" / method["id"]
    payload = safe_extract(archive, package["archive"], extract_dir)
    if mode == "runner":
        runners = package["runners"].get(platform_key(), [])
        for name in runners:
            runner = next(payload.rglob(name), None)
            if runner:
                runner.chmod(runner.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
                return {"kind": "runner", "runner": runner}
        raise AssistantError("The verified package does not contain a helper for this platform.")
    if kindle_root is None:
        raise AssistantError("Connect or select the Kindle first.")
    if mode == "adbreak":
        result = _prepare_adbreak(payload, kindle_root)
    else:
        result = stage_tree(payload, kindle_root, method["id"])
    result["kind"] = "staged"
    return result


def launch_runner(runner: Path) -> None:
    runner = runner.resolve()
    if sys.platform == "win32":
        subprocess.Popen([str(runner)], cwd=str(runner.parent), creationflags=subprocess.CREATE_NEW_CONSOLE)
        return
    command = f"cd {shlex.quote(str(runner.parent))} && {shlex.quote(str(runner))}"
    if sys.platform == "darwin":
        escaped = command.replace("\\", "\\\\").replace('"', '\\"')
        subprocess.Popen(["osascript", "-e", f'tell application "Terminal" to do script "{escaped}"'])
        return
    terminals = [
        ["x-terminal-emulator", "-e", "bash", "-lc", command + "; exec bash"],
        ["gnome-terminal", "--", "bash", "-lc", command + "; exec bash"],
        ["konsole", "-e", "bash", "-lc", command + "; exec bash"],
        ["xterm", "-e", "bash", "-lc", command + "; exec bash"],
    ]
    for candidate in terminals:
        if shutil.which(candidate[0]):
            subprocess.Popen(candidate)
            return
    subprocess.Popen([str(runner)], cwd=str(runner.parent))


def open_path(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(str(path))
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def create_space_guard(
    kindle_root: Path,
    target_free_mib: int = 80,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    guard = kindle_root / ".lazyingart_ota_guard"
    marker = guard / "manifest.json"
    if guard.exists() and not marker.exists():
        raise AssistantError("The guard folder exists without this app's manifest; it will not be modified.")
    guard.mkdir(parents=True, exist_ok=True)
    target = target_free_mib * MIB
    before = shutil.disk_usage(kindle_root).free
    if before <= target:
        marker.write_text(json.dumps({"target_mib": target_free_mib, "created": datetime.now().isoformat()}, indent=2), encoding="utf-8")
        return {"written": 0, "free": before}
    index = len(list(guard.glob("guard-*.bin")))
    written = 0
    block = b"\0" * MIB
    while True:
        free = shutil.disk_usage(kindle_root).free
        remaining = free - target
        if remaining <= MIB:
            break
        chunk_size = min(32 * MIB, remaining - MIB)
        path = guard / f"guard-{index:05d}.bin"
        if progress:
            progress(f"Creating reversible OTA guard: {free / MIB:.0f} MiB free")
        with path.open("wb") as handle:
            left = chunk_size
            while left > 0:
                piece = block if left >= MIB else block[:left]
                handle.write(piece)
                left -= len(piece)
            handle.flush()
            os.fsync(handle.fileno())
        written += chunk_size
        index += 1
    marker.write_text(
        json.dumps({"target_mib": target_free_mib, "created": datetime.now().isoformat(), "bytes_written": written}, indent=2),
        encoding="utf-8",
    )
    return {"written": written, "free": shutil.disk_usage(kindle_root).free}


def remove_space_guard(kindle_root: Path) -> int:
    guard = kindle_root / ".lazyingart_ota_guard"
    marker = guard / "manifest.json"
    if not guard.exists():
        return 0
    if not marker.is_file():
        raise AssistantError("Refusing to remove a guard folder not created by this app.")
    size = sum(path.stat().st_size for path in guard.rglob("*") if path.is_file())
    shutil.rmtree(guard)
    return size


def create_safety_snapshot(kindle_root: Path) -> Path:
    backup = _backup_dir("safety-snapshot")
    device = inspect_device(kindle_root)
    manifest = {
        "root": str(device.root),
        "label": device.label,
        "total": device.total,
        "free": device.free,
        "firmware": device.firmware,
        "created": datetime.now().isoformat(timespec="seconds"),
    }
    for pattern in ("update*.bin*", "*.log"):
        for source in kindle_root.glob(pattern):
            if source.is_file() and source.stat().st_size <= 32 * MIB:
                shutil.copy2(source, backup / source.name)
    (backup / "device.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return backup


def method_by_id(catalog: dict[str, Any], method_id: str) -> dict[str, Any]:
    for method in catalog["methods"]:
        if method["id"] == method_id:
            return method
    raise AssistantError(f"Catalog method not found: {method_id}")
