param(
    [string]$Iscc = ""
)
$ErrorActionPreference = "Stop"
$taskClientRoot = $PSScriptRoot
$taskExecutable = Join-Path $taskClientRoot "dist\FocusLedger\FocusLedger.exe"
if (-not (Test-Path -LiteralPath $taskExecutable -PathType Leaf)) {
    throw "Missing $taskExecutable. Run build.ps1 first, or build the onedir layout."
}
if (-not (Test-Path -LiteralPath (Join-Path $taskClientRoot "dist\FocusLedger\_internal") -PathType Container)) {
    throw "The complete onedir build (including _internal) is required."
}
if (-not $Iscc) {
    $taskCompilerCommand = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($taskCompilerCommand) { $Iscc = $taskCompilerCommand.Source }
}
if (-not $Iscc) {
    $taskCandidates = @(
        (Join-Path (Split-Path -Parent $taskClientRoot) ".runtime\inno-setup\ISCC.exe")
    )
    foreach ($taskBase in @(${env:ProgramFiles(x86)}, $env:ProgramFiles, "$env:LOCALAPPDATA\Programs")) {
        if ($taskBase) {
            $taskCandidates += Join-Path $taskBase "Inno Setup 6\ISCC.exe"
            $taskCandidates += Join-Path $taskBase "Inno Setup 7\ISCC.exe"
        }
    }
    $Iscc = $taskCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
}
if (-not $Iscc -or -not (Test-Path -LiteralPath $Iscc -PathType Leaf)) {
    throw "Inno Setup is required (6.7.3+ recommended). Install it from https://jrsoftware.org/isdl.php or pass -Iscc <path to ISCC.exe>."
}
$taskVersionSource = Get-Content -LiteralPath (Join-Path $taskClientRoot "focus_agent\__init__.py") -Raw
if ($taskVersionSource -notmatch '__version__\s*=\s*"(\d+\.\d+\.\d+)"') {
    throw "Unable to read the client version."
}
$taskVersion = $Matches[1]
& $Iscc "/DAppVersion=$taskVersion" "/DClientRoot=$taskClientRoot" (Join-Path $taskClientRoot "installer\FocusLedger.iss")
if ($LASTEXITCODE -ne 0) { throw "Installer compilation failed" }
$taskInstaller = Join-Path $taskClientRoot "release\FocusLedger-Setup-windows-x64.exe"
$taskHash = (Get-FileHash -LiteralPath $taskInstaller -Algorithm SHA256).Hash.ToLowerInvariant()
$taskManifest = Join-Path $taskClientRoot "release\SHA256SUMS.txt"
$taskOtherHashes = if (Test-Path -LiteralPath $taskManifest) {
    @(Get-Content -LiteralPath $taskManifest | Where-Object { $_ -and $_ -notmatch '  FocusLedger-Setup-windows-x64\.exe$' })
} else { @() }
$taskHashes = @($taskOtherHashes) + "$taskHash  FocusLedger-Setup-windows-x64.exe"
[System.IO.File]::WriteAllText($taskManifest, ($taskHashes -join "`n") + "`n", [System.Text.UTF8Encoding]::new($false))
Write-Host "Ready: $taskInstaller"
