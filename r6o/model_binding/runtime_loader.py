from __future__ import annotations

"""Qualified, bytecode-suppressed loader for the frozen R6S runtime."""

import importlib
import subprocess
import sys
from pathlib import Path
from types import ModuleType

R6S_COMMIT = "60d982f3328b45a351879d67dc4bb525172b65fd"
R6S_TREE = "b7689fbe8b9c9838438cbba6f6e0e5c1ce5b5ed6"
_PROVENANCE_PREFIXES = ("host", "runtime", "controller", "observation")
_EAGER_MODULES = (
    "host.app",
    "runtime.session_engine",
    "runtime.workspace",
    "controller.mechanical_controller",
)


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root)
    except ValueError:
        return False
    return True


def _module_paths(module: ModuleType) -> list[Path]:
    paths: list[Path] = []
    filename = getattr(module, "__file__", None)
    if filename:
        paths.append(Path(filename))
    package_paths = getattr(module, "__path__", None)
    if package_paths:
        paths.extend(Path(item) for item in package_paths)
    return paths


class FrozenRuntimeLoader:
    def __init__(self, baseline_repo: str | Path) -> None:
        self.baseline_repo = Path(baseline_repo).resolve()

    def validate_identity(self) -> None:
        if not (self.baseline_repo / "host" / "app.py").is_file():
            raise RuntimeError(f"frozen baseline host/app.py not found: {self.baseline_repo}")
        try:
            commit = subprocess.run(
                ["git", "-C", str(self.baseline_repo), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            tree = subprocess.run(
                ["git", "-C", str(self.baseline_repo), "rev-parse", "HEAD^{tree}"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        except (OSError, subprocess.CalledProcessError) as exc:
            raise RuntimeError("unable to verify frozen baseline git identity") from exc
        if (commit, tree) != (R6S_COMMIT, R6S_TREE):
            raise RuntimeError(
                f"frozen baseline identity mismatch: commit={commit}, tree={tree}"
            )

    def _reject_collisions(self) -> None:
        for name, module in tuple(sys.modules.items()):
            if not any(name == prefix or name.startswith(prefix + ".") for prefix in _PROVENANCE_PREFIXES):
                continue
            paths = _module_paths(module)
            if not paths or any(not _inside(path, self.baseline_repo) for path in paths):
                raise RuntimeError(f"module provenance collision for {name!r}")

    def load_host_class(self) -> type:
        self.validate_identity()
        self._reject_collisions()
        repo_text = str(self.baseline_repo)
        old_path = list(sys.path)
        old_dont_write = sys.dont_write_bytecode
        try:
            sys.path[:] = [repo_text, *(entry for entry in sys.path if entry != repo_text)]
            sys.dont_write_bytecode = True
            importlib.invalidate_caches()
            for name in _EAGER_MODULES:
                importlib.import_module(name)
            self._reject_collisions()
            module = sys.modules["host.app"]
            if not _inside(Path(module.__file__), self.baseline_repo):
                raise RuntimeError("host.app did not resolve inside the configured baseline")
            return module.PDLtHost
        finally:
            sys.path[:] = old_path
            sys.dont_write_bytecode = old_dont_write
