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

### Build the Windows installer

Install Inno Setup 6, then run:

```powershell
.\build_installer.ps1
```

That creates a standard Windows installer in `installer-dist`.

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
