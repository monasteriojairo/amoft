$ErrorActionPreference = "Stop"

$pythonVersions = @("3.13", "3.14")

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    Write-Host "Python launcher 'py' was not found."
    Write-Host "Install Python 3.13 or 3.14 for Windows, then rerun this script."
    exit 1
}

$selectedVersion = $null
foreach ($version in $pythonVersions) {
    try {
        py -$version --version *> $null
        if ($LASTEXITCODE -eq 0) {
            $selectedVersion = $version
            break
        }
    } catch {
    }
}

if (-not $selectedVersion) {
    Write-Host "No supported Python version found."
    Write-Host "Install Python 3.13 or 3.14, then rerun this script."
    exit 1
}

Write-Host "Rebuilding virtual environment with Python $selectedVersion..."

if (Test-Path ".venv") {
    Remove-Item ".venv" -Recurse -Force
}

py -$selectedVersion -m venv .venv

& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip
& ".\.venv\Scripts\pip.exe" install -r requirements-windows.txt

Write-Host ""
Write-Host "Setup complete."
Write-Host "Python version: $selectedVersion"
Write-Host "Run the GUI with:"
Write-Host "  .\.venv\Scripts\python.exe main.py"
