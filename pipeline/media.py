"""ffmpeg / OpenCV helpers.

Text is burned in with OpenCV rather than ffmpeg `drawtext`, because common ffmpeg
builds (including Homebrew's default) ship without libfreetype.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import cv2
import numpy as np

TARGET_W, TARGET_H, TARGET_FPS = 1280, 720, 30


def require(bin_name: str) -> str:
    path = shutil.which(bin_name)
    if not path:
        raise SystemExit(f"{bin_name} not found on PATH (brew install ffmpeg)")
    return path


def run(args: list[str]) -> None:
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        [require("ffprobe"), "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    return float(out)


def cut_clip(src: Path, start: float, end: float, out: Path) -> Path:
    """Frame-accurate cut (re-encoded) of [start, end] seconds."""
    out.parent.mkdir(parents=True, exist_ok=True)
    run([
        require("ffmpeg"), "-y", "-ss", f"{max(0.0, start):.2f}", "-i", str(src),
        "-t", f"{max(0.5, end - start):.2f}", "-an",
        # 480p keeps base64 uploads to the verifier small.
        "-vf", "scale=-2:480",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", str(out),
    ])
    return out


class VideoWriter:
    """Pipe BGR frames into ffmpeg/libx264 (browser-playable, unlike cv2's mp4v)."""

    def __init__(self, out: Path, width: int, height: int, fps: float):
        out.parent.mkdir(parents=True, exist_ok=True)
        self.proc = subprocess.Popen(
            [require("ffmpeg"), "-y", "-loglevel", "error",
             "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{width}x{height}", "-r", f"{fps:.3f}",
             "-i", "-", "-an", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
             "-movflags", "+faststart", str(out)],
            stdin=subprocess.PIPE,
        )

    def write(self, frame: np.ndarray) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(frame.tobytes())

    def close(self) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.close()
        if self.proc.wait() != 0:
            raise RuntimeError("ffmpeg encoder failed")


def mmss(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 60:02d}:{s % 60:02d}"


def draw_banner(frame: np.ndarray, text: str, *, top: bool = True, scale: float = 0.6) -> None:
    h, w = frame.shape[:2]
    font = cv2.FONT_HERSHEY_SIMPLEX
    (tw, th), base = cv2.getTextSize(text, font, scale, 1)
    pad = 8
    y0 = 0 if top else h - th - base - 2 * pad
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, y0), (min(w, tw + 2 * pad), y0 + th + base + 2 * pad), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)
    cv2.putText(frame, text, (pad, y0 + pad + th), font, scale, (255, 255, 255), 1, cv2.LINE_AA)


def render_label_png(lines: list[str], out: Path, width: int = TARGET_W) -> Path:
    """Transparent lower-third PNG for ffmpeg's `overlay` filter (used by the review reel)."""
    font = cv2.FONT_HERSHEY_SIMPLEX
    line_h, pad = 30, 14
    h = pad * 2 + line_h * len(lines)
    img = np.zeros((h, width, 4), dtype=np.uint8)
    img[:, :, 3] = 170
    for i, line in enumerate(lines):
        scale = 0.75 if i == 0 else 0.55
        color = (255, 255, 255, 255) if i == 0 else (210, 210, 210, 255)
        cv2.putText(img, line, (pad, pad + 22 + i * line_h), font, scale, color, 1 if i else 2, cv2.LINE_AA)
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), img)
    return out


def sample_frames(src: Path, start: float, end: float, n: int) -> list[np.ndarray]:
    cap = cv2.VideoCapture(str(src))
    frames = []
    for i in range(n):
        t = start + (end - start) * (i + 0.5) / n
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        if ok:
            frames.append(frame)
    cap.release()
    return frames
