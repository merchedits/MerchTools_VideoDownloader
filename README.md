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

## Notes

- The whole app is built using ChatGPT 5.4 and Codex for personal use only.
- The app uses `yt-dlp --download-sections` to cut the clip you want.
- Use the `Download full video` toggle if you want the entire source instead of a clipped range.
- If `ffmpeg` is not installed system-wide, the app falls back to `imageio-ffmpeg` and uses its downloaded binary automatically.
- When the app is packaged, it skips pip-based setup and prefers bundled dependencies.
- Start and end time support `SS`, `MM:SS`, and `HH:MM:SS`.
- If you leave the filename empty, the video title is used automatically.
- The installer build bundles Python, yt-dlp, ffmpeg, and required Python dependencies.
- Installed builds default to `Documents\MerchTools\Video Downloader` for each user instead of writing inside Program Files.
- `update_config.json` is bundled into packaged builds, so set its `manifest_url` before making your release installer.
