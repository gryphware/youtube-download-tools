#!/usr/bin/env python3
"""YouTube downloader TUI — paste a link, pick format/quality, choose save path."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path

from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import Screen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    ProgressBar,
    RadioButton,
    RadioSet,
)


class Step(Enum):
    URL = auto()
    FORMAT = auto()
    QUALITY = auto()
    PATH = auto()
    DOWNLOAD = auto()


MP3_CHOICES = [
    ("high", "High quality (320 kbps)"),
    ("mid", "Mid quality (192 kbps)"),
    ("low", "Low quality (128 kbps)"),
]

MP4_CHOICES = [
    ("360", "360p"),
    ("480", "480p"),
    ("720", "720p"),
    ("1080", "1080p"),
]


@dataclass
class DownloadJob:
    url: str = ""
    fmt: str = ""  # "mp3" or "mp4"
    quality: str = ""
    output_dir: str = ""


def build_ytdlp_command(job: DownloadJob) -> list[str]:
    out_template = str(Path(job.output_dir) / "%(title)s.%(ext)s")
    cmd = ["yt-dlp", job.url, "-o", out_template, "--no-playlist", "--progress"]

    if job.fmt == "mp3":
        cmd += ["-x", "--audio-format", "mp3"]
        bitrate = {"high": "320k", "mid": "192k", "low": "128k"}.get(job.quality, "192k")
        cmd += ["--postprocessor-args", f"ffmpeg:-b:a {bitrate}"]
    else:
        height = job.quality
        fmt = (
            f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/"
            f"best[height<={height}][ext=mp4]/best[height<={height}]"
        )
        cmd += ["-f", fmt, "--merge-output-format", "mp4"]

    return cmd


class DownloaderScreen(Screen):
    BINDINGS = [("escape", "back", "Back"), ("ctrl+c", "quit", "Quit")]

    CSS = """
    Screen {
        align: center middle;
    }

    #wizard {
        width: 72;
        height: auto;
        max-height: 90%;
        border: round $accent;
        padding: 1 2;
        background: $surface;
    }

    #title {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }

    #step-label {
        color: $text-muted;
        margin-bottom: 1;
    }

    #hint {
        color: $text-muted;
        margin-top: 1;
    }

    #error {
        color: $error;
        margin-top: 1;
    }

    RadioSet {
        margin: 1 0;
        height: auto;
    }

    #url-input, #path-input {
        margin: 1 0;
    }

    #actions {
        margin-top: 1;
        height: auto;
        align: right middle;
    }

    #actions Button {
        margin-left: 1;
    }

    #progress-area {
        margin-top: 1;
    }

    #status {
        margin-top: 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.step = Step.URL
        self.job = DownloadJob()
        self.error_message = ""

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Container(id="wizard"):
            yield Label("YouTube Downloader", id="title")
            yield Label("", id="step-label")
            yield Container(id="content")
            yield Label("", id="error")
            with Horizontal(id="actions"):
                yield Button("Back", id="back-btn", variant="default", disabled=True)
                yield Button("Next", id="next-btn", variant="primary")
        yield Footer()

    async def on_mount(self) -> None:
        await self.render_step()

    async def render_step(self) -> None:
        content = self.query_one("#content", Container)
        step_label = self.query_one("#step-label", Label)
        error = self.query_one("#error", Label)
        back_btn = self.query_one("#back-btn", Button)
        next_btn = self.query_one("#next-btn", Button)

        error.update(self.error_message)
        back_btn.disabled = self.step == Step.URL or self.step == Step.DOWNLOAD

        if self.step == Step.URL:
            step_label.update("Step 1 of 4 — Paste YouTube link")
            next_btn.label = "Next"
            await content.mount(
                Input(placeholder="https://www.youtube.com/watch?v=...", id="url-input"),
                Label("Paste a YouTube video or playlist URL.", id="hint"),
            )
            self.query_one("#url-input", Input).focus()

        elif self.step == Step.FORMAT:
            step_label.update("Step 2 of 4 — Choose format")
            next_btn.label = "Next"
            await content.mount(
                Label("Download as:", id="hint"),
                RadioSet(
                    RadioButton("MP3 (audio only)", id="fmt-mp3", value=True),
                    RadioButton("MP4 (video)", id="fmt-mp4"),
                    id="format-choice",
                ),
            )

        elif self.step == Step.QUALITY:
            if self.job.fmt == "mp3":
                step_label.update("Step 3 of 4 — Choose audio quality")
                buttons = [
                    RadioButton(label, id=f"q-{key}", value=i == 0)
                    for i, (key, label) in enumerate(MP3_CHOICES)
                ]
            else:
                step_label.update("Step 3 of 4 — Choose video quality")
                buttons = [
                    RadioButton(label, id=f"q-{key}", value=i == 0)
                    for i, (key, label) in enumerate(MP4_CHOICES)
                ]
            next_btn.label = "Next"
            await content.mount(RadioSet(*buttons, id="quality-choice"))

        elif self.step == Step.PATH:
            step_label.update("Step 4 of 4 — Download location")
            next_btn.label = "Download"
            default_path = str(Path.home() / "Downloads")
            await content.mount(
                Input(value=default_path, placeholder="/path/to/save/files", id="path-input"),
                Label("Folder where the file will be saved.", id="hint"),
            )
            self.query_one("#path-input", Input).focus()

        elif self.step == Step.DOWNLOAD:
            step_label.update("Downloading…")
            next_btn.disabled = True
            await content.mount(
                Label(f"URL: {self.job.url}", id="hint"),
                Label(
                    f"Format: {self.job.fmt.upper()} · Quality: {self.job.quality}"
                    + ("p" if self.job.fmt == "mp4" else ""),
                ),
                Label(f"Save to: {self.job.output_dir}"),
                ProgressBar(total=100, id="progress-bar"),
                Label("Starting…", id="status"),
            )
            self.start_download()

    async def clear_content(self) -> None:
        content = self.query_one("#content", Container)
        await content.remove_children()

    def validate_current_step(self) -> bool:
        self.error_message = ""

        if self.step == Step.URL:
            url = self.query_one("#url-input", Input).value.strip()
            if not url:
                self.error_message = "Please paste a YouTube URL."
                return False
            if "youtube.com" not in url and "youtu.be" not in url:
                self.error_message = "That doesn't look like a YouTube link."
                return False
            self.job.url = url

        elif self.step == Step.FORMAT:
            fmt_set = self.query_one("#format-choice", RadioSet)
            pressed = fmt_set.pressed_button
            if pressed is None:
                self.error_message = "Choose MP3 or MP4."
                return False
            self.job.fmt = "mp3" if pressed.id == "fmt-mp3" else "mp4"

        elif self.step == Step.QUALITY:
            quality_set = self.query_one("#quality-choice", RadioSet)
            pressed = quality_set.pressed_button
            if pressed is None:
                self.error_message = "Choose a quality option."
                return False
            self.job.quality = pressed.id.removeprefix("q-")

        elif self.step == Step.PATH:
            path_str = self.query_one("#path-input", Input).value.strip()
            if not path_str:
                self.error_message = "Please enter a download folder path."
                return False
            path = Path(path_str).expanduser()
            if not path.exists():
                self.error_message = f"Path does not exist: {path}"
                return False
            if not path.is_dir():
                self.error_message = f"Path is not a folder: {path}"
                return False
            self.job.output_dir = str(path.resolve())

        return True

    async def advance_step(self) -> None:
        if not self.validate_current_step():
            self.query_one("#error", Label).update(self.error_message)
            return

        self.query_one("#error", Label).update("")
        steps = list(Step)
        current_idx = steps.index(self.step)
        if current_idx + 1 < len(steps):
            await self.clear_content()
            self.step = steps[current_idx + 1]
            await self.render_step()

    async def retreat_step(self) -> None:
        if self.step in (Step.URL, Step.DOWNLOAD):
            return
        steps = list(Step)
        current_idx = steps.index(self.step)
        await self.clear_content()
        self.step = steps[current_idx - 1]
        await self.render_step()

    @on(Button.Pressed, "#next-btn")
    async def on_next(self) -> None:
        if self.step == Step.DOWNLOAD:
            self.job = DownloadJob()
            self.step = Step.URL
            await self.clear_content()
            self.query_one("#next-btn", Button).label = "Next"
            await self.render_step()
            return
        await self.advance_step()

    @on(Button.Pressed, "#back-btn")
    async def on_back_button(self) -> None:
        await self.retreat_step()

    async def action_back(self) -> None:
        await self.retreat_step()

    @work(thread=True)
    def start_download(self) -> None:
        cmd = build_ytdlp_command(self.job)
        self.app.call_from_thread(self._set_status, f"Running: {' '.join(cmd[:4])} …")

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError:
            self.app.call_from_thread(self._download_failed, "yt-dlp not found. Install it first.")
            return

        assert process.stdout is not None
        last_line = ""
        for line in process.stdout:
            last_line = line.strip()
            if "[download]" in last_line and "%" in last_line:
                try:
                    pct = float(last_line.split("%")[0].split()[-1])
                    self.app.call_from_thread(self._set_progress, pct)
                except ValueError:
                    pass
            self.app.call_from_thread(self._set_status, last_line or "Downloading…")

        code = process.wait()
        if code == 0:
            self.app.call_from_thread(self._download_done)
        else:
            self.app.call_from_thread(self._download_failed, last_line or f"yt-dlp exited with code {code}")

    def _set_progress(self, pct: float) -> None:
        try:
            bar = self.query_one("#progress-bar", ProgressBar)
            bar.progress = pct
        except Exception:
            pass

    def _set_status(self, msg: str) -> None:
        try:
            self.query_one("#status", Label).update(msg[:120])
        except Exception:
            pass

    def _download_done(self) -> None:
        self.query_one("#status", Label).update("Done! File saved successfully.")
        self.query_one("#progress-bar", ProgressBar).progress = 100
        next_btn = self.query_one("#next-btn", Button)
        next_btn.disabled = False
        next_btn.label = "Download another"
        # Keep step at DOWNLOAD until user clicks "Download another"

    def _download_failed(self, msg: str) -> None:
        self.query_one("#status", Label).update(f"Failed: {msg}")
        back_btn = self.query_one("#back-btn", Button)
        next_btn = self.query_one("#next-btn", Button)
        back_btn.disabled = False
        next_btn.disabled = False
        next_btn.label = "Try again"
        self.step = Step.PATH


class YouTubeDownloaderApp(App):
    TITLE = "YouTube Downloader"
    CSS_PATH = None

    def on_mount(self) -> None:
        self.push_screen(DownloaderScreen())


def main() -> None:
    app = YouTubeDownloaderApp()
    app.run()


if __name__ == "__main__":
    main()
