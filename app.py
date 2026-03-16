import importlib
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from PySide6.QtCore import QObject, QThread, Qt, Signal, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
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


APP_TITLE = "MerchTools - Video Downloader"
DEFAULT_OUTPUT_DIR = Path.cwd() / "downloads"
REQUIRED_PYTHON_PACKAGES = [
    ("yt_dlp", "yt-dlp"),
    ("imageio_ffmpeg", "imageio-ffmpeg"),
]


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


class ProgressButton(QPushButton):
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._progress = 0
        self._show_progress = False

    def set_progress_state(self, active: bool, value: int = 0) -> None:
        self._show_progress = active
        self._progress = max(0, min(100, value))
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect().adjusted(0, 0, -1, -1)
        radius = 12
        bg = QColor("#1b1f23") if self.isEnabled() else QColor("#171a1d")
        border = QColor("#2a2e33") if self.isEnabled() else QColor("#22262a")
        text_color = QColor("#efe8dd") if self.isEnabled() else QColor("#7d766d")

        painter.setPen(QPen(border, 1))
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, radius, radius)

        if self._show_progress:
            border = QColor("#ff9a55")
            text_color = QColor("#efe8dd")
        if self._show_progress and self._progress > 0:
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
        if self._show_progress:
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
    def __init__(self, command: list[str], url: str) -> None:
        super().__init__()
        self.command = command
        self.url = url

    def run(self) -> None:
        self.set_status("Fetching video info...")
        self.log(f"Fetching info for: {self.url}")
        args = self.command + [
            "--dump-single-json",
            "--no-playlist",
            "--force-ipv4",
            "--socket-timeout",
            "30",
            "--retries",
            "10",
            "--extractor-retries",
            "5",
            "--fragment-retries",
            "10",
            self.url,
        ]

        for attempt in range(1, 4):
            try:
                result = subprocess.run(
                    args,
                    capture_output=True,
                    text=True,
                    check=True,
                    encoding="utf-8",
                    errors="replace",
                )
                data = json.loads(result.stdout)
                self.signals.finished.emit(data)
                return
            except subprocess.CalledProcessError as error:
                stderr = error.stderr.strip() or "yt-dlp could not load the video."
                self.log(stderr)
                if "WinError 10054" in stderr and "twitch" in self.url.lower() and attempt < 3:
                    self.log(f"Twitch metadata request dropped. Retrying ({attempt}/2)...")
                    time.sleep(1.5 * attempt)
                    continue
                self.emit_error(stderr)
                return
            except json.JSONDecodeError:
                message = "yt-dlp returned invalid metadata."
                self.log(message)
                self.emit_error(message)
                return


class DownloadWorker(BaseWorker):
    def __init__(self, args: list[str], expected_duration: int | None = None) -> None:
        super().__init__()
        self.args = args
        self.expected_duration = expected_duration
        self.progress_pattern = re.compile(r"\[download\]\s+(\d+(?:\.\d+)?)%")
        self.ffmpeg_time_pattern = re.compile(r"time=(\d{2}:\d{2}:\d{2}(?:\.\d+)?)")

    def run(self) -> None:
        self.set_status("Downloading...")
        self.signals.progress.emit(0)
        self.log("Starting download...")
        self.log(" ".join(f'"{arg}"' if " " in arg else arg for arg in self.args))

        last_error = "Download failed. Check the activity log for details."
        for attempt in range(1, 4):
            process = subprocess.Popen(
                self.args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )

            full_output: list[str] = []
            assert process.stdout is not None
            for line in process.stdout:
                clean_line = line.rstrip()
                if clean_line:
                    full_output.append(clean_line)
                    self.log(clean_line)
                    match = self.progress_pattern.search(clean_line)
                    if match:
                        percentage = int(float(match.group(1)))
                        self.signals.progress.emit(max(0, min(100, percentage)))
                        continue
                    ffmpeg_match = self.ffmpeg_time_pattern.search(clean_line)
                    if ffmpeg_match and self.expected_duration:
                        current_seconds = parse_clock_value(ffmpeg_match.group(1))
                        percentage = int((current_seconds / self.expected_duration) * 100)
                        self.signals.progress.emit(max(0, min(100, percentage)))

            exit_code = process.wait()
            if exit_code == 0:
                self.log("Download finished.")
                self.signals.progress.emit(100)
                self.signals.finished.emit({"ok": True})
                return

            last_error = full_output[-1] if full_output else f"Download failed with exit code {exit_code}."
            self.log(f"Download failed with exit code {exit_code}.")
            if "WinError 10054" in last_error and any("twitch" in arg.lower() for arg in self.args) and attempt < 3:
                self.log(f"Twitch request dropped. Retrying download ({attempt}/2)...")
                self.signals.progress.emit(0)
                time.sleep(1.5 * attempt)
                continue
            self.emit_error(last_error)
            return


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


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1120, 760)
        self.setMinimumSize(980, 760)

        DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        self.dependencies_ready = False
        self.is_fetching_info = False
        self.is_downloading = False
        self.video_duration: int | None = None
        self.video_title = ""
        self.last_auto_filename = ""
        self.ffmpeg_path: str | None = None
        self.active_thread: QThread | None = None
        self.active_worker: BaseWorker | None = None
        self.last_fetched_url = ""
        self.last_output_path: Path | None = None
        self.url_fetch_timer = QTimer(self)
        self.url_fetch_timer.setInterval(1100)
        self.url_fetch_timer.setSingleShot(True)
        self.url_fetch_timer.timeout.connect(self.fetch_info_if_ready)

        self.setFont(QFont("Segoe UI", 10))
        self.setStyleSheet(self.build_stylesheet())
        self.build_ui()
        self.update_button_state()
        self.append_log("Ready. Paste a YouTube or Twitch link, choose full video or enter a clip range, then download.")
        self.start_dependency_check()

    def build_ui(self) -> None:
        root = QWidget()
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
        top_row.addLayout(brand_wrap, 1)

        eyebrow = QLabel("MerchTools")
        eyebrow.setObjectName("eyebrow")
        brand_wrap.addWidget(eyebrow)

        title = QLabel("Video Downloader")
        title.setObjectName("heroTitle")
        brand_wrap.addWidget(title)
        top_row.addStretch(1)

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
        self.output_dir_input = QLineEdit(str(DEFAULT_OUTPUT_DIR))
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
        self.start_input.setPlaceholderText("9:32")
        self.end_input = QLineEdit()
        self.end_input.setObjectName("timeInput")
        self.end_input.setPlaceholderText("9:43")

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
        clip_card.content_layout.addWidget(self.reveal_checkbox)

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

    def build_stylesheet(self) -> str:
        return """
        QWidget {
            background: #131516;
            color: #efe8dd;
        }
        QMainWindow {
            background: #131516;
        }
        QFrame#card {
            background: transparent;
            border: 1px solid #2a2e33;
            border-radius: 20px;
        }
        QLabel#eyebrow {
            color: #cbbda8;
            font-size: 12px;
            font-weight: 600;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }
        QLabel#heroTitle {
            font-family: "Trebuchet MS";
            font-size: 32px;
            font-weight: 700;
        }
        QLabel#hintText, QLabel#metaText {
            color: #cbbda8;
            line-height: 1.4;
        }
        QCheckBox#optionToggle {
            color: #efe8dd;
            spacing: 10px;
            font-size: 13px;
        }
        QCheckBox#optionToggle::indicator {
            width: 18px;
            height: 18px;
            border-radius: 5px;
            border: 1px solid #3a4148;
            background: #171a1d;
        }
        QCheckBox#optionToggle::indicator:checked {
            background: #ff9a55;
            border: 1px solid #ff9a55;
        }
        QLabel#cardTitle {
            color: #efe8dd;
            font-family: "Trebuchet MS";
            font-size: 20px;
            font-weight: 700;
        }
        QLabel#fieldLabel {
            color: #efe8dd;
            font-size: 12px;
            font-weight: 600;
            letter-spacing: 0.04em;
        }
        QLineEdit, QPlainTextEdit {
            background: #171a1d;
            border: 1px solid #2a2e33;
            border-radius: 12px;
            padding: 12px 14px;
            color: #efe8dd;
            selection-background-color: #ff9a55;
            selection-color: #1a1613;
        }
        QLineEdit#primaryInput {
            font-size: 14px;
            font-weight: 600;
            min-height: 26px;
            background: #1b1f23;
            border: 1px solid #3a4148;
        }
        QLineEdit#timeInput {
            min-height: 24px;
            font-size: 13px;
        }
        QLineEdit:disabled {
            background: #101214;
            color: #72767c;
            border: 1px solid #262a2f;
        }
        QLineEdit:focus, QPlainTextEdit:focus {
            border: 1px solid #ff9a55;
        }
        QPushButton {
            background: #1b1f23;
            color: #efe8dd;
            border: 1px solid #2a2e33;
            border-radius: 12px;
            padding: 12px 16px;
            font-weight: 600;
        }
        QPushButton:hover {
            background: #23282d;
        }
        QPushButton:disabled {
            background: #171a1d;
            color: #7d766d;
            border-color: #22262a;
        }
        QPushButton#accentButton {
            font-size: 14px;
            font-weight: 700;
            padding: 13px 18px;
        }
        QPlainTextEdit#logOutput {
            font-family: Consolas, monospace;
            font-size: 13px;
        }
        """

    def make_field_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("fieldLabel")
        return label

    def append_log(self, message: str) -> None:
        self.log_output.appendPlainText(message)
        self.log_output.verticalScrollBar().setValue(self.log_output.verticalScrollBar().maximum())

    def set_status(self, text: str) -> None:
        if text != "Downloading...":
            self.download_button.set_progress_state(False, 0)

    def set_progress(self, value: int) -> None:
        self.download_button.set_progress_state(True, max(0, min(100, value)))

    def choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose Save Folder", self.output_dir_input.text())
        if folder:
            self.output_dir_input.setText(folder)

    def on_full_video_toggled(self, checked: bool) -> None:
        self.start_input.setDisabled(checked)
        self.end_input.setDisabled(checked)

    def on_url_changed(self, _: str) -> None:
        self.video_meta.setText("Title: -\nDuration: -")
        self.video_duration = None
        self.video_title = ""
        self.last_fetched_url = ""
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

        command = self.resolve_yt_dlp_command()
        if not command:
            return

        self.is_fetching_info = True
        self.set_status("Fetching video info...")
        self.update_button_state()
        self.append_log("Starting metadata lookup...")
        worker = InfoWorker(command, url)
        self.run_worker(
            worker,
            self.on_info_loaded,
            lambda message: self.on_worker_error(message, "Ready"),
        )

    def download_video(self) -> None:
        if not self.dependencies_ready or self.is_fetching_info or self.is_downloading:
            self.show_error("The app is still preparing or processing. Please wait a moment.")
            return

        url = self.apply_normalized_url()
        if not url:
            self.show_error("Paste a YouTube or Twitch URL first.")
            return

        output_dir = Path(self.output_dir_input.text().strip() or DEFAULT_OUTPUT_DIR)
        output_dir.mkdir(parents=True, exist_ok=True)
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
        command = self.resolve_yt_dlp_command(require_ffmpeg=True)
        if not command or not ffmpeg_path:
            return

        args = command + [
            "--no-playlist",
            "--newline",
            "--force-ipv4",
            "--socket-timeout",
            "30",
            "--retries",
            "10",
            "--extractor-retries",
            "5",
            "--fragment-retries",
            "10",
            "--format",
            "bestvideo*+bestaudio/best",
            "--merge-output-format",
            "mp4",
            "--ffmpeg-location",
            ffmpeg_path,
            "--output",
            self.build_output_template(output_dir),
        ]

        expected_duration: int | None = self.video_duration
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
            args.extend(["--download-sections", section_value, "--force-keyframes-at-cuts"])
        else:
            self.append_log("Full video mode enabled.")

        args.append(url)

        self.is_downloading = True
        self.set_progress(0)
        self.set_status("Downloading...")
        self.update_button_state()
        self.append_log("Starting download worker...")
        worker = DownloadWorker(args, expected_duration=expected_duration)
        self.run_worker(
            worker,
            self.on_download_finished,
            lambda message: self.on_worker_error(message, "Ready"),
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
        suggested_filename = self.sanitize_filename(title)
        current_filename = self.filename_input.text().strip()
        if not current_filename or current_filename == self.last_auto_filename:
            self.filename_input.setText(suggested_filename)
            self.last_auto_filename = suggested_filename
        self.append_log(f"Loaded video: {title}")
        self.append_log(f"Duration: {format_seconds(self.video_duration)}")
        self.update_button_state()

    def on_download_finished(self, _: object) -> None:
        self.is_downloading = False
        self.set_progress(100)
        self.set_status("Ready")
        self.update_button_state()
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

    def on_worker_error(self, message: str, status: str) -> None:
        self.is_fetching_info = False
        self.is_downloading = False
        self.set_status(status)
        self.update_button_state()
        self.show_error(message)

    def on_thread_finished(self) -> None:
        self.active_thread = None
        self.active_worker = None

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
            and not self.is_downloading
            and bool(self.url_input.text().strip())
        )
        self.download_button.setDisabled(not can_download)

    def reveal_in_explorer(self) -> None:
        output_dir = Path(self.output_dir_input.text().strip() or DEFAULT_OUTPUT_DIR)
        if not output_dir.exists():
            return
        subprocess.Popen(["explorer.exe", str(output_dir)])

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
            return

        self.update_button_state()
        worker = DependencyWorker()
        self.run_worker(
            worker,
            self.on_dependencies_ready,
            lambda message: self.on_worker_error(message, "Setup failed"),
        )

    def run_worker(self, worker: BaseWorker, success_handler, error_handler) -> None:
        thread = QThread(self)
        worker.moveToThread(thread)
        self.active_thread = thread
        self.active_worker = worker
        worker.signals.log.connect(self.append_log)
        worker.signals.status.connect(self.set_status)
        worker.signals.progress.connect(self.set_progress)
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

    def resolve_yt_dlp_command(self, require_ffmpeg: bool = False) -> list[str] | None:
        module_spec = shutil.which("yt-dlp")
        if self.python_has_yt_dlp():
            command = [sys.executable, "-m", "yt_dlp"]
        elif module_spec:
            command = [module_spec]
        else:
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


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
