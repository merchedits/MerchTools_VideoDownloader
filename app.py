import importlib
import json
import math
import os
import random
import re
import shutil
import struct
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import wave
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

try:
    import certifi
except ImportError:
    try:
        from pip._vendor import certifi  # type: ignore[no-redef]
    except ImportError:
        certifi = None

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError, download_range_func
from yt_dlp.downloader import external as yt_dlp_external
from PySide6.QtCore import QObject, QPoint, QThread, Qt, Signal, QTimer
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap, QPolygon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app_metadata import APP_TITLE, APP_VERSION

try:
    import winsound
except ImportError:
    winsound = None

DEFAULT_OUTPUT_DIR = Path.home() / "Documents" / "MerchTools" / "Video Downloader"
UPDATE_CONFIG_FILENAME = "update_config.json"
SETTINGS_FILENAME = "user_settings.json"
NODE_RUNTIME_FILENAME = "node.exe"
DEFAULT_DOWNLOAD_FORMAT = "bestvideo*+bestaudio/best"
REQUIRED_PYTHON_PACKAGES = [
    ("yt_dlp", "yt-dlp"),
    ("imageio_ffmpeg", "imageio-ffmpeg"),
]
HARDWARE_ENCODER_CACHE: dict[str, str | None] = {}


def format_seconds(total_seconds: float | int | None) -> str:
    if total_seconds is None:
        return "Unknown"

    seconds = int(total_seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def parse_timecode(value: str) -> int:
    text = value.strip()
    if not text:
        raise ValueError("Time value is empty.")

    parts = text.split(":")
    if not all(part.isdigit() for part in parts):
        raise ValueError("Use only numbers in the time fields, like 9:32 or 00:09:32.")

    if len(parts) == 1:
        return int(parts[0])
    if len(parts) == 2:
        minutes, seconds = (int(part) for part in parts)
        if seconds >= 60:
            raise ValueError("Seconds must be less than 60.")
        return minutes * 60 + seconds
    if len(parts) == 3:
        hours, minutes, seconds = (int(part) for part in parts)
        if minutes >= 60 or seconds >= 60:
            raise ValueError("Minutes and seconds must be less than 60.")
        return hours * 3600 + minutes * 60 + seconds

    raise ValueError("Time format must look like SS, MM:SS, or HH:MM:SS.")


def parse_clock_value(value: str) -> float:
    hours_text, minutes_text, seconds_text = value.split(":")
    return (int(hours_text) * 3600) + (int(minutes_text) * 60) + float(seconds_text)


def normalize_video_url(raw_url: str) -> str:
    text = raw_url.strip().strip('"').strip("'")
    if not text:
        return ""

    parsed = urlparse(text)
    host = parsed.netloc.lower().replace("www.", "")
    path = parsed.path.rstrip("/")
    query = parse_qs(parsed.query)

    if host in {"youtube.com", "m.youtube.com"}:
        if path == "/watch":
            video_id = query.get("v", [""])[0]
            if video_id:
                return f"https://www.youtube.com/watch?v={video_id}"
        return f"https://www.youtube.com{path}" if path else text

    if host == "youtu.be":
        if path:
            return f"https://youtu.be{path}"
        return text

    if host in {"twitch.tv", "m.twitch.tv"}:
        if path.startswith("/videos/"):
            video_id = path.split("/videos/", 1)[1].split("/")[0]
            if video_id:
                return f"https://www.twitch.tv/videos/{video_id}"
        if "/clip/" in path:
            return f"https://www.twitch.tv{path}"
        return f"https://www.twitch.tv{path}" if path else text

    if host == "clips.twitch.tv":
        return f"https://clips.twitch.tv{path}" if path else text

    return text


def application_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def bundled_file_candidates(filename: str) -> list[Path]:
    base_dir = application_dir()
    return [
        base_dir / filename,
        base_dir / "_internal" / filename,
        Path(__file__).resolve().parent / filename,
    ]


def bundled_executable_path(filename: str) -> str | None:
    for candidate in bundled_file_candidates(filename):
        if candidate.exists():
            return str(candidate)
    return None


def resolve_js_runtime_executable() -> str | None:
    bundled_runtime = bundled_executable_path(NODE_RUNTIME_FILENAME)
    if bundled_runtime:
        return bundled_runtime
    return shutil.which("node")


def yt_dlp_js_runtime_options() -> dict:
    node_path = resolve_js_runtime_executable()
    if not node_path:
        return {}
    return {
        "js_runtimes": {"node": {"path": node_path}},
        "remote_components": ["ejs:github"],
        "extractor_args": {
            "youtube": {
                "player_client": ["web", "android_vr"],
            }
        },
    }


def user_data_dir() -> Path:
    appdata = os.getenv("APPDATA")
    if appdata:
        return Path(appdata) / "MerchTools" / "Video Downloader"
    return Path.home() / "AppData" / "Roaming" / "MerchTools" / "Video Downloader"


def settings_path() -> Path:
    return user_data_dir() / SETTINGS_FILENAME


def load_json_file(filename: str) -> dict:
    for candidate in bundled_file_candidates(filename):
        if candidate.exists():
            try:
                return json.loads(candidate.read_text(encoding="utf-8"))
            except json.JSONDecodeError as error:
                raise RuntimeError(f"{filename} contains invalid JSON: {error}") from error
    return {}


def load_update_config() -> dict:
    config = {
        "manifest_url": "",
        "check_on_startup": True,
    }
    try:
        loaded = load_json_file(UPDATE_CONFIG_FILENAME)
    except RuntimeError:
        return config
    if isinstance(loaded, dict):
        config.update(loaded)
    return config


def load_user_settings() -> dict:
    path = settings_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_user_settings(data: dict) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def urlopen_options() -> dict:
    if certifi is None:
        return {}
    return {"context": ssl.create_default_context(cafile=certifi.where())}


def configure_ssl_environment() -> None:
    if certifi is None:
        return

    try:
        ca_bundle = certifi.where()
    except Exception:  # noqa: BLE001
        return

    if not ca_bundle or not Path(ca_bundle).exists():
        return

    # Make bundled CA certificates visible to yt-dlp and its HTTP backends.
    os.environ["SSL_CERT_FILE"] = ca_bundle
    os.environ["REQUESTS_CA_BUNDLE"] = ca_bundle
    os.environ["CURL_CA_BUNDLE"] = ca_bundle


def subprocess_window_options() -> dict:
    if os.name != "nt":
        return {}

    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return {
        "creationflags": subprocess.CREATE_NO_WINDOW,
        "startupinfo": startupinfo,
    }


def detect_windows_gpu_names() -> list[str]:
    if os.name != "nt":
        return []
    command = [
        "powershell",
        "-NoProfile",
        "-Command",
        "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name",
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=6,
            **subprocess_window_options(),
        )
    except Exception:  # noqa: BLE001
        return []
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def detect_hardware_encoder(ffmpeg_path: str) -> str | None:
    cached = HARDWARE_ENCODER_CACHE.get(ffmpeg_path)
    if ffmpeg_path in HARDWARE_ENCODER_CACHE:
        return cached

    try:
        result = subprocess.run(
            [ffmpeg_path, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=8,
            **subprocess_window_options(),
        )
    except Exception:  # noqa: BLE001
        HARDWARE_ENCODER_CACHE[ffmpeg_path] = None
        return None

    encoders_output = f"{result.stdout}\n{result.stderr}".lower()
    gpu_names = " ".join(detect_windows_gpu_names()).lower()

    encoder: str | None = None
    if "nvidia" in gpu_names or "geforce" in gpu_names or "rtx" in gpu_names or "gtx" in gpu_names:
        if "h264_nvenc" in encoders_output:
            encoder = "h264_nvenc"
    elif "amd" in gpu_names or "radeon" in gpu_names:
        if "h264_amf" in encoders_output:
            encoder = "h264_amf"
    elif "intel" in gpu_names:
        if "h264_qsv" in encoders_output:
            encoder = "h264_qsv"

    if encoder is None:
        if "h264_nvenc" in encoders_output:
            encoder = "h264_nvenc"
        elif "h264_amf" in encoders_output:
            encoder = "h264_amf"
        elif "h264_qsv" in encoders_output:
            encoder = "h264_qsv"

    HARDWARE_ENCODER_CACHE[ffmpeg_path] = encoder
    return encoder


def version_key(value: str) -> tuple[int, ...]:
    parts = [int(part) for part in re.findall(r"\d+", value)]
    return tuple(parts or [0])


def is_newer_version(current_version: str, candidate_version: str) -> bool:
    return version_key(candidate_version) > version_key(current_version)


class WorkerSignals(QObject):
    log = Signal(str)
    status = Signal(str)
    finished = Signal(object)
    error = Signal(str)
    progress = Signal(int)


class BaseWorker(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.signals = WorkerSignals()

    def log(self, message: str) -> None:
        self.signals.log.emit(message)

    def set_status(self, value: str) -> None:
        self.signals.status.emit(value)

    def emit_error(self, message: str) -> None:
        self.signals.error.emit(message)


class YtDlpWorkerLogger:
    def __init__(self, worker: BaseWorker) -> None:
        self.worker = worker

    def debug(self, message: str) -> None:
        if message and not message.startswith("[debug] "):
            self.worker.log(message)

    def info(self, message: str) -> None:
        if message:
            self.worker.log(message)

    def warning(self, message: str) -> None:
        if message:
            self.worker.log(message)

    def error(self, message: str) -> None:
        if message:
            self.worker.log(message)


class ProgressButton(QPushButton):
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._progress = 0
        self._show_progress = False
        self._hover_cancel = False
        self._hover_primary = False
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_progress_state(self, active: bool, value: int = 0) -> None:
        self._show_progress = active
        self._progress = max(0, min(100, value))
        if not active:
            self._hover_cancel = False
        self.update()

    def enterEvent(self, event) -> None:  # type: ignore[override]
        if self._show_progress:
            self._hover_cancel = True
        else:
            self._hover_primary = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        if self._hover_cancel:
            self._hover_cancel = False
        if self._hover_primary:
            self._hover_primary = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect().adjusted(0, 0, -1, -1)
        radius = 12
        if self.isEnabled() and not self._show_progress:
            bg = QColor("#ff9a55") if not self._hover_primary else QColor("#ffae73")
            border = QColor("#ffb883") if self._hover_primary else QColor("#ff9a55")
        else:
            bg = QColor("#1b1f23") if self.isEnabled() else QColor("#171a1d")
            border = QColor("#2a2e33") if self.isEnabled() else QColor("#22262a")
        text_color = QColor("#efe8dd") if self.isEnabled() else QColor("#7d766d")
        progress_active = self._show_progress and not self._hover_cancel

        painter.setPen(QPen(border, 1))
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, radius, radius)

        if self._show_progress and not self._hover_cancel:
            text_color = QColor("#1a1613")
        if self._hover_cancel and self._show_progress:
            painter.setPen(QPen(QColor("#cb4b4b"), 1))
            painter.setBrush(QColor("#7a2020"))
            painter.drawRoundedRect(rect, radius, radius)
            text_color = QColor("#fff2f2")
        elif self._show_progress:
            border = QColor("#ff9a55")
            text_color = QColor("#efe8dd")
        if progress_active and self._progress > 0:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#ff9a55"))
            painter.setClipRect(rect)
            progress_rect = rect.adjusted(0, 0, -(rect.width() - int((rect.width() * self._progress) / 100)), 0)
            painter.drawRoundedRect(progress_rect, radius, radius)
            painter.setClipping(False)
            painter.setPen(QPen(border, 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect, radius, radius)

        painter.setPen(text_color)
        text = self.text()
        if self._hover_cancel and self._show_progress:
            text = "Cancel Download"
        elif self._show_progress:
            text = f"Downloading... {self._progress}%"
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)


class DependencyWorker(BaseWorker):
    def run(self) -> None:
        try:
            self.set_status("Checking dependencies...")
            self.log("Checking required dependencies...")
            if self.is_frozen():
                self.log("Running as a packaged app. Skipping pip-based setup.")
            else:
                self.ensure_pip_available()
                for module_name, package_name in REQUIRED_PYTHON_PACKAGES:
                    if self.module_available(module_name):
                        self.log(f"{package_name} is already installed.")
                        continue
                    self.install_package(package_name)

            ffmpeg_path = self.resolve_ffmpeg_executable()
            if not ffmpeg_path:
                raise RuntimeError("ffmpeg could not be prepared.")

            self.log(f"Using ffmpeg at: {ffmpeg_path}")
            js_runtime_path = resolve_js_runtime_executable()
            if js_runtime_path:
                self.log(f"Using JavaScript runtime at: {js_runtime_path}")
            else:
                self.log("No JavaScript runtime found. Some YouTube formats may be unavailable until node is installed.")
            self.log("Dependency check complete.")
            self.signals.finished.emit({"ffmpeg_path": ffmpeg_path})
        except Exception as error:  # noqa: BLE001
            self.emit_error(
                "Automatic setup failed.\n\n"
                f"{error}\n\n"
                "The app could not prepare its required tools automatically."
            )

    def ensure_pip_available(self) -> None:
        try:
            import pip  # noqa: F401
            self.log("pip is available.")
        except ImportError:
            self.log("pip is missing. Bootstrapping it with ensurepip...")
            result = subprocess.run(
                [sys.executable, "-m", "ensurepip", "--upgrade"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                **subprocess_window_options(),
            )
            if result.stdout.strip():
                self.log(result.stdout.strip())
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "ensurepip failed.")

    def install_package(self, package_name: str) -> None:
        self.log(f"Installing missing package: {package_name}")
        process = subprocess.Popen(
            [sys.executable, "-m", "pip", "install", package_name],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            **subprocess_window_options(),
        )

        assert process.stdout is not None
        for line in process.stdout:
            clean_line = line.rstrip()
            if clean_line:
                self.log(clean_line)

        exit_code = process.wait()
        if exit_code != 0:
            raise RuntimeError(f"Installing {package_name} failed with exit code {exit_code}.")

    def module_available(self, module_name: str) -> bool:
        try:
            importlib.import_module(module_name)
        except ImportError:
            return False
        return True

    def resolve_ffmpeg_executable(self) -> str | None:
        path_ffmpeg = shutil.which("ffmpeg")
        if path_ffmpeg:
            return path_ffmpeg

        if self.is_frozen():
            packaged_dir = Path(sys.executable).resolve().parent
            candidates = [
                packaged_dir / "ffmpeg.exe",
                packaged_dir / "_internal" / "ffmpeg.exe",
            ]
            for candidate in candidates:
                if candidate.exists():
                    return str(candidate)

        try:
            import imageio_ffmpeg
            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:  # noqa: BLE001
            return None

    def is_frozen(self) -> bool:
        return bool(getattr(sys, "frozen", False))


class InfoWorker(BaseWorker):
    def __init__(self, url: str) -> None:
        super().__init__()
        self.url = url

    def run(self) -> None:
        self.set_status("Fetching video info...")
        self.log(f"Fetching info for: {self.url}")

        for attempt in range(1, 4):
            try:
                options = {
                    "quiet": True,
                    "no_warnings": True,
                    "noplaylist": True,
                    "forceipv4": True,
                    "socket_timeout": 30,
                    "retries": 10,
                    "extractor_retries": 5,
                    "fragment_retries": 10,
                    "logger": YtDlpWorkerLogger(self),
                }
                options.update(yt_dlp_js_runtime_options())
                with YoutubeDL(options) as ydl:
                    data = ydl.extract_info(self.url, download=False)
                self.signals.finished.emit(data)
                return
            except DownloadError as error:
                message = str(error).strip() or "yt-dlp could not load the video."
                if "WinError 10054" in message and "twitch" in self.url.lower() and attempt < 3:
                    self.log(f"Twitch metadata request dropped. Retrying ({attempt}/2)...")
                    time.sleep(1.5 * attempt)
                    continue
                self.emit_error(message)
                return
            except Exception as error:  # noqa: BLE001
                self.emit_error(str(error))
                return


class DownloadWorker(BaseWorker):
    def __init__(
        self,
        url: str,
        output_template: str,
        ffmpeg_path: str,
        expected_duration: int | None = None,
        start_seconds: int | None = None,
        end_seconds: int | None = None,
        use_hardware_acceleration: bool = False,
    ) -> None:
        super().__init__()
        self.url = url
        self.output_template = output_template
        self.ffmpeg_path = ffmpeg_path
        self.expected_duration = expected_duration
        self.start_seconds = start_seconds
        self.end_seconds = end_seconds
        self.use_hardware_acceleration = use_hardware_acceleration
        self.cancel_requested = False
        self.ydl: YoutubeDL | None = None
        self.ffmpeg_process = None
        self.ffmpeg_progress_state: dict[str, str] = {}
        self.last_progress_percent = -1
        self.last_progress_log_time = 0.0
        self.ffmpeg_progress_base = 0
        self.ffmpeg_progress_span = 100
        self.ffmpeg_progress_duration: float | int | None = expected_duration
        self.ffmpeg_progress_label = "Download progress"

    def cancel(self) -> None:
        if self.cancel_requested:
            return
        self.cancel_requested = True
        ffmpeg_process = self.ffmpeg_process
        if ffmpeg_process is not None and ffmpeg_process.poll() is None:
            try:
                ffmpeg_process.kill(timeout=None)
            except Exception:  # noqa: BLE001
                pass

    def run(self) -> None:
        self.set_status("Downloading...")
        self.signals.progress.emit(0)
        self.log("Starting download...")
        self.log(f"Downloading URL: {self.url}")

        last_error = "Download failed. Check the activity log for details."
        for attempt in range(1, 4):
            if self.cancel_requested:
                self.log("Download cancelled.")
                self.signals.finished.emit({"cancelled": True})
                return

            try:
                code = self.run_standard_download()
                if self.cancel_requested:
                    self.log("Download cancelled.")
                    self.signals.finished.emit({"cancelled": True})
                    return
                if code == 0:
                    self.log("Download finished.")
                    self.signals.progress.emit(100)
                    self.signals.finished.emit({"ok": True})
                    return
                last_error = f"Download failed with exit code {code}."
                self.log(last_error)
            except KeyboardInterrupt:
                self.ydl = None
                self.ffmpeg_process = None
                if self.cancel_requested:
                    self.log("Download cancelled by user.")
                    self.signals.finished.emit({"cancelled": True})
                    return
                last_error = "Download interrupted."
            except DownloadError as error:
                self.ydl = None
                self.ffmpeg_process = None
                if self.cancel_requested:
                    self.log("Download cancelled by user.")
                    self.signals.finished.emit({"cancelled": True})
                    return
                last_error = str(error).strip() or "Download failed."
            except Exception as error:  # noqa: BLE001
                self.ydl = None
                self.ffmpeg_process = None
                last_error = str(error).strip() or "Download failed."

            self.log(last_error)
            if "WinError 10054" in last_error and "twitch" in self.url.lower() and attempt < 3:
                self.log(f"Twitch request dropped. Retrying download ({attempt}/2)...")
                self.signals.progress.emit(0)
                time.sleep(1.5 * attempt)
                continue
            self.emit_error(last_error)
            return

    def run_standard_download(self) -> int:
        self.ffmpeg_progress_base = 0
        self.ffmpeg_progress_span = 100
        self.ffmpeg_progress_duration = self.expected_duration
        self.ffmpeg_progress_label = "Download progress"

        options = {
            "quiet": True,
            "noplaylist": True,
            "forceipv4": True,
            "socket_timeout": 30,
            "retries": 10,
            "extractor_retries": 5,
            "fragment_retries": 10,
            "format": DEFAULT_DOWNLOAD_FORMAT,
            "merge_output_format": "mp4",
            "ffmpeg_location": self.ffmpeg_path,
            "outtmpl": self.output_template,
            "force_keyframes_at_cuts": self.start_seconds is not None and self.end_seconds is not None,
            "progress_hooks": [self.on_progress],
            "logger": YtDlpWorkerLogger(self),
        }
        options.update(yt_dlp_js_runtime_options())
        options["external_downloader_args"] = {"ffmpeg_o": self.build_ffmpeg_output_args()}
        if self.start_seconds is not None and self.end_seconds is not None:
            options["download_ranges"] = download_range_func(None, [(self.start_seconds, self.end_seconds)])

        original_popen = yt_dlp_external.Popen
        yt_dlp_external.Popen = self.make_tracking_popen(original_popen)
        try:
            with YoutubeDL(options) as ydl:
                self.ydl = ydl
                code = ydl.download([self.url])
            self.ydl = None
        finally:
            yt_dlp_external.Popen = original_popen
            self.ffmpeg_process = None
            self.ffmpeg_progress_state = {}
        return code

    def build_ffmpeg_output_args(self) -> list[str]:
        args = ["-progress", "pipe:2", "-nostats"]
        if self.start_seconds is None or self.end_seconds is None or not self.use_hardware_acceleration:
            return args

        encoder = detect_hardware_encoder(self.ffmpeg_path)
        if encoder == "h264_nvenc":
            self.log("Hardware acceleration: using NVIDIA NVENC for clip encoding.")
            return args + ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "19", "-b:v", "0", "-c:a", "aac", "-b:a", "192k"]
        if encoder == "h264_amf":
            self.log("Hardware acceleration: using AMD AMF for clip encoding.")
            return args + ["-c:v", "h264_amf", "-quality", "quality", "-rc", "cqp", "-qp_i", "19", "-qp_p", "21", "-qp_b", "23", "-c:a", "aac", "-b:a", "192k"]
        if encoder == "h264_qsv":
            self.log("Hardware acceleration: using Intel Quick Sync for clip encoding.")
            return args + ["-c:v", "h264_qsv", "-global_quality", "21", "-look_ahead", "0", "-c:a", "aac", "-b:a", "192k"]

        self.log("Hardware acceleration: no supported GPU encoder found. Falling back to CPU encoding.")
        return args

    def make_tracking_popen(self, base_popen):
        worker = self

        class TrackingPopen(base_popen):
            def __init__(self, args, *remaining, **kwargs):
                executable = str(args[0]).lower() if args else ""
                is_ffmpeg = executable.endswith("ffmpeg") or executable.endswith("ffmpeg.exe")
                if is_ffmpeg:
                    kwargs["stderr"] = subprocess.PIPE
                    kwargs["stdout"] = subprocess.DEVNULL
                    kwargs["text"] = True
                    kwargs.setdefault("encoding", "utf-8")
                    kwargs.setdefault("errors", "replace")
                super().__init__(args, *remaining, **kwargs)
                if is_ffmpeg:
                    worker.attach_ffmpeg_process(self)

        return TrackingPopen

    def attach_ffmpeg_process(self, process) -> None:
        self.ffmpeg_process = process
        stderr = process.stderr
        if stderr is None:
            return

        def consume_stderr() -> None:
            try:
                for raw_line in stderr:
                    line = raw_line.strip()
                    if line:
                        self.on_ffmpeg_output(line)
            except Exception:  # noqa: BLE001
                return

        thread = threading.Thread(target=consume_stderr, daemon=True)
        thread.start()

    def on_ffmpeg_output(self, line: str) -> None:
        if "=" not in line:
            return

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        self.ffmpeg_progress_state[key] = value

        if key != "progress":
            return

        percentage = self.ffmpeg_progress_percentage()
        if percentage is not None:
            self.signals.progress.emit(percentage)
            self.log_ffmpeg_progress(percentage)

    def ffmpeg_progress_percentage(self) -> int | None:
        duration = self.ffmpeg_progress_duration
        if not duration or duration <= 0:
            return None

        out_time_ms = self.ffmpeg_progress_state.get("out_time_ms")
        if not out_time_ms or out_time_ms == "N/A":
            return None

        try:
            out_time_seconds = float(out_time_ms) / 1_000_000
        except ValueError:
            return None

        local_percentage = int((out_time_seconds / float(duration)) * 100)
        local_percentage = max(0, min(99, local_percentage))
        overall_percentage = self.ffmpeg_progress_base + int((local_percentage / 100) * self.ffmpeg_progress_span)
        return max(0, min(99, overall_percentage))

    def log_ffmpeg_progress(self, percentage: int) -> None:
        now = time.monotonic()
        if percentage == self.last_progress_percent and (now - self.last_progress_log_time) < 1.5:
            return
        if percentage != self.last_progress_percent and (now - self.last_progress_log_time) < 0.6:
            return

        self.last_progress_percent = percentage
        self.last_progress_log_time = now

        details: list[str] = []
        out_time = self.ffmpeg_progress_state.get("out_time")
        speed = self.ffmpeg_progress_state.get("speed")
        total_size = self.ffmpeg_progress_state.get("total_size")

        if out_time and out_time != "N/A" and self.ffmpeg_progress_duration:
            details.append(f"{out_time} / {format_seconds(self.ffmpeg_progress_duration)}")
        if total_size and total_size.isdigit():
            details.append(self.format_bytes(int(total_size)))
        if speed and speed != "N/A":
            details.append(f"speed {speed}")

        suffix = f" ({', '.join(details)})" if details else ""
        self.log(f"{self.ffmpeg_progress_label}: {percentage}%{suffix}")

    def on_progress(self, data: dict) -> None:
        if self.cancel_requested:
            raise KeyboardInterrupt

        status = data.get("status")
        if status == "finished":
            self.signals.progress.emit(100)
            return

        if status != "downloading":
            return

        total_bytes = data.get("total_bytes") or data.get("total_bytes_estimate")
        downloaded_bytes = data.get("downloaded_bytes")
        percentage: int | None = None
        if total_bytes and downloaded_bytes is not None:
            percentage = int((downloaded_bytes / total_bytes) * 100)
        else:
            percent_text = str(data.get("_percent_str") or "").strip().replace("%", "")
            if percent_text:
                try:
                    percentage = int(float(percent_text))
                except ValueError:
                    percentage = None

        if percentage is None:
            fragment_count = data.get("fragment_count")
            fragment_index = data.get("fragment_index")
            if fragment_count and fragment_index:
                percentage = int((fragment_index / fragment_count) * 100)

        if percentage is None:
            eta = data.get("eta")
            elapsed = data.get("elapsed")
            if isinstance(eta, (int, float)) and isinstance(elapsed, (int, float)) and eta > 0:
                percentage = int((elapsed / (elapsed + eta)) * 100)
                percentage = max(0, min(99, percentage))

        if percentage is not None:
            clamped_percentage = max(0, min(100, percentage))
            self.signals.progress.emit(clamped_percentage)
            self.log_progress_update(data, clamped_percentage)
            return

    def log_progress_update(self, data: dict, percentage: int) -> None:
        now = time.monotonic()
        if percentage == self.last_progress_percent and (now - self.last_progress_log_time) < 1.5:
            return
        if percentage != self.last_progress_percent and percentage < 100 and (now - self.last_progress_log_time) < 0.6:
            return

        self.last_progress_percent = percentage
        self.last_progress_log_time = now

        downloaded_bytes = data.get("downloaded_bytes")
        total_bytes = data.get("total_bytes") or data.get("total_bytes_estimate")
        speed = data.get("speed")
        eta = data.get("eta")
        fragment_index = data.get("fragment_index")
        fragment_count = data.get("fragment_count")

        details: list[str] = []
        if downloaded_bytes is not None and total_bytes:
            details.append(f"{self.format_bytes(downloaded_bytes)} / {self.format_bytes(total_bytes)}")
        elif downloaded_bytes is not None:
            details.append(self.format_bytes(downloaded_bytes))

        if speed:
            details.append(f"{self.format_bytes(speed)}/s")
        if eta is not None:
            details.append(f"ETA {format_seconds(eta)}")
        if fragment_index and fragment_count:
            details.append(f"frag {fragment_index}/{fragment_count}")

        suffix = f" ({', '.join(details)})" if details else ""
        self.log(f"Download progress: {percentage}%{suffix}")

    @staticmethod
    def format_bytes(value: float | int | None) -> str:
        if value is None:
            return "Unknown"
        units = ["B", "KiB", "MiB", "GiB", "TiB"]
        size = float(value)
        unit = units[0]
        for unit in units:
            if size < 1024 or unit == units[-1]:
                break
            size /= 1024
        if unit == "B":
            return f"{int(size)}{unit}"
        return f"{size:.2f}{unit}"


class UpdateCheckWorker(BaseWorker):
    def __init__(self, manifest_url: str, current_version: str) -> None:
        super().__init__()
        self.manifest_url = manifest_url
        self.current_version = current_version

    def run(self) -> None:
        self.log(f"Checking for updates: {self.manifest_url}")
        self.set_status("Checking for updates...")
        request = Request(
            self.manifest_url,
            headers={
                "User-Agent": f"MerchToolsVideoDownloader/{self.current_version}",
                "Accept": "application/json",
            },
        )

        try:
            with urlopen(request, timeout=20, **urlopen_options()) as response:
                payload = response.read().decode("utf-8", errors="replace")
        except HTTPError as error:
            self.emit_error(f"Update check failed with HTTP {error.code}.")
            return
        except URLError as error:
            self.emit_error(f"Update check failed: {error.reason}")
            return
        except Exception as error:  # noqa: BLE001
            self.emit_error(f"Update check failed: {error}")
            return

        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            self.emit_error("Update manifest returned invalid JSON.")
            return

        if not isinstance(data, dict):
            self.emit_error("Update manifest has an unexpected format.")
            return

        latest_version = str(data.get("version", "")).strip()
        installer_url = str(data.get("installer_url") or data.get("url") or "").strip()
        notes = str(data.get("notes", "")).strip()
        filename = str(data.get("filename", "")).strip()

        if not latest_version:
            self.emit_error("Update manifest is missing a version value.")
            return
        if not installer_url:
            self.emit_error("Update manifest is missing an installer_url value.")
            return

        result = {
            "current_version": self.current_version,
            "latest_version": latest_version,
            "installer_url": installer_url,
            "notes": notes,
            "filename": filename,
            "update_available": is_newer_version(self.current_version, latest_version),
        }
        self.signals.finished.emit(result)


class InstallerDownloadWorker(BaseWorker):
    def __init__(self, installer_url: str, version: str, filename: str = "") -> None:
        super().__init__()
        self.installer_url = installer_url
        self.version = version
        self.filename = filename

    def run(self) -> None:
        self.set_status("Downloading update...")
        self.log(f"Downloading update installer: {self.installer_url}")
        request = Request(
            self.installer_url,
            headers={"User-Agent": f"MerchToolsVideoDownloader/{APP_VERSION}"},
        )

        try:
            with urlopen(request, timeout=30, **urlopen_options()) as response:
                total_bytes = int(response.headers.get("Content-Length") or 0)
                update_dir = Path(tempfile.gettempdir()) / "MerchTools Video Downloader Updates"
                update_dir.mkdir(parents=True, exist_ok=True)
                filename = self.resolve_filename()
                destination = update_dir / filename

                downloaded = 0
                last_logged_percent = -1
                with destination.open("wb") as handle:
                    while True:
                        chunk = response.read(1024 * 256)
                        if not chunk:
                            break
                        handle.write(chunk)
                        downloaded += len(chunk)
                        if total_bytes > 0:
                            percent = int((downloaded / total_bytes) * 100)
                            if percent >= last_logged_percent + 10 or percent == 100:
                                last_logged_percent = percent
                                self.log(f"Update download: {percent}%")
        except HTTPError as error:
            self.emit_error(f"Installer download failed with HTTP {error.code}.")
            return
        except URLError as error:
            self.emit_error(
                f"Installer download failed: {error.reason}\n\n"
                f"If this machine has SSL certificate issues, open this link manually:\n{self.installer_url}"
            )
            return
        except Exception as error:  # noqa: BLE001
            self.emit_error(f"Installer download failed: {error}")
            return

        self.signals.finished.emit({"installer_path": str(destination), "version": self.version})

    def resolve_filename(self) -> str:
        if self.filename:
            name = Path(self.filename).name
        else:
            path_name = Path(urlparse(self.installer_url).path).name
            name = path_name or f"MerchToolsVideoDownloaderSetup-{self.version}.exe"
        if not name.lower().endswith(".exe"):
            name = f"{name}.exe"
        return name


class CardFrame(QFrame):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        title_label = QLabel(title)
        title_label.setObjectName("cardTitle")
        layout.addWidget(title_label)

        self.content_layout = QVBoxLayout()
        self.content_layout.setSpacing(12)
        layout.addLayout(self.content_layout)


class CatSpriteLabel(QLabel):
    clicked = Signal(object)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self)
            event.accept()
            return
        super().mousePressEvent(event)


class PixelExplosion(QWidget):
    def __init__(self, parent: QWidget, center: QPoint, color: QColor) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet("background: transparent;")
        self.resize(parent.size())
        self.particles: list[dict] = []
        self.life = 18
        flame_colors = [
            QColor("#fff1b8"),
            QColor("#ffd166"),
            QColor("#ff9f43"),
            QColor("#ff6b35"),
            QColor(color),
        ]
        smoke_colors = [
            QColor("#6d625f"),
            QColor("#4d4542"),
            QColor("#8b807b"),
        ]
        for _ in range(16):
            self.particles.append({
                "x": float(center.x() + random.randint(-8, 8)),
                "y": float(center.y() + random.randint(-8, 8)),
                "dx": random.uniform(-5.8, 5.8),
                "dy": random.uniform(-6.8, 2.6),
                "size": random.randint(6, 12),
                "color": QColor(random.choice(flame_colors)),
                "gravity": 0.30,
                "shrink": 0.42,
                "kind": "flame",
            })
        for _ in range(10):
            self.particles.append({
                "x": float(center.x() + random.randint(-5, 5)),
                "y": float(center.y() + random.randint(-5, 5)),
                "dx": random.uniform(-2.2, 2.2),
                "dy": random.uniform(-3.8, -0.6),
                "size": random.randint(8, 15),
                "color": QColor(random.choice(smoke_colors)),
                "gravity": -0.03,
                "shrink": 0.18,
                "kind": "smoke",
            })
        for _ in range(12):
            self.particles.append({
                "x": float(center.x()),
                "y": float(center.y()),
                "dx": random.uniform(-7.5, 7.5),
                "dy": random.uniform(-4.5, 3.5),
                "size": random.randint(2, 4),
                "color": QColor("#fff4d1"),
                "gravity": 0.16,
                "shrink": 0.08,
                "kind": "spark",
            })
        self.timer = QTimer(self)
        self.timer.setInterval(32)
        self.timer.timeout.connect(self.advance_frame)
        self.show()
        self.raise_()
        self.timer.start()

    def advance_frame(self) -> None:
        self.life -= 1
        for particle in self.particles:
            particle["x"] += particle["dx"]
            particle["y"] += particle["dy"]
            particle["dy"] += particle["gravity"]
            particle["size"] = max(1, particle["size"] - particle["shrink"])
            if particle["kind"] == "smoke":
                particle["dx"] *= 0.98
            else:
                particle["dx"] *= 0.99
        self.update()
        if self.life <= 0:
            self.timer.stop()
            self.deleteLater()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        for particle in self.particles:
            color = QColor(particle["color"])
            alpha_scale = 13 if particle["kind"] == "smoke" else 18
            color.setAlpha(max(18, min(255, self.life * alpha_scale)))
            painter.fillRect(
                int(particle["x"]),
                int(particle["y"]),
                int(particle["size"]),
                int(particle["size"]),
                color,
            )


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1120, 760)
        self.setMinimumSize(980, 760)
        self.apply_window_icon()

        self.dependencies_ready = False
        self.is_fetching_info = False
        self.is_downloading = False
        self.is_checking_updates = False
        self.is_installing_update = False
        self.video_duration: int | None = None
        self.video_title = ""
        self.last_auto_filename = ""
        self.ffmpeg_path: str | None = None
        self.active_thread: QThread | None = None
        self.active_worker: BaseWorker | None = None
        self.update_thread: QThread | None = None
        self.update_worker: BaseWorker | None = None
        self.update_info: dict | None = None
        self.update_config = load_update_config()
        self.user_settings = load_user_settings()
        self.cat_mode_enabled = bool(self.user_settings.get("cat_mode"))
        self.hardware_acceleration_enabled = self.user_settings.get("hardware_acceleration", True) is not False
        self.last_fetched_url = ""
        self.last_output_path: Path | None = None
        self.log_file_path = self.initialize_log_file()
        self._youtube_warning_logged = False
        self._last_display_log: str | None = None
        self._last_activity_phase: str | None = None
        self.root_widget: QWidget | None = None
        self.cat_sprites: list[dict] = []
        self.kittycat_sound_path = self.prepare_kittycat_sound()
        self.cat_timer = QTimer(self)
        self.cat_timer.setInterval(40)
        self.cat_timer.timeout.connect(self.tick_cat_sprites)
        self.url_fetch_timer = QTimer(self)
        self.url_fetch_timer.setInterval(1100)
        self.url_fetch_timer.setSingleShot(True)
        self.url_fetch_timer.timeout.connect(self.fetch_info_if_ready)

        self.setFont(QFont("Segoe UI", 10))
        self.setStyleSheet(self.build_stylesheet(self.cat_mode_enabled))
        self.build_ui()
        self.apply_cat_mode(self.cat_mode_enabled)
        self.update_button_state()
        self.refresh_update_button()
        self.append_log(f"App version: {APP_VERSION}")
        self.append_log("Ready. Paste a YouTube or Twitch link, choose full video or enter a clip range, then download.")
        self.start_dependency_check()

    def build_ui(self) -> None:
        root = QWidget()
        self.root_widget = root
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(16)

        header = QFrame()
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(4)

        top_row = QHBoxLayout()
        header_layout.addLayout(top_row)

        brand_wrap = QVBoxLayout()
        brand_wrap.setSpacing(4)
        top_row.addLayout(brand_wrap)

        eyebrow = QLabel("MerchTools")
        eyebrow.setObjectName("eyebrow")
        brand_wrap.addWidget(eyebrow)

        title = QLabel("Video Downloader")
        title.setObjectName("heroTitle")
        brand_wrap.addWidget(title)
        top_row.addStretch(1)
        pill_row = QHBoxLayout()
        pill_row.setSpacing(12)
        top_row.addLayout(pill_row)

        self.check_updates_button = QPushButton("Check for updates")
        self.check_updates_button.setObjectName("versionPillButton")
        self.check_updates_button.clicked.connect(self.check_for_updates)
        self.check_updates_button.setCursor(Qt.CursorShape.PointingHandCursor)
        pill_row.addWidget(self.check_updates_button)

        self.version_label = QLabel(f"v{APP_VERSION}")
        self.version_label.setObjectName("versionPill")
        pill_row.addWidget(self.version_label)

        content = QHBoxLayout()
        content.setSpacing(16)
        outer.addWidget(header)
        outer.addLayout(content, 1)

        left_column = QVBoxLayout()
        left_column.setSpacing(16)
        content.addLayout(left_column, 5)

        video_card = CardFrame("Video Setup")
        left_column.addWidget(video_card)

        video_grid = QGridLayout()
        video_grid.setHorizontalSpacing(12)
        video_grid.setVerticalSpacing(12)
        video_card.content_layout.addLayout(video_grid)

        self.url_input = QLineEdit()
        self.url_input.setObjectName("primaryInput")
        self.url_input.setPlaceholderText("Paste a YouTube or Twitch URL")
        self.url_input.textChanged.connect(self.on_url_changed)
        saved_output_dir = self.user_settings.get("output_dir") or str(DEFAULT_OUTPUT_DIR)
        self.output_dir_input = QLineEdit(saved_output_dir)
        self.output_dir_input.setObjectName("primaryInput")
        self.filename_input = QLineEdit()
        self.filename_input.setPlaceholderText("Optional custom filename")
        browse_button = QPushButton("Browse")
        browse_button.clicked.connect(self.choose_folder)

        video_grid.addWidget(self.make_field_label("Video URL"), 0, 0)
        video_grid.addWidget(self.url_input, 0, 1, 1, 2)
        video_grid.addWidget(self.make_field_label("Save Folder"), 1, 0)
        video_grid.addWidget(self.output_dir_input, 1, 1)
        video_grid.addWidget(browse_button, 1, 2)
        video_grid.addWidget(self.make_field_label("Filename"), 2, 0)
        video_grid.addWidget(self.filename_input, 2, 1, 1, 2)

        self.video_meta = QLabel("Title: -\nDuration: -")
        self.video_meta.setObjectName("metaText")
        self.video_meta.setWordWrap(True)
        video_card.content_layout.addWidget(self.video_meta)

        clip_card = CardFrame("Clip Range")
        left_column.addWidget(clip_card)

        clip_grid = QGridLayout()
        clip_grid.setHorizontalSpacing(12)
        clip_grid.setVerticalSpacing(12)
        clip_card.content_layout.addLayout(clip_grid)

        self.start_input = QLineEdit()
        self.start_input.setObjectName("timeInput")
        self.end_input = QLineEdit()
        self.end_input.setObjectName("timeInput")
        self.update_clip_range_placeholders()

        clip_grid.addWidget(self.make_field_label("Start Time"), 0, 0)
        clip_grid.addWidget(self.start_input, 0, 1)
        clip_grid.addWidget(self.make_field_label("End Time"), 0, 2)
        clip_grid.addWidget(self.end_input, 0, 3)

        self.clip_hint = QLabel("Enter both start and end times for a clip, or enable full video mode.")
        self.clip_hint.setObjectName("hintText")
        self.clip_hint.setWordWrap(True)
        clip_card.content_layout.addWidget(self.clip_hint)

        self.full_video_checkbox = QCheckBox("Download full video")
        self.full_video_checkbox.setObjectName("optionToggle")
        self.full_video_checkbox.toggled.connect(self.on_full_video_toggled)
        clip_card.content_layout.addWidget(self.full_video_checkbox)

        self.reveal_checkbox = QCheckBox("Reveal in Explorer after download completes")
        self.reveal_checkbox.setObjectName("optionToggle")
        self.reveal_checkbox.setChecked(True)
        clip_card.content_layout.addWidget(self.reveal_checkbox)

        self.hardware_acceleration_checkbox = QCheckBox("Use hardware acceleration")
        self.hardware_acceleration_checkbox.setObjectName("optionToggle")
        self.hardware_acceleration_checkbox.setChecked(self.hardware_acceleration_enabled)
        self.hardware_acceleration_checkbox.toggled.connect(self.on_hardware_acceleration_toggled)
        clip_card.content_layout.addWidget(self.hardware_acceleration_checkbox)

        self.cat_checkbox = QCheckBox("Kittycat")
        self.cat_checkbox.setObjectName("optionToggle")
        self.cat_checkbox.setChecked(self.cat_mode_enabled)
        self.cat_checkbox.toggled.connect(self.on_cat_mode_toggled)
        clip_card.content_layout.addWidget(self.cat_checkbox)

        left_column.addStretch(1)

        right_card = CardFrame("Activity")
        right_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        right_card.setMinimumWidth(380)
        content.addWidget(right_card, 4)

        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setObjectName("logOutput")
        right_card.content_layout.addWidget(self.log_output)

        self.download_button = ProgressButton("Download")
        self.download_button.setObjectName("accentButton")
        self.download_button.clicked.connect(self.download_video)
        self.download_button.setMinimumHeight(56)
        self.download_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        right_card.content_layout.addWidget(self.download_button)
        right_card.content_layout.setStretch(0, 1)

    def apply_window_icon(self) -> None:
        for candidate in bundled_file_candidates("assets/app-icon.png"):
            if candidate.exists():
                icon = QIcon(str(candidate))
                self.setWindowIcon(icon)
                app = QApplication.instance()
                if app is not None:
                    app.setWindowIcon(icon)
                return

    def build_stylesheet(self, cat_mode: bool = False) -> str:
        main_background = "#131516"
        window_background = "#131516"
        card_border = "#2a2e33"
        card_background = "transparent"
        input_background = "#171a1d"
        primary_input_background = "#1b1f23"
        primary_input_border = "#3a4148"
        button_background = "#1b1f23"
        button_hover = "#23282d"
        if cat_mode:
            main_background = "#1b1715"
            window_background = "#201816"
            card_border = "transparent"
            card_background = "transparent"
            input_background = "#211917"
            primary_input_background = "#2a211d"
            primary_input_border = "#7b6159"
            button_background = "#2d221f"
            button_hover = "#382925"

        return f"""
        QWidget {{
            background: {main_background};
            color: #efe8dd;
        }}
        QMainWindow {{
            background: {window_background};
        }}
        QFrame#card {{
            background: {card_background};
            border: 1px solid {card_border};
            border-radius: 20px;
        }}
        QLabel#eyebrow {{
            color: #cbbda8;
            font-size: 12px;
            font-weight: 600;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }}
        QLabel#heroTitle {{
            font-family: "Trebuchet MS";
            font-size: 32px;
            font-weight: 700;
        }}
        QLabel#versionPill {{
            color: #cbbda8;
            font-size: 12px;
            font-weight: 700;
            padding: 0px;
        }}
        QPushButton#versionPillButton {{
            background: transparent;
            color: #cbbda8;
            font-size: 12px;
            font-weight: 700;
            padding: 0px;
            border: none;
        }}
        QPushButton#versionPillButton:hover {{
            color: #efe8dd;
        }}
        QPushButton#versionPillButton:disabled {{
            background: transparent;
            color: #7d766d;
            border: none;
        }}
        QLabel#hintText, QLabel#metaText {{
            color: #cbbda8;
            line-height: 1.4;
        }}
        QCheckBox#optionToggle {{
            color: #efe8dd;
            spacing: 10px;
            font-size: 13px;
        }}
        QCheckBox#optionToggle::indicator {{
            width: 18px;
            height: 18px;
            border-radius: 5px;
            border: 1px solid #3a4148;
            background: #171a1d;
        }}
        QCheckBox#optionToggle::indicator:checked {{
            background: #ff9a55;
            border: 1px solid #ff9a55;
        }}
        QLabel#cardTitle {{
            color: #efe8dd;
            font-family: "Trebuchet MS";
            font-size: 20px;
            font-weight: 700;
        }}
        QLabel#fieldLabel {{
            color: #efe8dd;
            font-size: 12px;
            font-weight: 600;
            letter-spacing: 0.04em;
        }}
        QLineEdit, QPlainTextEdit {{
            background: {input_background};
            border: 1px solid {card_border};
            border-radius: 12px;
            padding: 12px 14px;
            color: #efe8dd;
            selection-background-color: #ff9a55;
            selection-color: #1a1613;
        }}
        QLineEdit#primaryInput {{
            font-size: 14px;
            font-weight: 600;
            min-height: 26px;
            background: {primary_input_background};
            border: 1px solid {primary_input_border};
        }}
        QLineEdit#timeInput {{
            min-height: 24px;
            font-size: 13px;
        }}
        QLineEdit:disabled {{
            background: #101214;
            color: #72767c;
            border: 1px solid #262a2f;
        }}
        QLineEdit:focus, QPlainTextEdit:focus {{
            border: 1px solid #ff9a55;
        }}
        QPushButton {{
            background: {button_background};
            color: #efe8dd;
            border: 1px solid {card_border};
            border-radius: 12px;
            padding: 12px 16px;
            font-weight: 600;
        }}
        QPushButton:hover {{
            background: {button_hover};
        }}
        QPushButton:disabled {{
            background: #171a1d;
            color: #7d766d;
            border-color: #22262a;
        }}
        QPushButton#accentButton {{
            font-size: 14px;
            font-weight: 700;
            padding: 13px 18px;
        }}
        QPlainTextEdit#logOutput {{
            font-family: Consolas, monospace;
            font-size: 13px;
        }}
        """

    def on_cat_mode_toggled(self, checked: bool) -> None:
        self.apply_cat_mode(checked)
        self.persist_user_settings()

    def on_hardware_acceleration_toggled(self, checked: bool) -> None:
        self.hardware_acceleration_enabled = checked
        self.persist_user_settings()

    def apply_cat_mode(self, enabled: bool) -> None:
        self.cat_mode_enabled = enabled
        self.setStyleSheet(self.build_stylesheet(enabled))
        if enabled:
            self.create_cat_sprites()
            self.cat_timer.start()
            self.append_log("Cat mode enabled.")
        else:
            self.cat_timer.stop()
            self.remove_cat_sprites()
            self.append_log("Cat mode disabled.")

    def prepare_kittycat_sound(self) -> Path | None:
        if winsound is None:
            return None
        try:
            sound_dir = user_data_dir() / "sounds"
            sound_dir.mkdir(parents=True, exist_ok=True)
            sound_path = sound_dir / "kittycat-pop.wav"
            if sound_path.exists():
                return sound_path

            sample_rate = 22050
            duration = 0.42
            frame_count = int(sample_rate * duration)
            frames = bytearray()
            for index in range(frame_count):
                t = index / sample_rate
                envelope = math.exp(-7.5 * t)
                pop = math.sin(2 * math.pi * (92 + 40 * t) * t) * envelope * 0.16
                crackle = math.sin(2 * math.pi * 180 * t) * math.exp(-18 * t) * 0.05
                meow_delay = max(0.0, t - 0.08)
                meow = math.sin(2 * math.pi * (720 - 260 * meow_delay) * meow_delay) * math.exp(-5.6 * meow_delay) * 0.11
                sample = max(-1.0, min(1.0, pop + crackle + meow))
                frames.extend(struct.pack("<h", int(sample * 32767)))

            with wave.open(str(sound_path), "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(sample_rate)
                wav_file.writeframes(bytes(frames))
            return sound_path
        except OSError:
            return None

    def play_kittycat_sound(self) -> None:
        if winsound is None or self.kittycat_sound_path is None:
            return
        try:
            winsound.PlaySound(
                str(self.kittycat_sound_path),
                winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
            )
        except RuntimeError:
            return

    def choose_cat_variant(self) -> dict:
        return random.choice([
            {
                "fur": QColor("#f3cfb1"),
                "outline": QColor("#5b4039"),
                "ears": QColor("#f6b7ba"),
                "eyes": QColor("#302624"),
                "blush": QColor("#f2a5a3"),
                "face_scale": 0.64,
                "ear_height": 0.08,
                "cheek_fluff": 0.0,
            },
            {
                "fur": QColor("#d7d2cb"),
                "outline": QColor("#4d4d57"),
                "ears": QColor("#f3c2d3"),
                "eyes": QColor("#23252c"),
                "blush": QColor("#dfb0bf"),
                "face_scale": 0.68,
                "ear_height": 0.06,
                "cheek_fluff": 0.03,
            },
            {
                "fur": QColor("#232020"),
                "outline": QColor("#c5b4ae"),
                "ears": QColor("#c89198"),
                "eyes": QColor("#f2efe8"),
                "blush": QColor("#9c6e74"),
                "face_scale": 0.62,
                "ear_height": 0.10,
                "cheek_fluff": 0.01,
            },
            {
                "fur": QColor("#f0c79d"),
                "outline": QColor("#8a5f43"),
                "ears": QColor("#f2aab0"),
                "eyes": QColor("#4b311d"),
                "blush": QColor("#ef9e92"),
                "face_scale": 0.60,
                "ear_height": 0.09,
                "cheek_fluff": 0.04,
            },
            {
                "fur": QColor("#e9dfcf"),
                "outline": QColor("#6c645e"),
                "ears": QColor("#f4c2c7"),
                "eyes": QColor("#2d2926"),
                "blush": QColor("#e8b1ab"),
                "face_scale": 0.70,
                "ear_height": 0.05,
                "cheek_fluff": 0.05,
            },
        ])

    def build_cat_sprite(self, layer: str | None = None) -> dict | None:
        if self.root_widget is None:
            return None

        variant = self.choose_cat_variant()
        layer = "foreground"
        size_bucket = random.random()
        if size_bucket < 0.2:
            size = random.randint(34, 50)
        elif size_bucket < 0.55:
            size = random.randint(54, 90)
        else:
            size = random.randint(96, 156)
        label = CatSpriteLabel(self.root_widget)
        label.setPixmap(self.create_cat_pixmap(size, variant))
        label.setFixedSize(size, size)
        label.setStyleSheet("background: transparent;")
        label.clicked.connect(self.on_cat_clicked)
        label.show()
        label.raise_()

        x_limit = max(1, self.root_widget.width() - size)
        y_limit = max(1, self.root_widget.height() - size)
        sprite = {
            "label": label,
            "layer": layer,
            "variant": variant,
            "x": float(random.randint(0, x_limit)),
            "y": float(random.randint(0, y_limit)),
            "dx": random.choice([-1.0, 1.0]) * random.uniform(0.70, 1.35),
            "dy": random.choice([-1.0, 1.0]) * random.uniform(0.18, 0.42),
            "phase": random.uniform(0.0, 6.28),
            "phase_step": random.uniform(0.07, 0.12),
            "bob": random.uniform(0.10, 0.22),
        }
        label.setWindowOpacity(0.96)
        label.move(int(sprite["x"]), int(sprite["y"]))
        return sprite

    def create_cat_sprites(self) -> None:
        if self.cat_sprites or self.root_widget is None:
            return

        sprite_count = 8
        for _ in range(sprite_count):
            sprite = self.build_cat_sprite("foreground")
            if sprite is not None:
                self.cat_sprites.append(sprite)
        self.position_cat_sprites()

    def on_cat_clicked(self, label: QLabel) -> None:
        if self.root_widget is None:
            return
        sprite = next((item for item in self.cat_sprites if item["label"] is label), None)
        if sprite is None:
            return

        center = label.geometry().center()
        PixelExplosion(self.root_widget, center, QColor(sprite["variant"]["fur"]))
        self.play_kittycat_sound()
        self.cat_sprites.remove(sprite)
        label.hide()
        label.deleteLater()

        if self.cat_mode_enabled:
            QTimer.singleShot(260, self.spawn_replacement_cat)

    def spawn_replacement_cat(self) -> None:
        if not self.cat_mode_enabled:
            return
        sprite = self.build_cat_sprite()
        if sprite is None:
            return
        self.cat_sprites.append(sprite)
        self.position_cat_sprites()

    def remove_cat_sprites(self) -> None:
        for sprite in self.cat_sprites:
            label = sprite["label"]
            label.hide()
            label.deleteLater()
        self.cat_sprites.clear()

    def create_cat_pixmap(self, size: int, variant: dict) -> QPixmap:
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        outline = QColor(variant["outline"])
        face_color = QColor(variant["fur"])
        inner_ear = QColor(variant["ears"])
        eye_color = QColor(variant["eyes"])
        blush_color = QColor(variant["blush"])
        face_scale = float(variant["face_scale"])
        ear_height = float(variant["ear_height"])
        cheek_fluff = float(variant["cheek_fluff"])

        painter.setPen(QPen(outline, max(2, size // 26)))
        painter.setBrush(face_color)
        ear_left = QPolygon([
            QPoint(int(size * 0.24), int(size * 0.36)),
            QPoint(int(size * 0.38), int(size * ear_height)),
            QPoint(int(size * 0.5), int(size * 0.34)),
        ])
        ear_right = QPolygon([
            QPoint(int(size * 0.5), int(size * 0.34)),
            QPoint(int(size * 0.63), int(size * ear_height)),
            QPoint(int(size * 0.76), int(size * 0.36)),
        ])
        painter.drawPolygon(ear_left)
        painter.drawPolygon(ear_right)

        painter.setBrush(inner_ear)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPolygon(QPolygon([
            QPoint(int(size * 0.31), int(size * 0.31)),
            QPoint(int(size * 0.39), int(size * 0.15)),
            QPoint(int(size * 0.46), int(size * 0.31)),
        ]))
        painter.drawPolygon(QPolygon([
            QPoint(int(size * 0.54), int(size * 0.31)),
            QPoint(int(size * 0.61), int(size * 0.15)),
            QPoint(int(size * 0.69), int(size * 0.31)),
        ]))

        painter.setPen(QPen(outline, max(2, size // 26)))
        painter.setBrush(face_color)
        face_width = int(size * face_scale)
        face_height = int(size * (0.56 + cheek_fluff))
        face_x = int((size - face_width) / 2)
        face_y = int(size * (0.24 - cheek_fluff / 2))
        painter.drawEllipse(face_x, face_y, face_width, face_height)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(eye_color)
        painter.drawEllipse(int(size * 0.34), int(size * 0.47), int(size * 0.08), int(size * 0.11))
        painter.drawEllipse(int(size * 0.58), int(size * 0.47), int(size * 0.08), int(size * 0.11))

        painter.setBrush(blush_color)
        painter.drawEllipse(int(size * 0.23), int(size * 0.57), int(size * 0.12), int(size * 0.08))
        painter.drawEllipse(int(size * 0.65), int(size * 0.57), int(size * 0.12), int(size * 0.08))

        painter.setPen(QPen(outline, max(2, size // 30)))
        painter.drawLine(int(size * 0.5), int(size * 0.53), int(size * 0.46), int(size * 0.59))
        painter.drawLine(int(size * 0.5), int(size * 0.53), int(size * 0.54), int(size * 0.59))
        painter.drawLine(int(size * 0.16), int(size * 0.54), int(size * 0.37), int(size * 0.56))
        painter.drawLine(int(size * 0.16), int(size * 0.62), int(size * 0.37), int(size * 0.59))
        painter.drawLine(int(size * 0.63), int(size * 0.56), int(size * 0.84), int(size * 0.54))
        painter.drawLine(int(size * 0.63), int(size * 0.59), int(size * 0.84), int(size * 0.62))
        painter.end()
        return pixmap

    def position_cat_sprites(self) -> None:
        if self.root_widget is None:
            return
        width = self.root_widget.width()
        height = self.root_widget.height()
        for sprite in self.cat_sprites:
            label = sprite["label"]
            size = label.width()
            x_limit = max(0, width - size)
            y_limit = max(0, height - size)
            x = max(0, min(int(sprite["x"]), x_limit))
            y = max(0, min(int(sprite["y"]), y_limit))
            label.move(x, y)
            if sprite["layer"] == "foreground":
                label.raise_()
            else:
                label.lower()

    def tick_cat_sprites(self) -> None:
        if self.root_widget is None or not self.cat_sprites:
            return

        width = self.root_widget.width()
        height = self.root_widget.height()
        for sprite in self.cat_sprites:
            label = sprite["label"]
            size = label.width()
            x_limit = max(0, width - size)
            y_limit = max(0, height - size)
            sprite["phase"] += sprite["phase_step"]
            sprite["x"] += sprite["dx"]
            sprite["y"] += sprite["dy"] + (sprite["bob"] if sprite["phase"] % 6.28 < 3.14 else -sprite["bob"])

            if sprite["x"] <= 0 or sprite["x"] >= x_limit:
                sprite["dx"] *= -1
                sprite["x"] = max(0, min(sprite["x"], x_limit))
            if sprite["y"] <= 0 or sprite["y"] >= y_limit:
                sprite["dy"] *= -1
                sprite["y"] = max(0, min(sprite["y"], y_limit))

            label.move(int(sprite["x"]), int(sprite["y"]))
            if sprite["layer"] == "foreground":
                label.raise_()
            else:
                label.lower()

    def make_field_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("fieldLabel")
        return label

    def initialize_log_file(self) -> Path | None:
        try:
            log_dir = user_data_dir() / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / "activity.log"
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(f"\n=== Session started {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n")
            return log_path
        except OSError:
            return None

    def write_raw_log(self, message: str) -> None:
        if not self.log_file_path:
            return
        try:
            with self.log_file_path.open("a", encoding="utf-8") as handle:
                handle.write(f"{message}\n")
        except OSError:
            return

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self.position_cat_sprites()

    def format_activity_message(self, phase: str, text: str) -> str:
        if self._last_activity_phase == phase:
            return text
        self._last_activity_phase = phase
        return f"\n[{phase}]\n{text}"

    def format_progress_clock(self, value: str) -> str:
        cleaned = value.strip()
        if ":" in cleaned:
            clock_parts = cleaned.split(":")
            if len(clock_parts) == 3:
                hours_text, minutes_text, seconds_text = clock_parts
                try:
                    hours = int(hours_text)
                    minutes = int(minutes_text)
                    seconds = int(float(seconds_text))
                except ValueError:
                    return cleaned
                if hours:
                    return f"{hours}:{minutes:02d}:{seconds:02d}"
                return f"{minutes:02d}:{seconds:02d}"
        try:
            total_seconds = max(0, int(float(cleaned)))
        except ValueError:
            return cleaned

        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    def simplify_log_message(self, message: str) -> str | None:
        text = message.strip()
        if not text:
            return None

        if text.startswith("Checking for updates: "):
            return self.format_activity_message("Updates", "Checking for updates...")
        if text == "You already have the latest version.":
            return self.format_activity_message("Updates", "App is up to date.")
        if text in {"Cat mode enabled.", "Cat mode disabled."}:
            return None
        if text.startswith("Auto-fetching info for:"):
            return self.format_activity_message("Video", "Loading video details...")
        if text == "Starting metadata lookup...":
            return None
        if text.startswith("Fetching info for: "):
            return None
        if text == "Starting download worker...":
            return self.format_activity_message("Download", "Preparing download...")
        if text == "Starting download...":
            return None
        if text.startswith("Downloading URL: "):
            return None
        if text.startswith("[youtube] Extracting URL:"):
            return None
        if text.startswith("[youtube] [WinError 10054]"):
            return None
        if text.startswith("[youtube] ") and ": Downloading webpage" in text:
            return None
        if text.startswith("[youtube] ") and ": Downloading android vr player API JSON" in text:
            return None
        if text.startswith("[youtube] ") and ": Downloading tv client config" in text:
            return None
        if text.startswith("[youtube] ") and ": Downloading tv player API JSON" in text:
            return None
        if text.startswith("[youtube] ") and ": Downloading web client config" in text:
            return None
        if text.startswith("[youtube] ") and ": Downloading web player API JSON" in text:
            return None
        if text.startswith("[youtube] ") and ": Downloading player " in text:
            return None
        if text.startswith("[youtube] ") and "Some tv client https formats have been skipped as they are DRM protected." in text:
            return None
        if text.startswith("[youtube] [jsc:node] Solving JS challenges using node"):
            return None
        if text.startswith("[youtube] [jsc:node] Downloading challenge solver lib script from "):
            return None
        if text.startswith("[youtube] [jsc:node] Downloading challenge solver core script from "):
            return None
        if text.startswith("[youtube] [jsc] Error solving n challenge request using "):
            return None
        if text.startswith("input = NChallengeInput("):
            return None
        if text.startswith("Please report this issue on "):
            return None
        if "[jsc] Remote component challenge solver script (node) was skipped." in text:
            if self._youtube_warning_logged:
                return None
            self._youtube_warning_logged = True
            return None
        if text.startswith("Hardware acceleration: "):
            return None
        if text.startswith("Twitch metadata request dropped. Retrying"):
            return None
        if text.startswith("Twitch request dropped. Retrying download"):
            return None
        if "n challenge solving failed" in text:
            if self._youtube_warning_logged:
                return None
            self._youtube_warning_logged = True
            return None
        if text.startswith("[info] ") and ": Downloading 1 format(s):" in text:
            return None
        if text.startswith("[info] ") and ": Downloading 1 time ranges:" in text:
            return self.format_activity_message("Download", "Cutting the selected clip range...")
        if text.startswith("[download] Destination: "):
            destination = text.split(": ", 1)[1].strip()
            return self.format_activity_message("Download", f"Saving to: {Path(destination).name}")
        if text.startswith("[download] 100% of "):
            return None
        if text == "\x1b[0;31mERROR:\x1b[0m ffmpeg exited with code 1":
            return None
        if text.startswith("Download progress: "):
            progress_match = re.search(r"Download progress: (\d+)% \(([^,]+) / ([^,)]+)", text)
            if progress_match:
                percent = progress_match.group(1)
                elapsed = self.format_progress_clock(progress_match.group(2))
                total = self.format_progress_clock(progress_match.group(3))
                return f"Download progress: {percent}% | {elapsed} / {total}"
            percent_match = re.search(r"Download progress: (\d+)%", text)
            if percent_match:
                return f"Download progress: {percent_match.group(1)}%"
        if text == "Download finished.":
            return self.format_activity_message("Done", "Download complete.")
        if text == "Download cancelled by user.":
            return self.format_activity_message("Done", "Download cancelled.")
        if text == "Cancelled the current download and removed partial files.":
            return "Partial download removed."
        if text == "Looking for yt-dlp and ffmpeg...":
            return None
        if text == "Dependencies already available. No setup needed.":
            return None
        return text

    def append_log(self, message: str) -> None:
        self.write_raw_log(message)
        display_message = self.simplify_log_message(message)
        if display_message is None:
            return
        if display_message == self._last_display_log:
            return
        self._last_display_log = display_message
        self.log_output.appendPlainText(display_message)
        self.log_output.verticalScrollBar().setValue(self.log_output.verticalScrollBar().maximum())

    def set_status(self, text: str) -> None:
        if text != "Downloading...":
            self.download_button.set_progress_state(False, 0)

    def set_progress(self, value: int) -> None:
        self.download_button.set_progress_state(True, max(0, min(100, value)))

    def refresh_update_button(self) -> None:
        if not hasattr(self, "check_updates_button"):
            return

        if self.is_installing_update:
            self.check_updates_button.setText("Downloading Update...")
            self.check_updates_button.setDisabled(True)
            return

        if self.is_checking_updates:
            self.check_updates_button.setText("Checking...")
            self.check_updates_button.setDisabled(True)
            return

        if self.update_info and self.update_info.get("update_available"):
            latest_version = self.update_info.get("latest_version", "")
            self.check_updates_button.setText(f"Update v{latest_version}")
        else:
            self.check_updates_button.setText("Check for updates")
        self.check_updates_button.setDisabled(False)

    def choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose Save Folder", self.output_dir_input.text())
        if folder:
            self.output_dir_input.setText(folder)
            self.persist_user_settings()

    def on_full_video_toggled(self, checked: bool) -> None:
        self.start_input.setDisabled(checked)
        self.end_input.setDisabled(checked)

    def update_clip_range_placeholders(self) -> None:
        self.start_input.setPlaceholderText("0:00")
        max_range = format_seconds(self.video_duration) if self.video_duration is not None else "0:00"
        self.end_input.setPlaceholderText(max_range)

    def on_url_changed(self, _: str) -> None:
        self.video_meta.setText("Title: -\nDuration: -")
        self.video_duration = None
        self.video_title = ""
        self.last_fetched_url = ""
        self._youtube_warning_logged = False
        self._last_activity_phase = None
        self.update_clip_range_placeholders()
        if not self.url_input.text().strip():
            self.url_fetch_timer.stop()
            self.update_button_state()
            return
        if self.dependencies_ready and not self.is_downloading:
            self.url_fetch_timer.start()
        self.update_button_state()

    def fetch_info_if_ready(self) -> None:
        if not self.dependencies_ready or self.is_fetching_info or self.is_downloading:
            return
        url = self.apply_normalized_url()
        if not url or url == self.last_fetched_url:
            return
        self.append_log(f"Auto-fetching info for: {url}")
        self.fetch_info()

    def fetch_info(self) -> None:
        if not self.dependencies_ready or self.is_fetching_info or self.is_downloading:
            return

        url = self.apply_normalized_url()
        if not url:
            return

        if not self.python_has_yt_dlp():
            self.append_log("yt-dlp module is not available.")
            return

        self.is_fetching_info = True
        self.set_status("Fetching video info...")
        self.update_button_state()
        self.append_log("Starting metadata lookup...")
        worker = InfoWorker(url)
        self.run_worker(
            worker,
            self.on_info_loaded,
            lambda message: self.on_worker_error(message, "Ready"),
        )

    def download_video(self) -> None:
        if self.is_downloading:
            self.cancel_download()
            return

        if not self.dependencies_ready or self.is_fetching_info:
            self.show_error("The app is still preparing or processing. Please wait a moment.")
            return

        url = self.apply_normalized_url()
        if not url:
            self.show_error("Paste a YouTube or Twitch URL first.")
            return

        output_dir = Path(self.output_dir_input.text().strip() or DEFAULT_OUTPUT_DIR)
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            self.show_error(
                "The selected save folder could not be created.\n\n"
                f"{output_dir}\n\n"
                f"{error}"
            )
            return
        self.persist_user_settings()
        target_output_path = self.resolve_output_path(output_dir)
        if target_output_path.exists():
            answer = QMessageBox.question(
                self,
                APP_TITLE,
                f'"{target_output_path.name}" already exists.\n\nDo you want to overwrite it?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            target_output_path.unlink()
            self.append_log(f"Removed existing file: {target_output_path}")
        self.last_output_path = target_output_path

        start_text = self.start_input.text().strip()
        end_text = self.end_input.text().strip()
        ffmpeg_path = self.resolve_ffmpeg_executable()
        if not self.python_has_yt_dlp():
            self.show_error("yt-dlp is not available inside the app bundle.")
            return
        if not ffmpeg_path:
            self.show_error(
                "ffmpeg could not be prepared automatically.\n\n"
                "This app needs ffmpeg to merge the best video+audio and cut exact sections."
            )
            return

        expected_duration: int | None = self.video_duration
        start_seconds: int | None = None
        end_seconds: int | None = None
        if not self.full_video_checkbox.isChecked():
            if not start_text or not end_text:
                self.show_error('Enter both start and end times, or enable "Download full video".')
                return

            try:
                start_seconds = parse_timecode(start_text)
                end_seconds = parse_timecode(end_text)
            except ValueError as error:
                self.show_error(str(error))
                return

            if end_seconds <= start_seconds:
                self.show_error("End time must be later than start time.")
                return

            if self.video_duration is not None and end_seconds > self.video_duration:
                self.show_error("End time is longer than the video duration.")
                return

            section_value = f"*{format_seconds(start_seconds)}-{format_seconds(end_seconds)}"
            expected_duration = end_seconds - start_seconds
        else:
            self.append_log("Full video mode enabled.")

        self.is_downloading = True
        self.set_progress(0)
        self.set_status("Downloading...")
        self.update_button_state()
        self.append_log("Starting download worker...")
        worker = DownloadWorker(
            url=url,
            output_template=self.build_output_template(output_dir),
            ffmpeg_path=ffmpeg_path,
            expected_duration=expected_duration,
            start_seconds=start_seconds,
            end_seconds=end_seconds,
            use_hardware_acceleration=self.hardware_acceleration_enabled,
        )
        self.run_worker(
            worker,
            self.on_download_finished,
            lambda message: self.on_worker_error(message, "Ready"),
            progress_handler=self.set_progress,
        )

    def on_info_loaded(self, data: object) -> None:
        self.is_fetching_info = False
        self.set_status("Ready")
        if not isinstance(data, dict):
            self.update_button_state()
            return

        self.last_fetched_url = self.url_input.text().strip()
        title = data.get("title") or "-"
        self.video_title = title if isinstance(title, str) else ""
        duration = data.get("duration")
        self.video_duration = int(duration) if isinstance(duration, (int, float)) else None
        self.video_meta.setText(f"Title: {title}\nDuration: {format_seconds(self.video_duration)}")
        self.update_clip_range_placeholders()
        suggested_filename = self.sanitize_filename(title)
        current_filename = self.filename_input.text().strip()
        if not current_filename or current_filename == self.last_auto_filename:
            self.filename_input.setText(suggested_filename)
            self.last_auto_filename = suggested_filename
        self.append_log(f"Loaded video: {title}")
        self.append_log(f"Duration: {format_seconds(self.video_duration)}")
        self.update_button_state()

    def on_download_finished(self, result: object) -> None:
        self.is_downloading = False
        self.set_status("Ready")
        self.update_button_state()
        if isinstance(result, dict) and result.get("cancelled"):
            self.cleanup_cancelled_download()
            self.append_log("Cancelled the current download and removed partial files.")
            return

        if self.reveal_checkbox.isChecked():
            self.reveal_in_explorer()
        QMessageBox.information(self, APP_TITLE, "Download completed successfully.")

    def on_dependencies_ready(self, result: object) -> None:
        self.dependencies_ready = True
        self.set_status("Ready")
        if isinstance(result, dict):
            self.ffmpeg_path = result.get("ffmpeg_path")
        self.update_button_state()
        self.fetch_info_if_ready()
        self.queue_startup_update_check()

    def on_update_check_finished(self, result: object) -> None:
        self.is_checking_updates = False
        self.refresh_update_button()

        if not isinstance(result, dict):
            return

        self.update_info = result
        latest_version = result.get("latest_version", "")
        if result.get("update_available"):
            self.append_log(f"Update available: v{latest_version}")
            self.refresh_update_button()
            notes = str(result.get("notes", "")).strip()
            body = f"Version {latest_version} is available. You are on {APP_VERSION}."
            if notes:
                body += f"\n\nWhat's new:\n{notes}"
            body += "\n\nDownload and launch the installer now?"
            answer = QMessageBox.question(
                self,
                APP_TITLE,
                body,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer == QMessageBox.StandardButton.Yes:
                self.download_update_installer()
            return

        self.append_log("You already have the latest version.")

    def on_update_download_finished(self, result: object) -> None:
        self.is_installing_update = False
        self.refresh_update_button()
        if not isinstance(result, dict):
            return

        installer_path = str(result.get("installer_path", "")).strip()
        version = str(result.get("version", "")).strip()
        if not installer_path:
            return

        self.append_log(f"Update installer downloaded: {installer_path}")
        answer = QMessageBox.question(
            self,
            APP_TITLE,
            f"Update v{version} is ready.\n\nLaunch the installer now? The app will close right after it starts.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self.launch_update_installer(installer_path)

    def on_worker_error(self, message: str, status: str) -> None:
        self.is_fetching_info = False
        self.is_downloading = False
        self.set_status(status)
        self.update_button_state()
        self.show_error(message)

    def on_thread_finished(self) -> None:
        self.active_thread = None
        self.active_worker = None

    def on_update_thread_finished(self) -> None:
        self.update_thread = None
        self.update_worker = None

    def show_error(self, message: str) -> None:
        QMessageBox.critical(self, APP_TITLE, message)

    def apply_normalized_url(self) -> str:
        normalized = normalize_video_url(self.url_input.text())
        if normalized and normalized != self.url_input.text().strip():
            self.url_input.blockSignals(True)
            self.url_input.setText(normalized)
            self.url_input.blockSignals(False)
        return normalized

    def update_button_state(self) -> None:
        can_download = (
            self.dependencies_ready
            and not self.is_fetching_info
            and bool(self.url_input.text().strip())
        )
        self.download_button.setDisabled(not can_download)

    def cancel_download(self) -> None:
        worker = self.active_worker
        if not self.is_downloading or not isinstance(worker, DownloadWorker):
            return
        if worker.cancel_requested:
            return
        self.append_log("Cancelling download...")
        worker.cancel()

    def persist_user_settings(self) -> None:
        save_user_settings({
            "output_dir": self.output_dir_input.text().strip() or str(DEFAULT_OUTPUT_DIR),
            "cat_mode": self.cat_mode_enabled,
            "hardware_acceleration": self.hardware_acceleration_enabled,
        })

    def cleanup_cancelled_download(self) -> None:
        target_path = self.last_output_path
        output_dir = Path(self.output_dir_input.text().strip() or DEFAULT_OUTPUT_DIR)
        candidates: list[Path] = []
        if target_path is not None:
            candidates.extend([
                target_path,
                target_path.with_suffix(".mp4.part"),
                target_path.with_suffix(".part"),
                target_path.with_suffix(".f140.mp4"),
                target_path.with_suffix(".f251.webm"),
            ])
            stem = target_path.stem
            yt_dlp_temp_name = re.compile(rf"^{re.escape(stem)}\.f\d+\..+")
            for candidate in output_dir.glob(f"{stem}*"):
                if candidate == target_path:
                    continue
                name = candidate.name
                if (
                    ".part" in name
                    or name.endswith(".ytdl")
                    or name.endswith(".temp")
                    or yt_dlp_temp_name.match(name)
                ):
                    candidates.append(candidate)

        seen: set[Path] = set()
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            if candidate.exists():
                try:
                    candidate.unlink()
                except OSError:
                    pass

    def update_configured(self) -> bool:
        manifest_url = str(self.update_config.get("manifest_url", "")).strip()
        return manifest_url.startswith("http://") or manifest_url.startswith("https://")

    def queue_startup_update_check(self) -> None:
        if self.update_config.get("check_on_startup", True):
            QTimer.singleShot(1500, lambda: self.check_for_updates(silent=True))

    def check_for_updates(self, silent: bool = False) -> None:
        if self.is_checking_updates or self.is_installing_update:
            return

        if not self.update_configured():
            if not silent:
                config_paths = "\n".join(str(path) for path in bundled_file_candidates(UPDATE_CONFIG_FILENAME))
                QMessageBox.information(
                    self,
                    APP_TITLE,
                    "Updates are not configured yet.\n\n"
                    "Set a manifest_url in update_config.json, then rebuild the installer.\n\n"
                    f"App version: {APP_VERSION}\n\n"
                    f"Searched these locations:\n{config_paths}",
                )
            return

        if self.update_thread is not None:
            return

        self.is_checking_updates = True
        self.refresh_update_button()
        worker = UpdateCheckWorker(str(self.update_config.get("manifest_url", "")).strip(), APP_VERSION)
        self.run_update_worker(
            worker,
            self.on_update_check_finished,
            lambda message: self.on_update_error(message, silent=silent, during_download=False),
        )

    def download_update_installer(self) -> None:
        if not self.update_info:
            return

        installer_url = str(self.update_info.get("installer_url", "")).strip()
        latest_version = str(self.update_info.get("latest_version", "")).strip()
        filename = str(self.update_info.get("filename", "")).strip()
        if not installer_url or not latest_version:
            return

        self.is_installing_update = True
        self.refresh_update_button()
        worker = InstallerDownloadWorker(installer_url, latest_version, filename)
        self.run_update_worker(
            worker,
            self.on_update_download_finished,
            lambda message: self.on_update_error(message, silent=False, during_download=True),
        )

    def on_update_error(self, message: str, silent: bool, during_download: bool) -> None:
        self.is_checking_updates = False
        self.is_installing_update = False
        self.refresh_update_button()
        self.append_log(message)
        if silent:
            return

        title = "Update download failed." if during_download else "Update check failed."
        if during_download and self.update_info and "open this link manually:" in message.lower():
            installer_url = str(self.update_info.get("installer_url", "")).strip()
            answer = QMessageBox.question(
                self,
                APP_TITLE,
                f"{title}\n\n{message}\n\nOpen the installer link in your browser instead?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer == QMessageBox.StandardButton.Yes and installer_url:
                try:
                    os.startfile(installer_url)
                except OSError:
                    pass
            return

        self.show_error(f"{title}\n\n{message}")

    def launch_update_installer(self, installer_path: str) -> None:
        try:
            os.startfile(installer_path)
        except OSError as error:
            self.show_error(f"Could not launch the installer.\n\n{error}")
            return

        QTimer.singleShot(250, QApplication.instance().quit)

    def reveal_in_explorer(self) -> None:
        output_dir = Path(self.output_dir_input.text().strip() or DEFAULT_OUTPUT_DIR)
        if not output_dir.exists():
            return
        os.startfile(str(output_dir))

    def start_dependency_check(self) -> None:
        self.append_log("Looking for yt-dlp and ffmpeg...")
        existing_ffmpeg = self.resolve_ffmpeg_executable()
        if self.python_has_yt_dlp() and existing_ffmpeg:
            self.ffmpeg_path = existing_ffmpeg
            self.dependencies_ready = True
            self.set_status("Ready")
            self.append_log("Dependencies already available. No setup needed.")
            self.update_button_state()
            self.fetch_info_if_ready()
            self.queue_startup_update_check()
            return

        self.update_button_state()
        worker = DependencyWorker()
        self.run_worker(
            worker,
            self.on_dependencies_ready,
            lambda message: self.on_worker_error(message, "Setup failed"),
        )

    def run_worker(self, worker: BaseWorker, success_handler, error_handler, progress_handler=None) -> None:
        thread = QThread(self)
        worker.moveToThread(thread)
        self.active_thread = thread
        self.active_worker = worker
        worker.signals.log.connect(self.append_log)
        worker.signals.status.connect(self.set_status)
        if progress_handler is not None:
            worker.signals.progress.connect(progress_handler)
        worker.signals.finished.connect(success_handler)
        worker.signals.finished.connect(thread.quit)
        worker.signals.finished.connect(worker.deleteLater)
        worker.signals.error.connect(error_handler)
        worker.signals.error.connect(thread.quit)
        worker.signals.error.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self.on_thread_finished)
        thread.started.connect(worker.run)
        thread.start()

    def run_update_worker(self, worker: BaseWorker, success_handler, error_handler) -> None:
        thread = QThread(self)
        worker.moveToThread(thread)
        self.update_thread = thread
        self.update_worker = worker
        worker.signals.log.connect(self.append_log)
        worker.signals.finished.connect(success_handler)
        worker.signals.finished.connect(thread.quit)
        worker.signals.finished.connect(worker.deleteLater)
        worker.signals.error.connect(error_handler)
        worker.signals.error.connect(thread.quit)
        worker.signals.error.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self.on_update_thread_finished)
        thread.started.connect(worker.run)
        thread.start()

    def resolve_yt_dlp_command(self, require_ffmpeg: bool = False) -> list[str] | None:
        module_spec = shutil.which("yt-dlp")
        if self.is_frozen():
            packaged_dir = Path(sys.executable).resolve().parent
            candidates = [
                packaged_dir / "yt-dlp.exe",
                packaged_dir / "_internal" / "yt-dlp.exe",
            ]
            for candidate in candidates:
                if candidate.exists():
                    command = [str(candidate)]
                    break
            else:
                command = None
        elif self.python_has_yt_dlp():
            command = [sys.executable, "-m", "yt_dlp"]
        elif module_spec:
            command = [module_spec]
        else:
            command = None

        if not command:
            self.append_log("yt-dlp was not found in the packaged app or on PATH.")
            self.show_error(
                "yt-dlp is not installed.\n\n"
                "Run: pip install yt-dlp\n"
                "or install the yt-dlp executable and add it to PATH."
            )
            return None

        if require_ffmpeg and not self.resolve_ffmpeg_executable():
            self.show_error(
                "ffmpeg could not be prepared automatically.\n\n"
                "This app needs ffmpeg to merge the best video+audio and cut exact sections."
            )
            return None

        return command

    def python_has_yt_dlp(self) -> bool:
        try:
            importlib.import_module("yt_dlp")
        except ImportError:
            return False
        return True

    def resolve_ffmpeg_executable(self) -> str | None:
        if self.ffmpeg_path:
            return self.ffmpeg_path
        return DependencyWorker().resolve_ffmpeg_executable()

    def build_output_template(self, output_dir: Path) -> str:
        requested_name = self.filename_input.text().strip()
        if requested_name:
            safe_name = self.sanitize_filename(requested_name)
            return str(output_dir / f"{safe_name}.%(ext)s")
        return str(output_dir / "%(title)s.%(ext)s")

    def resolve_output_path(self, output_dir: Path) -> Path:
        requested_name = self.filename_input.text().strip()
        if requested_name:
            filename = self.sanitize_filename(requested_name)
        elif self.video_title:
            filename = self.sanitize_filename(self.video_title)
        else:
            filename = "download"
        return output_dir / f"{filename}.mp4"

    def sanitize_filename(self, value: str) -> str:
        invalid_chars = '<>:"/\\|?*'
        sanitized = "".join("_" if char in invalid_chars else char for char in value).strip()
        return sanitized.rstrip(". ") or "clip"

    def is_frozen(self) -> bool:
        return bool(getattr(sys, "frozen", False))


def main() -> None:
    configure_ssl_environment()
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
