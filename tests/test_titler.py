import textwrap

import pytest
from PIL import Image

from titler.cli import main
from titler.config import ConfigError, load_config
from titler.render import SlideRenderer
from titler.units import UnitError, parse_length


def write(tmp_path, name, content):
    p = tmp_path / name
    text = textwrap.dedent(content.replace("@VIDEO", ""))
    if "@VIDEO" in content:
        text = SMALL_VIDEO + "\n" + text
    p.write_text(text, encoding="utf-8")
    return p


SMALL_VIDEO = "video: {width: 320, height: 180, fps: 10}"


def test_parse_length():
    assert parse_length(120, 1000, 96) == 120
    assert parse_length("120px", 1000, 96) == 120
    assert parse_length("36pt", 1000, 96) == 48
    assert parse_length("25%", 1000, 96) == 250
    with pytest.raises(UnitError):
        parse_length("12em", 1000, 96)


def test_theme_precedence_and_extends(tmp_path):
    write(tmp_path, "themes.yaml", """
        base: {text: {color: "#ff0000", size: 20pt}, effects: {vignette: 0.3}}
        child: {extends: base, text: {size: 30pt}}
    """)
    cfg = write(tmp_path, "t.yaml", """@VIDEO
        output_dir: out
        themes: themes.yaml
        theme: child
        defaults: {text: {speed: 5}}
        slides:
          - texts: [{text: hi, color: "#00ff00"}, plain]
          - theme: terminator
            texts: [hello]
    """)
    p = load_config(cfg)
    a, b = p["slides"][0]["texts"]
    assert a["color"] == "#00ff00" and b["color"] == "#ff0000"
    assert a["size"] == "30pt" and a["speed"] == 5
    assert p["slides"][0]["effects"]["vignette"] == 0.3
    term = p["slides"][1]
    assert term["texts"][0]["glow"]["color"] == "#00ff41"
    assert term["effects"]["scanlines"]["spacing"] == 4


def test_unknown_key_and_theme_errors(tmp_path):
    cfg = write(tmp_path, "t.yaml", "output_dir: o\nslides: [{texts: [{text: a, colour: red}]}]\n")
    with pytest.raises(ConfigError, match="colour"):
        load_config(cfg)
    cfg = write(tmp_path, "t2.yaml", "output_dir: o\nslides: [{theme: nope, texts: [a]}]\n")
    with pytest.raises(ConfigError, match="unknown theme"):
        load_config(cfg)


def test_typing_progress_and_overlays(tmp_path):
    cfg = write(tmp_path, "t.yaml", """@VIDEO
        output_dir: out
        slides:
          - duration: auto
            hold: 1
            background:
              color: "#000000"
              overlays:
                - {type: rounded_rect, x: 0, y: 0, width: 50%, height: 100%, radius: 10, color: "#ffffff", opacity: 0.5}
                - {type: circle, x: 75%, y: 50%, radius: 20, color: "#ff0000"}
            texts:
              - {text: "ABCD", x: 60%, y: 5%, size: 20px, speed: 10, start: 0}
    """)
    slide = load_config(cfg)["slides"][0]
    r = SlideRenderer(slide, {"width": 320, "height": 180, "fps": 10, "dpi": 96}, str(tmp_path))
    assert r.duration == pytest.approx(0.4 + 1.0)
    el = r.elements[0]
    assert [el.chars_at(t) for t in (0.0, 0.1, 0.25, 1.0)] == [0, 1, 2, 4]

    first, last = r.render(0), r.render(r.frame_count - 1)
    assert first.getpixel((10, 170)) == (128, 128, 128)  # 50% white rect
    assert first.getpixel((240, 90)) == (255, 0, 0)       # circle centre
    box = el.box
    assert first.crop(box).getbbox() is None  # nothing typed yet
    assert last.crop(box).convert("L").getextrema()[1] > 200


def test_cli_renders_mp4_and_preview(tmp_path):
    Image.new("RGB", (64, 36), (0, 0, 255)).save(tmp_path / "bg.png")
    cfg = write(tmp_path, "t.yaml", """@VIDEO
        output_dir: out
        slides:
          - name: "My Slide"
            theme: terminator
            duration: 1
            background: {image: bg.png, image_opacity: 0.5}
            texts: [{text: "HI", x: 10, y: 10, size: 24px, speed: 20}]
    """)
    assert main([str(cfg), "--preview"]) == 0
    assert (tmp_path / "out" / "01_My_Slide.png").is_file()
    assert main([str(cfg)]) == 0
    mp4 = tmp_path / "out" / "01_My_Slide.mp4"
    import imageio_ffmpeg
    frames, secs = imageio_ffmpeg.count_frames_and_secs(str(mp4))
    assert frames == 10 and secs == pytest.approx(1.0, abs=0.05)
