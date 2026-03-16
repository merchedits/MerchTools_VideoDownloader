$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$IsccCandidates = @(
    (Get-Command iscc -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue),
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe"
) | Where-Object { $_ -and (Test-Path $_) }

if (-not $IsccCandidates) {
    throw "Inno Setup Compiler (ISCC.exe) was not found. Install Inno Setup 6 first."
}

$IsccPath = $IsccCandidates[0]
& $IsccPath (Join-Path $ProjectRoot "installer.iss")

Write-Host ""
Write-Host "Installer created in:"
Write-Host "  $(Join-Path $ProjectRoot "installer-dist")"
