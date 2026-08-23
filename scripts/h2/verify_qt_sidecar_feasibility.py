from __future__ import annotations

"""Fail-closed H2-C Qt Quick shell qualification."""

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import PySide6
from PySide6.QtCore import QMetaObject, QPoint, Qt, qVersion
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest

from r6o.views.sidecar import EXPANDED_SIZE, STANDARD_SIZE, QtSidecarWindow, SidecarMode


DEFAULT_EVIDENCE = REPO_ROOT / "r6o_evidence" / "H2-C-QT-QUICK" / "feasibility"
ASSET_ROOT = REPO_ROOT / "r6o" / "views" / "sidecar" / "assets"
ASSET_PROVENANCE = ASSET_ROOT / "ASSET-PROVENANCE.json"
EXPECTED_QPA = {"windows": "windows", "x11": "xcb", "wayland": "wayland"}
CAPTURE_NAMES = {
    SidecarMode.STANDARD: "H2-C-FEASIBILITY-STANDARD.png",
    SidecarMode.EXPANDED: "H2-C-FEASIBILITY-EXPANDED.png",
}
REQUIRED_OBJECTS = (
    "sidecarSurface", "sidecarChrome", "sidecarTitle", "stageBadge", "activeDot",
    "activeLabel", "closeControl", "closeIcon", "artifactCard", "artifactTitle",
    "artifactBody", "artifactFlickable", "openEditorControl", "externalLinkIcon",
    "sourceLabel", "sourceValue", "copyControl", "reviewOptions",
    "reviewOptionsTitle", "actionsColumn", "tipText",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_asset_provenance() -> dict[str, str]:
    provenance = json.loads(ASSET_PROVENANCE.read_text(encoding="utf-8"))
    expected: dict[str, str] = {}
    for font in provenance["fonts"]:
        expected.update(font["files"])
    expected.update(provenance["icons"]["files"])
    observed: dict[str, str] = {}
    for relative_path, expected_hash in expected.items():
        path = ASSET_ROOT / relative_path
        if not path.is_file():
            raise AssertionError(f"approved Sidecar asset is missing: {relative_path}")
        actual_hash = sha256_file(path)
        if actual_hash != expected_hash:
            raise AssertionError(
                f"Sidecar asset hash mismatch for {relative_path}: {actual_hash}"
            )
        observed[relative_path] = actual_hash
    return observed


def git_value(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()


def wait_for(predicate: Any, timeout_seconds: float = 3.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    app = QGuiApplication.instance()
    while time.monotonic() < deadline:
        assert app is not None
        app.processEvents()
        if predicate():
            return
        QTest.qWait(20)
    raise AssertionError("timed out waiting for Qt qualification state")


def assert_capture(image: Any, expected_size: tuple[int, int]) -> dict[str, Any]:
    observed = (image.width(), image.height())
    if observed != expected_size:
        raise AssertionError(f"capture size {observed} != {expected_size}")
    corners = {
        "top_left": image.pixelColor(0, 0).alpha(),
        "top_right": image.pixelColor(image.width() - 1, 0).alpha(),
        "bottom_left": image.pixelColor(0, image.height() - 1).alpha(),
        "bottom_right": image.pixelColor(image.width() - 1, image.height() - 1).alpha(),
    }
    if any(alpha != 0 for alpha in corners.values()):
        raise AssertionError(f"outer rounded corners are not transparent: {corners}")
    center_alpha = image.pixelColor(image.width() // 2, image.height() // 2).alpha()
    if center_alpha != 255:
        raise AssertionError(f"Sidecar center is not opaque: alpha={center_alpha}")
    return {"size": list(observed), "corner_alpha": corners, "center_alpha": center_alpha}


def qualify(target: str, evidence_root: Path, hold_seconds: float) -> dict[str, Any]:
    asset_hashes = verify_asset_provenance()
    sidecar = QtSidecarWindow(SidecarMode.STANDARD)
    sidecar.show()
    try:
        actual_qpa = QGuiApplication.platformName().lower()
        if actual_qpa != EXPECTED_QPA[target]:
            raise AssertionError(
                f"Qt backend {actual_qpa!r} != required {EXPECTED_QPA[target]!r}"
            )
        if not sidecar.window.flags() & Qt.FramelessWindowHint:
            raise AssertionError("Qt Sidecar window is not frameless")
        if sidecar.window.color().alpha() != 0:
            raise AssertionError("Qt Sidecar top-level clear color is not transparent")
        if not bool(sidecar.window.property("assetsReady")):
            raise AssertionError("local fonts or SVG assets did not load")
        if str(sidecar.window.property("uiFamily")) != "Inter":
            raise AssertionError(f"unexpected UI font: {sidecar.window.property('uiFamily')!r}")
        if str(sidecar.window.property("monoFamily")) != "JetBrains Mono":
            raise AssertionError(
                f"unexpected artifact font: {sidecar.window.property('monoFamily')!r}"
            )
        for object_name in REQUIRED_OBJECTS:
            sidecar.object(object_name)
        sidecar.object("expandControl")
        sidecar.object("expandIcon")

        QTest.mouseClick(sidecar.window, Qt.LeftButton, Qt.NoModifier, QPoint(530, 131))
        wait_for(lambda: sidecar.bridge.lastActionId == "change_task")
        if not QMetaObject.invokeMethod(sidecar.window, "focusFirstAction", Qt.DirectConnection):
            raise AssertionError("unable to focus the first QML action")
        QTest.keyClick(sidecar.window, Qt.Key_Return)
        wait_for(lambda: sidecar.bridge.lastActionId == "confirm_prompt")

        platform_dir = evidence_root / target
        platform_dir.mkdir(parents=True, exist_ok=True)
        modes: dict[str, Any] = {}
        for mode, size in (
            (SidecarMode.STANDARD, STANDARD_SIZE),
            (SidecarMode.EXPANDED, EXPANDED_SIZE),
        ):
            sidecar.set_mode(mode)
            wait_for(lambda size=size: (sidecar.window.width(), sidecar.window.height()) == size)
            if hold_seconds:
                QTest.qWait(round(hold_seconds * 1000))
            capture_path = platform_dir / CAPTURE_NAMES[mode]
            image = sidecar.capture(capture_path)
            modes[mode.value] = {
                **assert_capture(image, size),
                "capture": capture_path.name,
                "capture_sha256": sha256_file(capture_path),
            }

        report = {
            "schema_version": "r6o-h2-c-qt-feasibility-1",
            "gate": "H2-C-QT-FEASIBILITY",
            "status": "MECHANICAL_FEASIBILITY_PASS",
            "human_visual_approval": "PENDING",
            "overall_h2_pass_authorized": False,
            "real_codex_host_tested": False,
            "d2_implemented": False,
            "target": target,
            "runtime": {
                "os": platform.platform(),
                "python": platform.python_version(),
                "pyside6": PySide6.__version__,
                "qt": qVersion(),
                "qpa_platform": actual_qpa,
                "logical_dpi": sidecar.window.screen().logicalDotsPerInch(),
                "device_pixel_ratio": sidecar.window.devicePixelRatio(),
            },
            "source": {
                "branch": git_value("branch", "--show-current"),
                "head": git_value("rev-parse", "HEAD"),
                "tree": git_value("rev-parse", "HEAD^{tree}"),
            },
            "proof": {
                "production_framework": "PySide6 + Qt Quick/QML",
                "frameless": True,
                "transparent_rounded_silhouette": True,
                "local_fonts": ["Inter", "JetBrains Mono"],
                "local_svg_assets": ["expand.svg", "close.svg", "external-link.svg"],
                "keyboard_delivery": True,
                "mouse_delivery": True,
                "sidecar_only_capture": True,
                "same_qml_source": "r6o/views/sidecar/qml/Sidecar.qml",
                "asset_hashes": asset_hashes,
            },
            "modes": modes,
        }
        result_path = platform_dir / "feasibility-result.json"
        result_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        return report
    finally:
        sidecar.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=tuple(EXPECTED_QPA), required=True)
    parser.add_argument("--evidence-dir", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--hold-seconds", type=float, default=0.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = qualify(args.platform, args.evidence_dir, args.hold_seconds)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
