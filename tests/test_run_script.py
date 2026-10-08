"""Exercise startup control flow without installing packages or opening a database."""

from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which("powershell") is None, reason="Windows PowerShell required")
@pytest.mark.parametrize("install_exit, import_exit", [(0, 0), (1, 0), (0, 1)])
def test_dependencies_are_verified_before_startup(tmp_path, install_exit, import_exit):
    trace = tmp_path / "calls.txt"
    interpreter = tmp_path / "python.cmd"
    interpreter.write_text(
        '@echo off\n'
        f'echo %* >> "{trace}"\n'
        f'if "%~1 %~2"=="-m pip" exit /b {install_exit}\n'
        f'if "%~1"=="-c" exit /b {import_exit}\n'
        'exit /b 0\n',
        encoding="utf-8",
    )
    source = (Path(__file__).resolve().parents[1] / "run.ps1").read_text(encoding="utf-8")
    # Replace only the interpreter path; execute the actual startup branches.
    source = source.replace(
        '$venvPython = Join-Path $root ".venv\\Scripts\\python.exe"',
        "$venvPython = '" + str(interpreter).replace("'", "''") + "'",
    )
    script = tmp_path / "run.ps1"
    script.write_text(source, encoding="utf-8")
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-NoReload"],
        capture_output=True, timeout=30,
    )
    calls = trace.read_text().splitlines()
    assert any("-m pip install -r requirements.txt" in call for call in calls)
    imported = any("backend.app.main" in call for call in calls)
    started = any("-m uvicorn" in call for call in calls)
    succeeds = install_exit == 0 and import_exit == 0
    assert imported == (install_exit == 0)
    assert started == succeeds
    assert (result.returncode == 0) == succeeds
