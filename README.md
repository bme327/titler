# titler

Turns a single YAML file into animated title slides, one MP4 per slide. Each text is
typed in letter by letter. Slides can have a background colour or image, overlay shapes
(rounded rectangles and circles with opacity), and reusable themes. A glowing green
**terminator** theme is built in.

Rendering is done in Python. Pillow draws each frame and the frames are piped into
ffmpeg, which `imageio-ffmpeg` installs for you. No browser is involved, so frame timing
is exact and nothing else needs to be installed.

## Install & run

```powershell
pip install -r requirements.txt        # or: pip install -e .   (adds a `titler` command)
python -m titler examples/titles.yaml            # render all slides to MP4
python -m titler examples/titles.yaml --preview  # quick PNG still per slide (last frame)
python -m titler examples/titles.yaml -p 1.5     # PNG still at 1.5 s
python -m titler examples/titles.yaml -s intro   # only slide "intro" (repeatable)
python -m titler examples/titles.yaml -j 4       # render 4 slides in parallel
```

Output files go to `<output_dir>/NN_<slide-name>.mp4` (H.264, yuv420p, faststart).

## Why YAML

YAML allows comments and multi-line text (`|` blocks), and it needs fewer quotes than
JSON. YAML is a superset of JSON, so `.json` project files also work.

## Units

Every position, size, radius and outline width accepts:

| Form | Meaning |
|---|---|
| `120` or `"120px"` | pixels |
| `"36pt"` | points, converted with `video.dpi` (1 pt = dpi/72 px; at 96 dpi 36pt = 48px) |
| `"50%"` | percent of frame width (x, width) or height (y, height, font size) |

## Project file

```yaml
output_dir: out/my_titles      # required, relative to this file
themes: my-themes.yaml         # optional: one file or a list of files
theme: terminator              # optional default theme for all slides
video: {width: 1920, height: 1080, fps: 30, dpi: 96, crf: 18, preset: medium}
defaults: { ...style... }      # optional style applied to every slide
slides:
  - name: intro                # used in the file name
    theme: amber               # per-slide theme, or `null` for no theme
    ...style...                # any style key, overriding the theme
    texts:
      - text: "HELLO"          # text elements; a plain string is also allowed
        ...text style...
```

**Precedence**, lowest to highest: built-in defaults < `defaults` < theme < slide < text
element. Mappings are merged key by key, and lists such as `overlays` are replaced as a whole.

### Style keys (allowed on slides, themes and `defaults`)

| Key | Default | Notes |
|---|---|---|
| `duration` | `auto` | seconds, or `auto` = typing end + `hold` + `fade_out` |
| `hold` | `2.0` | seconds kept on screen after typing (auto duration) |
| `fade_in` / `fade_out` | `0` | seconds; fades from and to black |
| `background.color` | `#000000` | any CSS-like colour: `#rrggbb`, `red`, `rgb(…)` |
| `background.image` | – | path relative to the file that defines it |
| `background.fit` | `cover` | `cover`, `contain`, `stretch`, `center` |
| `background.image_opacity` | `1.0` | blends the image over `color`, which is a simple way to dim it |
| `background.image_blur` | `0` | Gaussian blur radius in px |
| `background.overlays` | `[]` | shapes, see below |
| `effects.scanlines` | `false` | `true` or `{spacing: 4, thickness: 1, opacity: 0.2}` |
| `effects.vignette` | `0` | 0–1 corner darkening |
| `effects.flicker` | `0` | 0–1 random brightness flicker per frame |
| `text` | | default text style for this slide, see next table |

### Text keys

| Key | Default | Notes |
|---|---|---|
| `text` | – | supports multi-line text (`\|` block) |
| `x`, `y` | `10%` | position of the `anchor` point |
| `anchor` | `top-left` | `top-left`, `top-center`, `top-right`, `center-left`, `center`, `center-right`, `bottom-…` |
| `align` | `left` | alignment of lines inside a multi-line block |
| `font` | sans fallback list | file path, file name (`consola.ttf`), or family name (`"Courier New"`); a list means first found wins |
| `size` | `48pt` | font size |
| `color` | `#ffffff` | |
| `line_spacing` | `1.2` | |
| `speed` | `20` | characters per second; `0` means the text appears instantly |
| `start` | `auto` | seconds from slide start; `auto` = after the previous text + `pause` |
| `pause` | `0.4` | delay before this text starts when `start: auto` |
| `line_pause` | `0` | extra delay after each newline |
| `jitter` | `0` | 0–1 random variation in keystroke timing, for a more human feel |
| `glow` | `false` | `true` or `{color, radius: 10, strength: 1.5}` |
| `cursor` | `false` | `true` or `{style: block\|underscore\|bar, color, blink_interval: 0.5, solid_while_typing: true}` |

The layout is computed from the full text, so letters never shift while they are typed,
even when the text is centred. The cursor follows the text that is currently being typed
and keeps blinking at the end of the last text once typing finishes.

### Overlays

```yaml
overlays:
  - type: rounded_rect        # or rect / rectangle
    x: 5%                     # top-left corner
    y: 10%
    width: 90%
    height: 80%
    radius: 24                # corner radius (0 = square corners)
    color: "#000000"          # fill (omit for outline only)
    opacity: 0.6
    outline: "#00ff41"
    outline_width: 2pt
    blur: 0                   # soft edges or a shadow
  - type: circle
    x: 50%                    # centre
    y: 50%
    radius: 80
    color: "#ff0000"
    opacity: 0.5
```

Overlays are drawn in order, on top of the background image and under the text.

## Themes

A theme file maps theme names to style definitions. It accepts the same keys as a slide,
except `texts` and `name`. A theme can also use `extends: <other theme>` to inherit from
another theme, and `description` to describe itself. Paths inside a theme file are
resolved relative to that theme file.

The built-in themes are in [titler/themes/builtin.yaml](titler/themes/builtin.yaml):

- **terminator**: phosphor-green Consolas-style mono text on a near-black background,
  with a green glow, block cursor, human-like typing jitter, scanlines, vignette and a
  subtle flicker.
- **amber**: the terminator look in amber (an example of `extends`).
- **clean**: white text on dark grey with no effects.

[examples/themes.yaml](examples/themes.yaml) shows a project theme, `skynet-hud`. It
extends `terminator` and adds a dimmed, blurred background image, a translucent
rounded HUD panel and a glowing red circle.

## Tests

```powershell
pip install pytest; python -m pytest -q
```
