param(
    [int]$Port = 8000,
    [string]$Address = "127.0.0.1",
    [switch]$NoReload
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$venvPython = Join-Path $root ".venv\Scripts\python.exe"

function Test-Python311OrNewer {
    param(
        [string]$Executable,
        [string[]]$Arguments = @()
    )

    if (-not (Test-Path $Executable)) {
        return $false
    }

    try {
        & $Executable @Arguments -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" *> $null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

function New-ProjectVenv {
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) {
        try {
            & $launcher.Source -3.11 -m venv .venv
            if ($LASTEXITCODE -eq 0) {
                return
            }
        } catch {
        }
    }

    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand -and $pythonCommand.Source -notlike "*WindowsApps*") {
        if (Test-Python311OrNewer -Executable $pythonCommand.Source) {
            & $pythonCommand.Source -m venv .venv
            if ($LASTEXITCODE -eq 0) {
                return
            }
        }
    }

    $localPythonRoot = Join-Path $env:LOCALAPPDATA "Programs\Python"
    $localPython = Get-ChildItem -Path (Join-Path $localPythonRoot "Python*\python.exe") -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending |
        Select-Object -First 1
    if ($localPython -and (Test-Python311OrNewer -Executable $localPython.FullName)) {
        & $localPython.FullName -m venv .venv
        if ($LASTEXITCODE -eq 0) {
            return
        }
    }

    throw 'Python 3.11+ was not found. Install it with: winget install --id Python.Python.3.11 --exact. Then open a new PowerShell window and run .\run.ps1 again.'
}

if (-not (Test-Path $venvPython)) {
    Write-Host "[1/3] Creating local Python virtual environment..."
    New-ProjectVenv
}

Write-Host "[2/3] Checking Python dependencies..."
& $venvPython -c "import fastapi, uvicorn, pandas, openpyxl" *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing dependencies from requirements.txt..."
    & $venvPython -m pip install -r requirements.txt
}

Write-Host "[3/3] Starting PMO API at http://${Address}:$Port"
$uvicornArgs = @("-m", "uvicorn", "backend.app.main:app", "--host", $Address, "--port", $Port)
if (-not $NoReload) {
    $uvicornArgs += "--reload"
}
& $venvPython @uvicornArgs
