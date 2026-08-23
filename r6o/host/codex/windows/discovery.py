from __future__ import annotations

import os
import platform
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

CODEX_PRODUCT_NAME = "Codex"


@dataclass(frozen=True)
class HostCandidate:
    hwnd: int
    pid: int
    executable: str
    product_name: str
    product_version: str
    file_version: str
    package_version: str | None
    title: str
    class_name: str
    visible: bool

    def as_record(self) -> dict[str, Any]:
        return asdict(self)


class HostDiscoveryError(RuntimeError):
    """A stable, machine-readable actual-host discovery failure."""

    def __init__(self, code: str, candidates: Iterable[HostCandidate] = ()) -> None:
        self.code = code
        self.candidates = tuple(candidates)
        super().__init__(code)

    def as_record(self) -> dict[str, Any]:
        return {
            "status": "FAIL",
            "code": self.code,
            "candidates": [candidate.as_record() for candidate in self.candidates],
        }


def _require_windows() -> None:
    if sys.platform != "win32":
        raise HostDiscoveryError("HOST_PLATFORM_UNSUPPORTED")


def _load_win32() -> tuple[Any, Any, Any, Any]:
    _require_windows()
    try:
        import win32api
        import win32con
        import win32gui
        import win32process
    except ImportError as exc:  # pragma: no cover - exercised only on misconfigured Windows hosts
        raise HostDiscoveryError("HOST_DEPENDENCY_MISSING") from exc
    return win32api, win32con, win32gui, win32process


def _version_strings(executable: str, win32api: Any) -> dict[str, str]:
    translations: list[tuple[int, int]] = []
    try:
        raw = win32api.GetFileVersionInfo(executable, r"\VarFileInfo\Translation")
        translations.extend(tuple(pair) for pair in raw)
    except Exception:
        pass
    for fallback in ((0x0409, 0x04B0), (0x0409, 0x04E4)):
        if fallback not in translations:
            translations.append(fallback)

    result: dict[str, str] = {}
    for key in ("ProductName", "ProductVersion", "FileVersion"):
        for language, codepage in translations:
            query = rf"\StringFileInfo\{language:04x}{codepage:04x}\{key}"
            try:
                value = win32api.GetFileVersionInfo(executable, query)
            except Exception:
                continue
            if isinstance(value, str) and value.strip():
                result[key] = value.strip()
                break
        result.setdefault(key, "")
    return result


def enumerate_visible_top_level_windows() -> list[HostCandidate]:
    """Enumerate visible Win32 top-level windows and resolve process metadata."""

    win32api, win32con, win32gui, win32process = _load_win32()
    candidates: list[HostCandidate] = []

    def visit(hwnd: int, _context: Any) -> bool:
        if not win32gui.IsWindowVisible(hwnd) or win32gui.GetParent(hwnd):
            return True
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if not pid:
            return True
        process = None
        try:
            process = win32api.OpenProcess(
                win32con.PROCESS_QUERY_INFORMATION | win32con.PROCESS_VM_READ,
                False,
                pid,
            )
            executable = str(Path(win32process.GetModuleFileNameEx(process, 0)).resolve())
            metadata = _version_strings(executable, win32api)
            candidates.append(
                HostCandidate(
                    hwnd=int(hwnd),
                    pid=int(pid),
                    executable=executable,
                    product_name=metadata["ProductName"],
                    product_version=metadata["ProductVersion"],
                    file_version=metadata["FileVersion"],
                    package_version=_package_version(executable),
                    title=win32gui.GetWindowText(hwnd),
                    class_name=win32gui.GetClassName(hwnd),
                    visible=True,
                )
            )
        except Exception:
            # An inaccessible non-Codex process is not a candidate. Codex itself is
            # installed per-user and must be readable for this gate to pass.
            pass
        finally:
            if process is not None:
                win32api.CloseHandle(process)
        return True

    win32gui.EnumWindows(visit, None)
    return candidates


def is_codex_candidate(candidate: HostCandidate, *, current_pid: int) -> bool:
    return (
        candidate.visible
        and candidate.pid != current_pid
        and candidate.product_name.strip().casefold() == CODEX_PRODUCT_NAME.casefold()
        and bool(candidate.product_version.strip())
        and bool(candidate.file_version.strip())
        and Path(candidate.executable).is_absolute()
    )


def select_unique_codex_host(
    windows: Iterable[HostCandidate], *, current_pid: int | None = None
) -> HostCandidate:
    pid = os.getpid() if current_pid is None else current_pid
    matches = tuple(candidate for candidate in windows if is_codex_candidate(candidate, current_pid=pid))
    if not matches:
        raise HostDiscoveryError("HOST_NOT_FOUND")
    if len(matches) != 1:
        raise HostDiscoveryError("HOST_AMBIGUOUS", matches)
    return matches[0]


def discover_codex_host(
    enumerator: Callable[[], list[HostCandidate]] = enumerate_visible_top_level_windows,
) -> HostCandidate:
    return select_unique_codex_host(enumerator())


def _rect_record(rect: Any) -> dict[str, int]:
    left, top, right, bottom = (int(value) for value in rect)
    return {
        "left": left,
        "top": top,
        "right": right,
        "bottom": bottom,
        "width": right - left,
        "height": bottom - top,
    }


def _package_version(executable: str) -> str | None:
    match = re.search(r"OpenAI\.Codex_(\d+\.\d+\.\d+\.\d+)_", executable, re.IGNORECASE)
    return match.group(1) if match else None


def build_environment_record(candidate: HostCandidate) -> dict[str, Any]:
    """Measure the selected host and return the exact D1 environment record."""

    win32api, win32con, win32gui, _ = _load_win32()
    if not win32gui.IsWindow(candidate.hwnd) or not win32gui.IsWindowVisible(candidate.hwnd):
        raise HostDiscoveryError("HOST_WINDOW_STALE", (candidate,))
    if win32gui.IsIconic(candidate.hwnd):
        raise HostDiscoveryError("HOST_WINDOW_MINIMIZED", (candidate,))

    window_rect = win32gui.GetWindowRect(candidate.hwnd)
    client_local = win32gui.GetClientRect(candidate.hwnd)
    client_origin = win32gui.ClientToScreen(candidate.hwnd, (client_local[0], client_local[1]))
    client_end = win32gui.ClientToScreen(candidate.hwnd, (client_local[2], client_local[3]))
    client_rect = (*client_origin, *client_end)
    monitor = win32api.MonitorFromWindow(candidate.hwnd, win32con.MONITOR_DEFAULTTONEAREST)
    monitor_info = win32api.GetMonitorInfo(monitor)
    try:
        import ctypes

        dpi = int(ctypes.windll.user32.GetDpiForWindow(candidate.hwnd))
    except Exception:
        dpi = 96
    windows_version = sys.getwindowsversion()
    record = {
        "schema_version": "r6o-h2-d1-host-environment-1",
        "status": "HOST_DISCOVERED",
        "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "windows": {
            "edition": platform.win32_edition(),
            "version": platform.version(),
            "build": int(windows_version.build),
            "architecture": platform.machine(),
        },
        "codex": {
            "hwnd": candidate.hwnd,
            "pid": candidate.pid,
            "executable": candidate.executable,
            "product_name": candidate.product_name,
            "product_version": candidate.product_version,
            "file_version": candidate.file_version,
            "package_version": candidate.package_version,
            "window_title": candidate.title,
            "window_class": candidate.class_name,
            "window_rectangle": _rect_record(window_rect),
            "client_rectangle": _rect_record(client_rect),
            "monitor": {
                "handle": int(monitor),
                "id": monitor_info.get("Device", ""),
                "rectangle": _rect_record(monitor_info["Monitor"]),
                "work_area": _rect_record(monitor_info["Work"]),
            },
            "dpi": dpi,
            "scale": dpi / 96.0,
        },
    }
    validate_environment_record(record)
    return record


def validate_environment_record(record: dict[str, Any]) -> None:
    """Reject incomplete or internally inconsistent D1 environment evidence."""

    try:
        windows = record["windows"]
        codex = record["codex"]
        monitor = codex["monitor"]
        if record["schema_version"] != "r6o-h2-d1-host-environment-1":
            raise ValueError
        if record["status"] != "HOST_DISCOVERED" or not str(record["timestamp_utc"]).endswith("Z"):
            raise ValueError
        for key in ("edition", "version", "architecture"):
            if not isinstance(windows[key], str) or not windows[key].strip():
                raise ValueError
        if not isinstance(windows["build"], int) or windows["build"] <= 0:
            raise ValueError
        if not isinstance(codex["hwnd"], int) or codex["hwnd"] <= 0:
            raise ValueError
        if not isinstance(codex["pid"], int) or codex["pid"] <= 0:
            raise ValueError
        if not Path(codex["executable"]).is_absolute():
            raise ValueError
        for key in (
            "product_name",
            "product_version",
            "file_version",
            "window_title",
            "window_class",
        ):
            if not isinstance(codex[key], str) or not codex[key].strip():
                raise ValueError
        for rectangle in (
            codex["window_rectangle"],
            codex["client_rectangle"],
            monitor["rectangle"],
            monitor["work_area"],
        ):
            if set(rectangle) != {"left", "top", "right", "bottom", "width", "height"}:
                raise ValueError
            if any(not isinstance(rectangle[key], int) for key in rectangle):
                raise ValueError
            if rectangle["width"] <= 0 or rectangle["height"] <= 0:
                raise ValueError
            if rectangle["right"] - rectangle["left"] != rectangle["width"]:
                raise ValueError
            if rectangle["bottom"] - rectangle["top"] != rectangle["height"]:
                raise ValueError
        if not isinstance(monitor["handle"], int) or monitor["handle"] <= 0:
            raise ValueError
        if not isinstance(monitor["id"], str) or not monitor["id"].strip():
            raise ValueError
        if not isinstance(codex["dpi"], int) or codex["dpi"] <= 0:
            raise ValueError
        if not isinstance(codex["scale"], (int, float)) or codex["scale"] <= 0:
            raise ValueError
        if abs(float(codex["scale"]) - codex["dpi"] / 96.0) > 1e-9:
            raise ValueError
        uia = codex.get("uia_connection")
        if uia is not None and (
            not isinstance(uia, dict)
            or uia.get("backend") != "uia"
            or uia.get("connected") is not True
            or not isinstance(uia.get("root_control_type"), str)
            or not isinstance(uia.get("root_automation_id"), str)
        ):
            raise ValueError
    except (KeyError, TypeError, ValueError) as exc:
        raise HostDiscoveryError("HOST_ENVIRONMENT_INVALID") from exc
