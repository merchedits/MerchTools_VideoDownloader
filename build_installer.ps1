$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PossiblePaths = @(
    (Get-Command iscc -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue),
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe"
)

$IsccPath = $null
foreach ($Candidate in $PossiblePaths) {
    if ($Candidate -and (Test-Path -LiteralPath $Candidate)) {
        $IsccPath = [string]$Candidate
        break
    }
}

if (-not $IsccPath) {
    throw "Inno Setup Compiler (ISCC.exe) was not found. Install Inno Setup 6 first."
}

& "$IsccPath" (Join-Path $ProjectRoot "installer.iss")

Write-Host ""
Write-Host "Installer created in:"
Write-Host "  $(Join-Path $ProjectRoot "installer-dist")"
