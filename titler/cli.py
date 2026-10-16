"""Command line interface: ``titler <config.yaml>``."""
from __future__ import annotations

import argparse
import re
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from .config import ConfigError, load_config
from .render import SlideRenderer
from .video import encode


def slide_filename(slide: dict, ext: str) -> str:
    safe = re.sub(r"[^\w\-]+", "_", slide["name"]).strip("_") or "slide"
    return f"{slide['index'] + 1:02d}_{safe}.{ext}"


def _render_one(project: dict, slide: dict, preview_at, quiet: bool) -> str:
    renderer = SlideRenderer(slide, project["video"], project["base_dir"])
    out_dir = Path(project["output_dir"])
    if preview_at is not None:
        t = renderer.duration - renderer.fade_out - 1 / renderer.fps if preview_at == "end" else float(preview_at)
        index = min(renderer.frame_count - 1, max(0, round(t * renderer.fps)))
        out = out_dir / slide_filename(slide, "png")
        out.parent.mkdir(parents=True, exist_ok=True)
        renderer.render(index).save(out)
        return f"{out}  (frame at {index / renderer.fps:.2f}s)"

    out = out_dir / slide_filename(slide, "mp4")
    started = time.perf_counter()

    def progress(done, total):
        if not quiet and (done == total or done % 15 == 0):
            print(f"\r  {slide['name']}: {done}/{total} frames", end="", flush=True)

    encode(renderer, out, project["video"], progress)
    if not quiet:
        print()
    return f"{out}  ({renderer.duration:.2f}s, {renderer.frame_count} frames, " \
           f"rendered in {time.perf_counter() - started:.1f}s)"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="titler", description="Render animated typewriter title slides to MP4.")
    parser.add_argument("config", help="YAML (or JSON) project file")
    parser.add_argument("-s", "--slide", action="append", metavar="NAME",
                        help="render only this slide (repeatable)")
    parser.add_argument("-p", "--preview", nargs="?", const="end", metavar="SECONDS",
                        help="write a PNG still per slide instead of MP4 (default: last frame before fade-out)")
    parser.add_argument("-j", "--jobs", type=int, default=1, help="slides to render in parallel")
    args = parser.parse_args(argv)

    try:
        project = load_config(args.config)
    except (ConfigError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    slides = project["slides"]
    if args.slide:
        wanted = set(args.slide)
        missing = wanted - {s["name"] for s in slides}
        if missing:
            print(f"error: unknown slide(s): {sorted(missing)}", file=sys.stderr)
            return 2
        slides = [s for s in slides if s["name"] in wanted]

    try:
        if args.jobs > 1 and len(slides) > 1:
            with ProcessPoolExecutor(max_workers=args.jobs) as pool:
                futures = [pool.submit(_render_one, project, s, args.preview, True) for s in slides]
                for f in futures:
                    print(f.result())
        else:
            for s in slides:
                print(_render_one(project, s, args.preview, False))
    except (ConfigError, RuntimeError) as e:
        print(f"\nerror: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
