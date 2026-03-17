$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonExe = "python"
$MetadataJson = & $PythonExe -c "import json; from app_metadata import APP_TITLE, APP_VERSION, APP_PUBLISHER; print(json.dumps({'title': APP_TITLE, 'version': APP_VERSION, 'publisher': APP_PUBLISHER}))"
if ($LASTEXITCODE -ne 0 -or -not $MetadataJson) {
    throw "Could not load app metadata from app_metadata.py"
}
$AppMetadata = $MetadataJson | ConvertFrom-Json
$AppName = [string]$AppMetadata.title
$AppVersion = [string]$AppMetadata.version
$AppPublisher = [string]$AppMetadata.publisher
$AppExeName = "$AppName.exe"
$AppSourceDir = "dist\$AppName"
$LatestJsonPath = Join-Path $ProjectRoot "latest.json"
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

if (Test-Path $LatestJsonPath) {
    $LatestManifest = Get-Content $LatestJsonPath -Raw | ConvertFrom-Json
    if ([string]$LatestManifest.version -ne $AppVersion) {
        throw "latest.json version ($($LatestManifest.version)) does not match app version ($AppVersion)."
    }
}

& "$IsccPath" `
    "/DMyAppName=$AppName" `
    "/DMyAppVersion=$AppVersion" `
    "/DMyAppPublisher=$AppPublisher" `
    "/DMyAppExeName=$AppExeName" `
    "/DMyAppSourceDir=$AppSourceDir" `
    (Join-Path $ProjectRoot "installer.iss")
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup build failed with exit code $LASTEXITCODE"
}

Write-Host ""
Write-Host "Installer created in:"
Write-Host "  $(Join-Path $ProjectRoot "installer-dist")"
