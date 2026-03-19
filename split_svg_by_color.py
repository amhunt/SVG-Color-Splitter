#!/usr/bin/env python3
"""
Split an SVG into separate files grouped by fill color.

Each output SVG preserves the original's viewBox and dimensions so the files
can be superimposed. Output filenames follow the pattern:
    <original_stem>_<color_label>.svg

Usage:
    python split_svg_by_color.py input.svg [--outdir DIR]
"""

import argparse
import copy
import os
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

import webcolors

SVG_NS = "http://www.w3.org/2000/svg"

SHAPE_TAGS = {
    f"{{{SVG_NS}}}path",
    f"{{{SVG_NS}}}rect",
    f"{{{SVG_NS}}}circle",
    f"{{{SVG_NS}}}ellipse",
    f"{{{SVG_NS}}}polygon",
    f"{{{SVG_NS}}}polyline",
    f"{{{SVG_NS}}}line",
    f"{{{SVG_NS}}}text",
    f"{{{SVG_NS}}}tspan",
    f"{{{SVG_NS}}}use",
}

# Pre-compute name→RGB tuples for nearest-color lookup
_CSS3_COLORS_RGB: list[tuple[str, tuple[int, int, int]]] = [
    (name, webcolors.name_to_rgb(name))
    for name in webcolors.names(spec="css3")
    if "grey" not in name  # skip grey variants, keep gray
]


def _normalize_color(raw: str) -> str:
    """Return a canonical lowercase 6-digit hex string (e.g. '#ff0000')."""
    raw = raw.strip().lower()

    if raw in ("none", "transparent"):
        return raw

    # Named CSS color
    try:
        return webcolors.name_to_hex(raw)
    except (ValueError, AttributeError):
        pass

    # Hex (3, 4, 6, or 8 digit)
    if raw.startswith("#"):
        digits = raw[1:]
        if len(digits) == 8:
            digits = digits[:6]
        elif len(digits) == 4:
            digits = digits[:3]
        try:
            return webcolors.normalize_hex(f"#{digits}")
        except ValueError:
            return raw

    # rgb() / rgba()
    m = re.match(
        r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*[\d.]+\s*)?\)",
        raw,
    )
    if m:
        return webcolors.rgb_to_hex(
            (int(m[1]), int(m[2]), int(m[3]))
        )

    return raw


def _color_label(normalized: str) -> str:
    """Human-friendly filename-safe label for a color.

    Tries an exact CSS3 name match first, then falls back to the nearest
    named color by Euclidean distance in RGB space.
    """
    try:
        return webcolors.hex_to_name(normalized)
    except ValueError:
        pass

    if not normalized.startswith("#"):
        return re.sub(r"[^a-zA-Z0-9_-]", "_", normalized)

    target = webcolors.hex_to_rgb(normalized)
    best_name = normalized.lstrip("#")
    best_dist = float("inf")
    for name, rgb in _CSS3_COLORS_RGB:
        dist = sum((a - b) ** 2 for a, b in zip(target, rgb))
        if dist < best_dist:
            best_dist = dist
            best_name = name
    return best_name


def _parse_style(style_str: str) -> dict[str, str]:
    """Parse an inline CSS style string into a dict."""
    props: dict[str, str] = {}
    for decl in style_str.split(";"):
        decl = decl.strip()
        if ":" in decl:
            k, v = decl.split(":", 1)
            props[k.strip().lower()] = v.strip()
    return props


def _get_fill(elem: ET.Element) -> str | None:
    """Extract the fill value from an element (attribute or inline style)."""
    style = elem.get("style", "")
    if style:
        props = _parse_style(style)
        if "fill" in props:
            return props["fill"]
    return elem.get("fill")


def _resolve_fill(elem: ET.Element, parent_map: dict) -> str:
    """Walk up the tree to resolve the effective fill color."""
    node = elem
    while node is not None:
        fill = _get_fill(node)
        if fill is not None:
            return _normalize_color(fill)
        node = parent_map.get(node)
    return "#000000"  # SVG default fill is black


def _build_parent_map(root: ET.Element) -> dict[ET.Element, ET.Element]:
    pmap: dict[ET.Element, ET.Element] = {}
    for parent in root.iter():
        for child in parent:
            pmap[child] = parent
    return pmap


def _register_namespaces(svg_path: str) -> None:
    """Register every namespace found in the file so they survive round-trip."""
    for _, (prefix, uri) in ET.iterparse(svg_path, events=["start-ns"]):
        if prefix:
            ET.register_namespace(prefix, uri)
        else:
            ET.register_namespace("", uri)


def _prune_empty_groups(root: ET.Element) -> None:
    """Recursively remove <g> elements that contain no children."""
    changed = True
    while changed:
        changed = False
        for parent in list(root.iter()):
            for child in list(parent):
                if child.tag == f"{{{SVG_NS}}}g" and len(child) == 0:
                    parent.remove(child)
                    changed = True


def split_svg(svg_path: str, outdir: str | None = None) -> list[str]:
    svg_path = os.path.abspath(svg_path)
    stem = Path(svg_path).stem
    if outdir is None:
        outdir = str(Path(svg_path).parent)
    os.makedirs(outdir, exist_ok=True)

    _register_namespaces(svg_path)
    tree = ET.parse(svg_path)
    root = tree.getroot()
    parent_map = _build_parent_map(root)

    shapes_by_color: dict[str, list[ET.Element]] = defaultdict(list)
    for elem in root.iter():
        if elem.tag in SHAPE_TAGS:
            color = _resolve_fill(elem, parent_map)
            if color == "none" or color == "transparent":
                continue
            shapes_by_color[color].append(elem)

    if not shapes_by_color:
        print("No filled shapes found in the SVG.")
        return []

    shape_ids: dict[str, set[int]] = {
        color: {id(e) for e in elems}
        for color, elems in shapes_by_color.items()
    }

    written: list[str] = []
    for color, ids_set in shape_ids.items():
        clone = copy.deepcopy(tree)
        clone_root = clone.getroot()

        for elem in list(clone_root.iter()):
            if elem.tag in SHAPE_TAGS:
                if id(elem) not in ids_set:
                    pass  # ids differ after deepcopy

        clone = copy.deepcopy(tree)
        clone_root = clone.getroot()

        orig_elems = list(root.iter())
        clone_elems = list(clone_root.iter())
        keep_ids = set()
        for o, c in zip(orig_elems, clone_elems):
            if o.tag in SHAPE_TAGS and id(o) in ids_set:
                keep_ids.add(id(c))

        clone_parent_map = _build_parent_map(clone_root)
        for elem in list(clone_root.iter()):
            if elem.tag in SHAPE_TAGS and id(elem) not in keep_ids:
                parent = clone_parent_map.get(elem)
                if parent is not None:
                    parent.remove(elem)

        _prune_empty_groups(clone_root)

        label = _color_label(color)
        out_path = os.path.join(outdir, f"{stem}_{label}.svg")
        clone.write(out_path, xml_declaration=True, encoding="unicode")
        written.append(out_path)
        count = len(shapes_by_color[color])
        print(f"  {out_path}  ({count} shape{'s' if count != 1 else ''})")

    print(f"\nSplit into {len(written)} file(s).")
    return written


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Split an SVG into per-fill-color SVGs."
    )
    parser.add_argument("svg", help="Path to the input SVG file")
    parser.add_argument(
        "--outdir",
        default=None,
        help="Output directory (defaults to same directory as input)",
    )
    args = parser.parse_args()

    if not os.path.isfile(args.svg):
        parser.error(f"File not found: {args.svg}")

    split_svg(args.svg, args.outdir)


if __name__ == "__main__":
    main()
