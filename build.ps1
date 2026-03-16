$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonExe = "python"
$AppName = "MerchTools - Video Downloader"
$DistDir = Join-Path $ProjectRoot "dist\$AppName"
$BuildDir = Join-Path $ProjectRoot "build"
$BuildTempDir = Join-Path $env:USERPROFILE "MerchToolsBuildTemp"
$FfmpegSource = $env:YTCUTTER_FFMPEG_PATH
$FfmpegTarget = Join-Path $ProjectRoot "ffmpeg.exe"
$YtDlpTarget = Join-Path $ProjectRoot "yt-dlp.exe"

New-Item -ItemType Directory -Force -Path $BuildTempDir | Out-Null
$env:TMP = $BuildTempDir
$env:TEMP = $BuildTempDir

& $PythonExe -m pip install --user --upgrade pip
& $PythonExe -m pip install --user -r (Join-Path $ProjectRoot "build_requirements.txt")

$YtDlpCandidates = @(
    (& $PythonExe -c "import os, sysconfig; print(os.path.join(sysconfig.get_path('scripts'), 'yt-dlp.exe'))"),
    (& $PythonExe -c "import os, site; print(os.path.join(site.USER_BASE, 'Python314', 'Scripts', 'yt-dlp.exe'))"),
    (& $PythonExe -c "import os, site; print(os.path.join(site.USER_BASE, 'Scripts', 'yt-dlp.exe'))")
) | Where-Object { $_ }

$ResolvedYtDlp = $null
foreach ($Candidate in $YtDlpCandidates) {
    if (Test-Path $Candidate) {
        $ResolvedYtDlp = $Candidate
        break
    }
}

if ($ResolvedYtDlp) {
    Copy-Item $ResolvedYtDlp $YtDlpTarget -Force
    Write-Host "Bundled yt-dlp executable: $ResolvedYtDlp"
}
else {
    Write-Warning "Could not resolve yt-dlp.exe for bundling. The packaged app may not be able to launch yt-dlp correctly."
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
    "--icon"
    (Join-Path $ProjectRoot "assets\app-icon.ico")
    "--name"
    $AppName
    "--hidden-import"
    "yt_dlp"
    "--hidden-import"
    "imageio_ffmpeg"
    "--add-data"
    "$ProjectRoot\README.md;."
    "--add-data"
    "$ProjectRoot\assets\app-icon.png;assets"
    "--add-data"
    "$ProjectRoot\update_config.json;."
    "--add-data"
    "$ProjectRoot\latest.example.json;."
    "--exclude-module"
    "PySide6.Qt3DAnimation"
    "--exclude-module"
    "PySide6.Qt3DCore"
    "--exclude-module"
    "PySide6.Qt3DExtras"
    "--exclude-module"
    "PySide6.Qt3DInput"
    "--exclude-module"
    "PySide6.Qt3DLogic"
    "--exclude-module"
    "PySide6.Qt3DRender"
    "--exclude-module"
    "PySide6.QtAxContainer"
    "--exclude-module"
    "PySide6.QtBluetooth"
    "--exclude-module"
    "PySide6.QtCharts"
    "--exclude-module"
    "PySide6.QtDataVisualization"
    "--exclude-module"
    "PySide6.QtDesigner"
    "--exclude-module"
    "PySide6.QtGraphs"
    "--exclude-module"
    "PySide6.QtHelp"
    "--exclude-module"
    "PySide6.QtHttpServer"
    "--exclude-module"
    "PySide6.QtLocation"
    "--exclude-module"
    "PySide6.QtMultimedia"
    "--exclude-module"
    "PySide6.QtMultimediaWidgets"
    "--exclude-module"
    "PySide6.QtNetworkAuth"
    "--exclude-module"
    "PySide6.QtNfc"
    "--exclude-module"
    "PySide6.QtOpenGL"
    "--exclude-module"
    "PySide6.QtOpenGLWidgets"
    "--exclude-module"
    "PySide6.QtPdf"
    "--exclude-module"
    "PySide6.QtPdfWidgets"
    "--exclude-module"
    "PySide6.QtPositioning"
    "--exclude-module"
    "PySide6.QtPrintSupport"
    "--exclude-module"
    "PySide6.QtQml"
    "--exclude-module"
    "PySide6.QtQuick"
    "--exclude-module"
    "PySide6.QtQuick3D"
    "--exclude-module"
    "PySide6.QtQuickControls2"
    "--exclude-module"
    "PySide6.QtRemoteObjects"
    "--exclude-module"
    "PySide6.QtScxml"
    "--exclude-module"
    "PySide6.QtSensors"
    "--exclude-module"
    "PySide6.QtSerialBus"
    "--exclude-module"
    "PySide6.QtSerialPort"
    "--exclude-module"
    "PySide6.QtSpatialAudio"
    "--exclude-module"
    "PySide6.QtSql"
    "--exclude-module"
    "PySide6.QtStateMachine"
    "--exclude-module"
    "PySide6.QtSvg"
    "--exclude-module"
    "PySide6.QtSvgWidgets"
    "--exclude-module"
    "PySide6.QtTest"
    "--exclude-module"
    "PySide6.QtTextToSpeech"
    "--exclude-module"
    "PySide6.QtUiTools"
    "--exclude-module"
    "PySide6.QtWebChannel"
    "--exclude-module"
    "PySide6.QtWebEngineCore"
    "--exclude-module"
    "PySide6.QtWebEngineQuick"
    "--exclude-module"
    "PySide6.QtWebEngineWidgets"
    "--exclude-module"
    "PySide6.QtWebSockets"
    "--exclude-module"
    "PySide6.QtWebView"
    "--exclude-module"
    "PySide6.QtXml"
)

if (Test-Path $FfmpegTarget) {
    $PyInstallerArgs += @(
        "--add-binary"
        "$FfmpegTarget;."
    )
}

if (Test-Path $YtDlpTarget) {
    $PyInstallerArgs += @(
        "--add-binary"
        "$YtDlpTarget;."
    )
}

$PyInstallerArgs += (Join-Path $ProjectRoot "app.py")

& $PythonExe -m PyInstaller @PyInstallerArgs

if (Test-Path $FfmpegTarget) {
    Remove-Item $FfmpegTarget -Force
}

if (Test-Path $YtDlpTarget) {
    Remove-Item $YtDlpTarget -Force
}

Write-Host ""
Write-Host "Build complete:"
Write-Host "  $DistDir"
