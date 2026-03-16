$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPath = Join-Path $ProjectRoot ".build-venv"
$PythonExe = Join-Path $VenvPath "Scripts\python.exe"
$PyInstallerExe = Join-Path $VenvPath "Scripts\pyinstaller.exe"
$AppName = "MerchTools - Video Downloader"
$DistDir = Join-Path $ProjectRoot "dist\$AppName"
$BuildDir = Join-Path $ProjectRoot "build"
$FfmpegSource = $env:YTCUTTER_FFMPEG_PATH
$FfmpegTarget = Join-Path $ProjectRoot "ffmpeg.exe"

if (-not (Test-Path $VenvPath)) {
    python -m venv $VenvPath
}

& $PythonExe -m pip install --upgrade pip
& $PythonExe -m pip install -r (Join-Path $ProjectRoot "build_requirements.txt")

if ($FfmpegSource) {
    if (-not (Test-Path $FfmpegSource)) {
        throw "YTCUTTER_FFMPEG_PATH points to a file that does not exist: $FfmpegSource"
    }
    Copy-Item $FfmpegSource $FfmpegTarget -Force
    Write-Host "Bundled ffmpeg from $FfmpegSource"
}
else {
    Write-Warning "No ffmpeg binary supplied. Set YTCUTTER_FFMPEG_PATH to bundle ffmpeg.exe into the app."
}

if (Test-Path $BuildDir) {
    Remove-Item $BuildDir -Recurse -Force
}

if (Test-Path $DistDir) {
    Remove-Item $DistDir -Recurse -Force
}

$PyInstallerArgs = @(
    "--noconfirm"
    "--clean"
    "--windowed"
    "--name"
    $AppName
    "--collect-all"
    "PySide6"
    "--collect-all"
    "yt_dlp"
    "--hidden-import"
    "imageio_ffmpeg"
    "--add-data"
    "$ProjectRoot\README.md;."
)

if (Test-Path $FfmpegTarget) {
    $PyInstallerArgs += @(
        "--add-binary"
        "$FfmpegTarget;."
    )
}

$PyInstallerArgs += (Join-Path $ProjectRoot "app.py")

& $PyInstallerExe @PyInstallerArgs

Write-Host ""
Write-Host "Build complete:"
Write-Host "  $DistDir"
