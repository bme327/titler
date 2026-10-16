"""MP4 encoding by piping raw frames into ffmpeg."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        exe = shutil.which("ffmpeg")
        if not exe:
            raise RuntimeError("ffmpeg not found: pip install imageio-ffmpeg, or put ffmpeg on PATH")
        return exe


def encode(renderer, out_path: Path, video: dict, progress=None) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg_exe(), "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{renderer.width}x{renderer.height}", "-r", str(video["fps"]),
        "-i", "-",
        "-c:v", "libx264", "-preset", str(video["preset"]), "-crf", str(video["crf"]),
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        str(out_path),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for i in range(renderer.frame_count):
            proc.stdin.write(renderer.render(i).tobytes())
            if progress:
                progress(i + 1, renderer.frame_count)
        proc.stdin.close()
    except BrokenPipeError:
        pass
    except BaseException:
        proc.kill()
        proc.wait()
        raise
    err = proc.stderr.read().decode(errors="replace")
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg failed for {out_path.name}:\n{err}")
