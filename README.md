# MerchTools - Video Downloader

Small desktop GUI for downloading the best quality YouTube or Twitch video with audio and saving only the clip range you want.

This version uses `PySide6` for a more modern desktop UI.

## What it does

- Downloads the highest quality video and audio that `yt-dlp` can get
- Merges output into `mp4`
- Lets you save only a selected section, like `9:32` to `9:43`
- Lets you download the full video with a dedicated toggle
- Shows a simple log so you can see what `yt-dlp` is doing
- Checks on startup whether required tools are present and installs missing Python-based dependencies automatically
- Accepts YouTube links, Twitch VODs, and Twitch clips
- Can check a hosted update manifest and download a newer installer from inside the app

## Requirements

- Python 3.10+
- Internet connection the first time if dependencies are missing

## Share It As A Standalone App

You can package this as a normal Windows app so the other person does not need to install Python.

### Build the standalone app

```powershell
.\build.ps1
```

This creates a bundled app in `dist\MerchTools - Video Downloader`.

If you already have an `ffmpeg.exe` you want to ship inside the app, set:

```powershell
$env:YTCUTTER_FFMPEG_PATH="C:\path\to\ffmpeg.exe"
.\build.ps1
```

That copies `ffmpeg.exe` into the packaged app so the recipient does not need a separate ffmpeg install.

If you do not set `YTCUTTER_FFMPEG_PATH`, the build script will try to bundle ffmpeg automatically from `imageio-ffmpeg`.

### Build the Windows installer

Install Inno Setup 6, then run:

```powershell
.\build_installer.ps1
```

That creates a standard Windows installer in `installer-dist`.

## Installer Output

The finished Windows installer is created as:

```text
installer-dist\MerchToolsVideoDownloaderSetup.exe
```

## App Updates

The app now supports a simple installer-based update flow.

How it works:

- The app reads `update_config.json`
- That file points to a hosted `latest.json` manifest
- On startup or when `Check Updates` is clicked, the app compares the hosted version to its current version
- If a newer version exists, it can download the new installer and launch it

### 1. Configure the manifest URL

Edit `update_config.json` before building:

```json
{
  "manifest_url": "https://your-host.example.com/latest.json",
  "check_on_startup": true
}
```

### 2. Host a manifest file

Use `latest.example.json` as the template:

```json
{
  "version": "1.0.1",
  "installer_url": "https://your-host.example.com/MerchToolsVideoDownloaderSetup.exe",
  "filename": "MerchToolsVideoDownloaderSetup.exe",
  "notes": "Fixed installer launch issues and improved package size."
}
```

### 3. Upload the new installer

Whenever you ship a new version:

- build the new installer
- upload `MerchToolsVideoDownloaderSetup.exe`
- update the hosted `latest.json` with the new version and URL

This works well with any static HTTPS host you control, including private-ish shared links or simple file hosting.

## Install

```powershell
pip install -r requirements.txt
```

If `yt-dlp` or `ffmpeg` support files are missing, the app will try to install them automatically when it starts.

## Run

```powershell
python app.py
```

## Notes

- The app uses `yt-dlp --download-sections` to cut the clip you want.
- Use the `Download full video` toggle if you want the entire source instead of a clipped range.
- If `ffmpeg` is not installed system-wide, the app falls back to `imageio-ffmpeg` and uses its downloaded binary automatically.
- When the app is packaged, it skips pip-based setup and prefers bundled dependencies.
- Start and end time support `SS`, `MM:SS`, and `HH:MM:SS`.
- If you leave the filename empty, the video title is used automatically.
- The installer build bundles Python, yt-dlp, ffmpeg, and required Python dependencies.
- Installed builds default to `Documents\MerchTools\Video Downloader` for each user instead of writing inside Program Files.
- `update_config.json` is bundled into packaged builds, so set its `manifest_url` before making your release installer.
