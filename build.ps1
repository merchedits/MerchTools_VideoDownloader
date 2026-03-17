$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonExe = "python"
$MetadataJson = & $PythonExe -c "import json; from app_metadata import APP_TITLE, APP_VERSION; print(json.dumps({'title': APP_TITLE, 'version': APP_VERSION}))"
if ($LASTEXITCODE -ne 0 -or -not $MetadataJson) {
    throw "Could not load app metadata from app_metadata.py"
}
$AppMetadata = $MetadataJson | ConvertFrom-Json
$AppName = [string]$AppMetadata.title
$AppVersion = [string]$AppMetadata.version
$SpecPath = Join-Path $ProjectRoot "$AppName.spec"
$DistDir = Join-Path $ProjectRoot "dist\$AppName"
$BuildDir = Join-Path $ProjectRoot "build"
$BuildTempDir = Join-Path $env:USERPROFILE "MerchToolsBuildTemp"
$FfmpegSource = $env:YTCUTTER_FFMPEG_PATH
$FfmpegTarget = Join-Path $ProjectRoot "ffmpeg.exe"
$NodeSource = $env:YTDLP_NODE_PATH
$NodeTarget = Join-Path $ProjectRoot "node.exe"
$LatestJsonPath = Join-Path $ProjectRoot "latest.json"
$TwitchDownloaderPath = Join-Path $ProjectRoot "tools\TwitchDownloaderCLI\TwitchDownloaderCLI.exe"

New-Item -ItemType Directory -Force -Path $BuildTempDir | Out-Null
$env:TMP = $BuildTempDir
$env:TEMP = $BuildTempDir

& $PythonExe -m pip install --user --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "pip upgrade failed with exit code $LASTEXITCODE"
}

& $PythonExe -m pip install --user -r (Join-Path $ProjectRoot "build_requirements.txt")
if ($LASTEXITCODE -ne 0) {
    throw "Installing build requirements failed with exit code $LASTEXITCODE"
}

if (Test-Path $LatestJsonPath) {
    $LatestManifest = Get-Content $LatestJsonPath -Raw | ConvertFrom-Json
    if ([string]$LatestManifest.version -ne $AppVersion) {
        throw "latest.json version ($($LatestManifest.version)) does not match app version ($AppVersion)."
    }
}

if ($FfmpegSource) {
    if (-not (Test-Path $FfmpegSource)) {
        throw "YTCUTTER_FFMPEG_PATH points to a file that does not exist: $FfmpegSource"
    }
    Copy-Item $FfmpegSource $FfmpegTarget -Force
    Write-Host "Bundled ffmpeg from $FfmpegSource"
}
else {
    $ResolvedFfmpeg = & $PythonExe -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"
    if ($LASTEXITCODE -ne 0 -or -not $ResolvedFfmpeg -or -not (Test-Path $ResolvedFfmpeg)) {
        Write-Warning "Could not resolve ffmpeg automatically. Set YTCUTTER_FFMPEG_PATH to bundle ffmpeg.exe into the app."
    }
    else {
        Copy-Item $ResolvedFfmpeg $FfmpegTarget -Force
        Write-Host "Bundled ffmpeg from imageio-ffmpeg: $ResolvedFfmpeg"
    }
}

if ($NodeSource) {
    if (-not (Test-Path $NodeSource)) {
        throw "YTDLP_NODE_PATH points to a file that does not exist: $NodeSource"
    }
    Copy-Item $NodeSource $NodeTarget -Force
    Write-Host "Bundled node runtime from $NodeSource"
}
else {
    $ResolvedNode = (Get-Command node -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue)
    if ($ResolvedNode -and (Test-Path $ResolvedNode)) {
        Copy-Item $ResolvedNode $NodeTarget -Force
        Write-Host "Bundled node runtime from PATH: $ResolvedNode"
    }
    else {
        Write-Warning "Could not resolve node automatically. Set YTDLP_NODE_PATH to bundle node.exe into the app."
    }
}

if (-not (Test-Path $TwitchDownloaderPath)) {
    Write-Warning "TwitchDownloaderCLI.exe was not found at $TwitchDownloaderPath. Twitch VOD range downloads will fall back to the older yt-dlp path in this build."
}

if (Test-Path $BuildDir) {
    Remove-Item $BuildDir -Recurse -Force
}

if (Test-Path $DistDir) {
    Remove-Item $DistDir -Recurse -Force
}

if (-not (Test-Path $SpecPath)) {
    throw "PyInstaller spec file not found: $SpecPath"
}

try {
    & $PythonExe -m PyInstaller --noconfirm --clean $SpecPath
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller build failed with exit code $LASTEXITCODE"
    }
}
finally {
    if (Test-Path $FfmpegTarget) {
        Remove-Item $FfmpegTarget -Force
    }

    if (Test-Path $NodeTarget) {
        Remove-Item $NodeTarget -Force
    }
}

Write-Host ""
Write-Host "Build complete:"
Write-Host "  $DistDir"
