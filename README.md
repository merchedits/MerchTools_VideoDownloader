# MerchTools - Video Downloader

Small desktop GUI for downloading the best quality video with audio and saving only the clip range you want.

This version uses `PySide6` for a more modern desktop UI.

## What it does

- Downloads the highest quality video and audio that the active backend can get
- Merges output into `mp4`
- Lets you save only a selected section, like `9:32` to `9:43`
- Lets you download the full video with a dedicated toggle
- Shows a simple log so you can see what `yt-dlp` is doing
- Checks on startup whether required tools are present and installs missing Python-based dependencies automatically
- Accepts YouTube links, Twitch VODs, Twitch clips, and other sites supported by `yt-dlp`
- Uses `TwitchDownloaderCLI` for Twitch VOD ranges and Twitch clips
- Can check a hosted update manifest and download a newer installer from inside the app

## Requirements

- Python 3.10+
- Internet connection the first time if dependencies are missing

## Notes

- The whole app is built using ChatGPT 5.4 and Codex for personal use only.
- YouTube and most non-Twitch sites use `yt-dlp`.
- Twitch VOD ranges and Twitch clips use bundled `TwitchDownloaderCLI`.
- Instagram Reels, TikTok, Twitter/X videos, and similar links can be attempted through the generic `yt-dlp` path when the site is supported.
- Use the `Download full video` toggle if you want the entire source instead of a clipped range.
- If `ffmpeg` is not installed system-wide, the app falls back to `imageio-ffmpeg` and uses its downloaded binary automatically.
- When the app is packaged, it skips pip-based setup and prefers bundled dependencies.
- Packaged builds bundle CA certificates so HTTPS downloads work more reliably on clean machines.
- Start and end time support `SS`, `MM:SS`, and `HH:MM:SS`.
- If you leave the filename empty, the video title is used automatically.
- Hardware acceleration is automatic where supported and falls back to CPU encoding when it is not available.
- The installer build bundles Python, yt-dlp, ffmpeg, `node.exe`, `TwitchDownloaderCLI`, and required Python dependencies.
- Installed builds default to `Documents\MerchTools\Video Downloader` for each user instead of writing inside Program Files.
- `update_config.json` is bundled into packaged builds, so set its `manifest_url` before making your release installer.
