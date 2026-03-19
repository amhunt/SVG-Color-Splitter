# SVG Color Splitter

Splits a multi-color SVG into separate SVG files by fill color, for multi-color 3D printing.

Designed for workflows where you export a single SVG from Illustrator (or similar) and need per-color files to import into Bambu Studio or another slicer. Each output file preserves the original `viewBox` and dimensions, so the layers align without manual repositioning.

## Usage

```bash
pip install webcolors
python3 split_svg_by_color.py <input.svg> [--outdir <directory>]
```

### Example

```bash
python3 split_svg_by_color.py rose.svg
```

If `rose.svg` contains black, red, and green shapes:

```
rose_black.svg   (all black shapes)
rose_red.svg     (all red shapes)
rose_green.svg   (all green shapes)
```

Use `--outdir` to write to a different folder:

```bash
python3 split_svg_by_color.py rose.svg --outdir ./split
```

## Details

- Handles `<path>`, `<rect>`, `<circle>`, `<ellipse>`, `<polygon>`, `<polyline>`, `<line>`, `<text>`, `<tspan>`, and `<use>` elements
- Resolves fill from `fill=` attributes, inline `style=`, and inherited fills from parent `<g>` groups
- Normalizes equivalent color formats (`#000`, `black`, `rgb(0,0,0)` all group together)
- Labels output files with the nearest CSS3 color name (e.g. `#fe0100` becomes `_red`, not `_fe0100`)
- Shapes with `fill="none"` are excluded

## Requirements

Python 3.10+, [webcolors](https://pypi.org/project/webcolors/)

## License

MIT
