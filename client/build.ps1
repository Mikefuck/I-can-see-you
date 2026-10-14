param([string]$Python = "python", [switch]$SkipInstall)
$ErrorActionPreference = "Stop"
$taskOriginalPath = $env:PATH
$taskPythonCommand = (Get-Command $Python -ErrorAction Stop).Source
# Prevent unrelated tools on PATH (for example Poppler) from supplying incompatible DLLs.
$taskPythonDirectory = Split-Path -Parent $taskPythonCommand
$env:PATH = "$taskPythonDirectory;$env:SystemRoot\System32;$env:SystemRoot"
Push-Location $PSScriptRoot
try {
    if (-not $SkipInstall) {
        & $taskPythonCommand -m pip install -r requirements.txt "pyinstaller==6.22.3"
        if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed" }
    }
    & $taskPythonCommand tools\make_icon.py build\icon\FocusLedger.ico
    if ($LASTEXITCODE -ne 0) { throw "Icon generation failed" }
    & $taskPythonCommand -m PyInstaller --noconfirm --clean --onedir --windowed --name FocusLedger --icon build\icon\FocusLedger.ico --paths . main.py
    if ($LASTEXITCODE -ne 0) { throw "Build failed" }
    Write-Host "Ready: $PSScriptRoot\dist\FocusLedger\FocusLedger.exe"
} finally {
    Pop-Location
    $env:PATH = $taskOriginalPath
}
