param(
    [string]$Python = "python",
    [switch]$SkipInstall,
    [ValidateSet("both", "onefile", "onedir")][string]$Layout = "both",
    [ValidateSet("installer", "portable", "all")][string]$Package = "installer",
    [string]$Iscc = ""
)
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
    $taskLayouts = if ($Package -eq "installer") { @("onedir") } elseif ($Layout -eq "both") { @("onedir", "onefile") } else { @($Layout) }
    if ($Package -eq "all" -and "onedir" -notin $taskLayouts) { $taskLayouts = @("onedir") + $taskLayouts }
    foreach ($taskLayout in $taskLayouts) {
        # Keep both builds' specifications and intermediate files separate.
        & $taskPythonCommand tools\build_executable.py --noconfirm --clean "--$taskLayout" --windowed --name FocusLedger --icon "$PSScriptRoot\build\icon\FocusLedger.ico" --paths . --specpath "build\$taskLayout" --workpath "build\$taskLayout\work" main.py
        if ($LASTEXITCODE -ne 0) { throw "$taskLayout build failed" }
    }
    if ("onedir" -in $taskLayouts) { Write-Host "Ready: $PSScriptRoot\dist\FocusLedger\FocusLedger.exe" }
    if ("onefile" -in $taskLayouts) { Write-Host "Ready: $PSScriptRoot\dist\FocusLedger.exe" }
    if ($Package -ne "portable") {
        & (Join-Path $PSScriptRoot "build-installer.ps1") -Iscc $Iscc
    }
} finally {
    Pop-Location
    $env:PATH = $taskOriginalPath
}
