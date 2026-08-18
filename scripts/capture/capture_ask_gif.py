#!/usr/bin/env python3
"""Regenerate docs/assets/synapse-ask-knowledge-system.gif.

This captures the real Synapse Ask curses TUI inside a headless kitty terminal,
drives human-like typing with xdotool, records terminal pixels with ffmpeg, and
exports an optimized README-friendly GIF.

The capture uses a deterministic local Ask webhook harness for stable timing.
The JSON response matches the live Ask response shape and source-safe rendering
contract, but avoids a model-latency spike that would make the spinner exceed
three seconds.

Usage from the repository root:
    python3 scripts/capture/capture_ask_gif.py

Capture contract:
    - terminal size: 100x30-ish, rendered in a 1280x800 headless X display
    - typed question: What tools make up my knowledge system, and what are they used for?
    - initial loaded-TUI hold: 2.6s
    - human typing: deterministic per-character variation
    - backend thinking delay: 1.2s
    - final answer/source hold: 10.0s
    - raw video encoder: ``SYNAPSE_CAPTURE_ENCODER`` or portable ``mpeg4``
    - output: docs/assets/synapse-ask-knowledge-system.gif
"""

from __future__ import annotations

import http.server
import json
import os
import random
import shutil
import signal
import socket
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
OUTPUT_GIF = ROOT / "docs" / "assets" / "synapse-ask-knowledge-system.gif"
ARTIFACT_DIR = ROOT / ".local-artifacts" / "capture"
GENERATED_GIF = ARTIFACT_DIR / "synapse-ask-knowledge-system.generated.gif"
RAW_MP4 = ARTIFACT_DIR / "synapse-ask-knowledge-system.raw.mp4"
PALETTE = ARTIFACT_DIR / "synapse-ask-knowledge-system.palette.png"
CONTACT = ARTIFACT_DIR / "synapse-ask-knowledge-system.contact.png"
FIRST_FRAME = ARTIFACT_DIR / "synapse-ask-knowledge-system.first.png"
FINAL_FRAME = ARTIFACT_DIR / "synapse-ask-knowledge-system.final.png"
MID_FRAME = ARTIFACT_DIR / "synapse-ask-knowledge-system.answer.png"

DISPLAY_NUM = os.environ.get("SYNAPSE_CAPTURE_DISPLAY", "99")
DISPLAY = f":{DISPLAY_NUM}"
WIDTH = 1280
HEIGHT = 800
FPS = 30
GIF_FPS = 18
RAW_ENCODER = os.environ.get("SYNAPSE_CAPTURE_ENCODER", "mpeg4")
QUESTION = "What tools make up my knowledge system, and what are they used for?"
SOURCE_PATH = "Synapse-Demo/knowledge-system-notes.md"
WEBHOOK_TOKEN = "capture-demo-token"

INITIAL_HOLD_SECONDS = 2.6
SUBMIT_PAUSE_SECONDS = 0.35
BACKEND_DELAY_SECONDS = 1.2
FINAL_HOLD_SECONDS = 10.0
POST_SUBMIT_RECORD_SECONDS = BACKEND_DELAY_SECONDS + 1.2 + FINAL_HOLD_SECONDS


def require_tools() -> None:
    missing = [cmd for cmd in ("Xvfb", "kitty", "ffmpeg", "xdotool", "gifsicle", "magick") if not shutil.which(cmd)]
    if missing:
        raise SystemExit(f"Missing required capture tools: {', '.join(missing)}")


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class AskHarness(http.server.ThreadingHTTPServer):
    daemon_threads = True


class AskHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - stdlib API
        parsed = urlparse(self.path)
        if parsed.path not in {"/webhook/synapse/ask", "/ask"}:
            self.send_error(404)
            return
        token = self.headers.get("X-Synapse-Token") or ""
        if token != WEBHOOK_TOKEN:
            self._json(401, {"error_code": "unauthorized", "error": "unauthorized"})
            return
        length = int(self.headers.get("Content-Length") or "0")
        body = json.loads(self.rfile.read(length) or b"{}")
        question = str(body.get("question") or "")
        source_path = str(body.get("source_path") or "")
        time.sleep(BACKEND_DELAY_SECONDS)
        if question != QUESTION or (source_path and source_path != SOURCE_PATH):
            payload = {
                "question": question,
                "answer": "I do not have enough indexed note context to answer that reliably.",
                "insufficient_context": True,
                "sources": [],
                "citations": [],
            }
        else:
            payload = {
                "question": QUESTION,
                "answer": "Markdown notes are the source of truth; Synapse coordinates note intake and questions, Ollama provides local models, Qdrant stores searchable vectors, Wiki.js publishes readable copies, and Ask provides the terminal interface. [1]",
                "insufficient_context": False,
                "sources": [
                    {
                        "title": "My Knowledge System",
                        "source_path": SOURCE_PATH,
                        "wiki_path": "/synapse-demo/knowledge-system-notes",
                        "note_id": "4f732329-46eb-5692-bed4-290890901e2c",
                        "chunk_index": 0,
                        "quoted_support": "Markdown notes are the source of truth. The Synapse FastAPI service coordinates note intake and questions. Ollama provides local formatting, embedding, and answer generation. Qdrant stores searchable vector chunks. Wiki.js stores a readable published copy. The Ask CLI/TUI is the terminal interface for questions.",
                    }
                ],
                "retrieval": {
                    "accepted": 1,
                    "filtered_for_grounding": True,
                    "answer_validation": "capture_harness",
                },
            }
        self._json(200, payload)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - stdlib method name.
        return

    def _json(self, status: int, payload: dict[str, object]) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def start_harness(port: int) -> tuple[AskHarness, threading.Thread]:
    server = AskHarness(("127.0.0.1", port), AskHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def run(cmd: list[str], *, env: dict[str, str] | None = None, timeout: int | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(cmd, env=env, text=True, capture_output=True, timeout=timeout)
    if check and result.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd)}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")
    return result


def wait_for_window(env: dict[str, str]) -> str:
    deadline = time.time() + 15
    while time.time() < deadline:
        result = run(["xdotool", "search", "--name", "Synapse Ask Demo"], env=env, check=False)
        ids = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if ids:
            return ids[-1]
        time.sleep(0.2)
    raise RuntimeError("kitty window did not appear")


def type_question(window_id: str, env: dict[str, str]) -> None:
    random.seed(42)
    for char in QUESTION:
        run(["xdotool", "type", "--window", window_id, "--delay", "0", "--", char], env=env)
        delay = random.uniform(0.040, 0.105)
        if char == " ":
            delay += 0.115
        elif char in {"?", ".", ","}:
            delay += 0.080
        time.sleep(delay)


def extract_frames() -> None:
    # First frame, middle/answer frame, and final frame for manual/automated inspection.
    run(["ffmpeg", "-y", "-i", str(RAW_MP4), "-vf", "select=eq(n\\,0)", "-frames:v", "1", str(FIRST_FRAME)], timeout=30)
    run(["ffmpeg", "-y", "-ss", "5.5", "-i", str(RAW_MP4), "-frames:v", "1", str(MID_FRAME)], timeout=30)
    run(["ffmpeg", "-y", "-sseof", "-0.2", "-i", str(RAW_MP4), "-frames:v", "1", str(FINAL_FRAME)], timeout=30)
    run([
        "magick",
        str(FIRST_FRAME),
        str(MID_FRAME),
        str(FINAL_FRAME),
        "+append",
        str(CONTACT),
    ], timeout=30)


def frame_mean(path: Path) -> float:
    result = run(["magick", str(path), "-colorspace", "Gray", "-format", "%[fx:mean]", "info:"], timeout=30)
    return float(result.stdout.strip())


def render_gif() -> None:
    run([
        "ffmpeg", "-y", "-i", str(RAW_MP4),
        "-vf", f"fps={GIF_FPS},scale=1080:-1:flags=lanczos,palettegen",
        str(PALETTE),
    ], timeout=60)
    run([
        "ffmpeg", "-y", "-i", str(RAW_MP4), "-i", str(PALETTE),
        "-lavfi", f"fps={GIF_FPS},scale=1080:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=4",
        str(GENERATED_GIF),
    ], timeout=60)
    run(["gifsicle", "--optimize=3", "--colors", "256", "--lossy=60", str(GENERATED_GIF), "-o", str(GENERATED_GIF)], timeout=60)
    os.replace(GENERATED_GIF, OUTPUT_GIF)


def main() -> int:
    require_tools()
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_GIF.parent.mkdir(parents=True, exist_ok=True)

    port = free_port()
    server, _thread = start_harness(port)
    env = os.environ.copy()
    env.update({
        "DISPLAY": DISPLAY,
        "TERM": "xterm-256color",
        "LIBGL_ALWAYS_SOFTWARE": "1",
        "SYNAPSE_ASK_WEBHOOK_URL": f"http://127.0.0.1:{port}/webhook/synapse/ask",
        "SYNAPSE_WEBHOOK_AUTH_TOKEN": WEBHOOK_TOKEN,
    })

    xvfb = subprocess.Popen(["Xvfb", DISPLAY, "-screen", "0", f"{WIDTH}x{HEIGHT}x24"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    kitty = None
    ffmpeg = None
    try:
        time.sleep(0.5)
        run(["xsetroot", "-solid", "#0b1220"], env=env, check=False)

        tui_cmd = (
            f"cd {shlex_quote(str(ROOT))}; "
            "printf '\\033[?25l'; "
            f"python3 Ask/ask.py --source-path {shlex_quote(SOURCE_PATH)}"
        )
        kitty = subprocess.Popen([
            "kitty", "--config", "NONE",
            "--override", "font_family=JetBrains Mono",
            "--override", "font_size=14.0",
            "--override", "background=#0b1220",
            "--override", "foreground=#e6edf3",
            "--override", "cursor=#0b1220",
            "--override", "cursor_text_color=#0b1220",
            "--override", "window_padding_width=16",
            "--override", "remember_window_size=no",
            "--override", f"initial_window_width={WIDTH}",
            "--override", f"initial_window_height={HEIGHT}",
            "--title", "Synapse Ask Demo",
            "bash", "-lc", tui_cmd,
        ], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        window_id = wait_for_window(env)
        run(["xdotool", "windowmove", window_id, "0", "0"], env=env, check=False)
        run(["xdotool", "windowsize", window_id, str(WIDTH), str(HEIGHT)], env=env, check=False)
        run(["xdotool", "windowactivate", window_id], env=env, check=False)
        time.sleep(1.4)  # loaded TUI visible before capture starts

        ffmpeg = subprocess.Popen([
            "ffmpeg", "-loglevel", "error", "-y",
            "-f", "x11grab",
            "-draw_mouse", "0",
            "-framerate", str(FPS),
            "-video_size", f"{WIDTH}x{HEIGHT}",
            "-i", DISPLAY,
            # Fedora's ffmpeg build may omit libx264. The intermediate MP4 only
            # feeds GIF conversion, so use a portable encoder by default while
            # allowing CI or a workstation to override it.
            "-codec:v", RAW_ENCODER,
            "-q:v", "3",
            "-pix_fmt", "yuv420p",
            str(RAW_MP4),
        ], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, env=env)

        time.sleep(INITIAL_HOLD_SECONDS)
        type_question(window_id, env)
        time.sleep(SUBMIT_PAUSE_SECONDS)
        run(["xdotool", "key", "--window", window_id, "Return"], env=env)
        time.sleep(POST_SUBMIT_RECORD_SECONDS)

        if ffmpeg.stdin:
            # ffmpeg may stop itself after an X11/display error. Treat a closed
            # stdin as a recorder failure to report after collecting stderr.
            try:
                ffmpeg.stdin.write("q\n")
                ffmpeg.stdin.flush()
            except BrokenPipeError:
                pass
        ffmpeg.wait(timeout=15)
        if ffmpeg.returncode != 0:
            detail = ffmpeg.stderr.read().strip() if ffmpeg.stderr else ""
            raise RuntimeError(f"ffmpeg screen capture failed (exit {ffmpeg.returncode}): {detail}")
        if ffmpeg.stderr:
            ffmpeg.stderr.close()
        ffmpeg = None

        extract_frames()
        render_gif()

        first_mean = frame_mean(FIRST_FRAME)
        final_mean = frame_mean(FINAL_FRAME)
        if first_mean < 0.01 or final_mean < 0.01:
            raise RuntimeError("first/final frame appears black")

        print("Capture complete")
        print(f"  GIF: {OUTPUT_GIF} ({OUTPUT_GIF.stat().st_size / 1024:.0f} KB)")
        print(f"  Raw MP4: {RAW_MP4}")
        print(f"  Contact sheet: {CONTACT}")
        print(f"  Terminal/display: {WIDTH}x{HEIGHT}, kitty JetBrains Mono 14, GIF {GIF_FPS} fps")
        print(f"  Timing: initial {INITIAL_HOLD_SECONDS}s, backend {BACKEND_DELAY_SECONDS}s, final hold {FINAL_HOLD_SECONDS}s")
        return 0
    finally:
        server.shutdown()
        if ffmpeg and ffmpeg.poll() is None:
            ffmpeg.send_signal(signal.SIGINT)
            try:
                ffmpeg.wait(timeout=5)
            except subprocess.TimeoutExpired:
                ffmpeg.kill()
        if kitty and kitty.poll() is None:
            kitty.terminate()
            try:
                kitty.wait(timeout=5)
            except subprocess.TimeoutExpired:
                kitty.kill()
        if xvfb.poll() is None:
            xvfb.terminate()
            try:
                xvfb.wait(timeout=5)
            except subprocess.TimeoutExpired:
                xvfb.kill()


def shlex_quote(value: str) -> str:
    import shlex
    return shlex.quote(value)


if __name__ == "__main__":
    raise SystemExit(main())
