"""Pre-commit hook runner that locates the project's virtualenv mypy.

When VS Code (or any non-terminal process) runs ``git commit``, the system
``python`` is the global interpreter — not the Poetry virtualenv. This script
detects local virtual environments and delegates to the Python that actually
has *mypy* (and the project dependencies) installed.
"""

import os
import subprocess
import sys
from pathlib import Path


def _find_venv_python() -> Path | None:
    """Search for a local virtualenv Python that has mypy installed."""
    repo_root = Path(__file__).resolve().parent.parent
    candidates: list[Path] = []

    for venv_name in ("virtual_env", ".venv", "venv", ".env"):
        scripts = repo_root / venv_name / "Scripts"
        if scripts.exists():
            candidates.append(scripts / "python.exe")

    for cand in candidates:
        if cand.exists():
            try:
                subprocess.run(
                    [str(cand), "-c", "import mypy"],
                    check=True,
                    capture_output=True,
                )
                return cand
            except subprocess.CalledProcessError:
                continue

    return None


def _find_poetry_exe() -> Path | None:
    """Locate the Poetry binary in standard installation directories."""
    candidates: list[Path] = []
    appdata = os.environ.get("APPDATA")
    localappdata = os.environ.get("LOCALAPPDATA")
    home = Path.home()

    if appdata:
        candidates.append(Path(appdata) / "Python" / "Scripts" / "poetry.exe")
    if localappdata:
        candidates.append(
            Path(localappdata) / "Programs" / "Python" / "Python310" / "Scripts" / "poetry.exe"
        )
    candidates.append(home / ".poetry" / "bin" / "poetry")

    for cand in candidates:
        if cand.exists():
            return cand
    return None


def _find_poetry_venv_from_cache(project_name: str) -> Path | None:
    """Scan the Poetry cache for a virtualenv belonging to *project_name*."""
    localappdata = os.environ.get("LOCALAPPDATA")
    if not localappdata:
        return None

    cache_dir = Path(localappdata) / "pypoetry" / "Cache" / "virtualenvs"
    if not cache_dir.exists():
        return None

    for entry in cache_dir.iterdir():
        if entry.is_dir() and entry.name.startswith(project_name):
            python = entry / "Scripts" / "python.exe"
            if python.exists():
                try:
                    subprocess.run(
                        [str(python), "-c", "import mypy"],
                        check=True,
                        capture_output=True,
                    )
                    return python
                except subprocess.CalledProcessError:
                    continue
    return None


def _read_project_name() -> str | None:
    """Read ``tool.poetry.name`` from ``pyproject.toml``."""
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    if not pyproject.exists():
        return None
    try:
        with pyproject.open("rb") as fh:
            import tomllib

            data = tomllib.load(fh)
            return data.get("tool", {}).get("poetry", {}).get("name")
    except Exception:
        return None


def _find_poetry_python() -> Path | None:
    """Resolve the Poetry virtualenv, even when ``poetry`` is not in PATH."""
    poetry = _find_poetry_exe()
    if poetry:
        try:
            result = subprocess.run(
                [str(poetry), "env", "info", "--path"],
                capture_output=True,
                text=True,
                check=True,
            )
            venv_path = Path(result.stdout.strip())
            python = venv_path / "Scripts" / "python.exe"
            if python.exists():
                try:
                    subprocess.run(
                        [str(python), "-c", "import mypy"],
                        check=True,
                        capture_output=True,
                    )
                    return python
                except subprocess.CalledProcessError:
                    pass
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

    project_name = _read_project_name()
    if project_name:
        python = _find_poetry_venv_from_cache(project_name)
        if python:
            return python

    return None


def main() -> None:
    python: Path | None = None

    if sys.platform == "win32":
        python = _find_venv_python()

    if python is None:
        python = _find_poetry_python()

    if python is None:
        print(
            "ERROR: Could not find a virtualenv Python with mypy installed.\n"
            "Make sure your Poetry environment is active or that 'poetry' is in PATH.",
            file=sys.stderr,
        )
        sys.exit(1)

    cmd = [str(python), "-m", "mypy", "app/", "tests/", "alembic/"]
    sys.exit(subprocess.run(cmd).returncode)


if __name__ == "__main__":
    main()
