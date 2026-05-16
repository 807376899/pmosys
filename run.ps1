param(
    [int]$Port = 5000,
    [string]$Address = "0.0.0.0"
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$venvPython = Join-Path $root ".venv\Scripts\python.exe"
$bundledPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

function Get-BootstrapPython {
    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCmd) {
        return @($pythonCmd.Source)
    }

    $pyCmd = Get-Command py -ErrorAction SilentlyContinue
    if ($pyCmd) {
        foreach ($version in @("-3.12", "-3.11", "-3")) {
            try {
                & $pyCmd.Source $version -c "import sys; print(sys.version)" *> $null
                if ($LASTEXITCODE -eq 0) {
                    return @($pyCmd.Source, $version)
                }
            } catch {
            }
        }
    }

    if (Test-Path $bundledPython) {
        return @($bundledPython)
    }

    throw "Python was not found. Install Python 3.11+ or run this project inside Codex desktop."
}

function Ensure-Venv {
    if (Test-Path $venvPython) {
        return
    }

    Write-Host "[1/4] Creating .venv ..."
    $bootstrap = Get-BootstrapPython

    if ($bootstrap.Count -eq 2) {
        & $bootstrap[0] $bootstrap[1] -m venv .venv
    } else {
        & $bootstrap[0] -m venv .venv
    }
}

function Ensure-Dependencies {
    Write-Host "[2/4] Checking dependencies ..."
    & $venvPython -c "import streamlit, pandas, openpyxl" *> $null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Dependencies are ready."
        return
    }

    Write-Host "Installing requirements from requirements.txt ..."
    & $venvPython -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --default-timeout 1000
}

Ensure-Venv
Ensure-Dependencies

Write-Host "[3/4] Starting Streamlit ..."
Write-Host "[4/4] URL: http://127.0.0.1:$Port"

& $venvPython -m streamlit run app.py --server.port $Port --server.address $Address --server.headless true
