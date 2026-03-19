#!/usr/bin/env python3
"""
Split an SVG into separate files grouped by color.

Groups shapes by fill color. Shapes with no visible fill but a visible stroke
are grouped by stroke color instead, so stroke-only elements (e.g. a stem
drawn with stroke but no fill) aren't lost.

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


def _get_prop(elem: ET.Element, prop: str) -> str | None:
    """Extract a CSS property from an element (inline style takes precedence)."""
    style = elem.get("style", "")
    if style:
        props = _parse_style(style)
        if prop in props:
            return props[prop]
    return elem.get(prop)


def _resolve_prop(elem: ET.Element, parent_map: dict, prop: str,
                  default: str) -> str:
    """Walk up the tree to resolve an inherited CSS property."""
    node = elem
    while node is not None:
        val = _get_prop(node, prop)
        if val is not None:
            return _normalize_color(val)
        node = parent_map.get(node)
    return default


def _resolve_effective_color(elem: ET.Element, parent_map: dict) -> str | None:
    """Return the color a shape should be grouped by.

    Prefers fill; falls back to stroke when fill is none/transparent.
    Returns None if the shape has no visible fill or stroke.
    """
    fill = _resolve_prop(elem, parent_map, "fill", "#000000")
    if fill not in ("none", "transparent"):
        return fill

    stroke = _resolve_prop(elem, parent_map, "stroke", "none")
    if stroke not in ("none", "transparent"):
        return stroke

    return None


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


REGISTRATION_MARK_RADIUS = 0.01


def _parse_viewbox(root: ET.Element) -> tuple[float, float, float, float] | None:
    """Return (min_x, min_y, width, height) from the viewBox, or None."""
    vb = root.get("viewBox")
    if not vb:
        return None
    parts = vb.split()
    if len(parts) != 4:
        return None
    return tuple(float(p) for p in parts)  # type: ignore[return-value]


def _add_registration_marks(root: ET.Element, color: str) -> None:
    """Add tiny circles at opposite viewBox corners to anchor the bounding box.

    Ensures every output file shares the same extents so slicers that ignore
    viewBox (like Bambu Studio) still align the layers correctly.
    """
    vb = _parse_viewbox(root)
    if vb is None:
        return
    min_x, min_y, w, h = vb
    r = str(REGISTRATION_MARK_RADIUS)
    for cx, cy in [(min_x, min_y), (min_x + w, min_y + h)]:
        mark = ET.SubElement(root, f"{{{SVG_NS}}}circle")
        mark.set("cx", str(cx))
        mark.set("cy", str(cy))
        mark.set("r", r)
        mark.set("fill", color)


def _color_distance_sq(hex_a: str, hex_b: str) -> int:
    """Squared Euclidean distance between two hex colors in RGB space."""
    ra, ga, ba = webcolors.hex_to_rgb(hex_a)
    rb, gb, bb = webcolors.hex_to_rgb(hex_b)
    return (ra - rb) ** 2 + (ga - gb) ** 2 + (ba - bb) ** 2


def _merge_closest_colors(
    shapes_by_color: dict[str, list[ET.Element]],
    max_colors: int,
) -> dict[str, list[ET.Element]]:
    """Iteratively merge the two most similar color groups until at the limit.

    The smaller group is folded into the larger one; the larger group's hex
    key is kept so the output filename reflects the dominant color.
    """
    merged: dict[str, list[ET.Element]] = {
        c: list(elems) for c, elems in shapes_by_color.items()
    }

    while len(merged) > max_colors:
        keys = list(merged.keys())
        best_dist = float("inf")
        best_pair = (keys[0], keys[1])
        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                d = _color_distance_sq(keys[i], keys[j])
                if d < best_dist:
                    best_dist = d
                    best_pair = (keys[i], keys[j])

        a, b = best_pair
        if len(merged[a]) >= len(merged[b]):
            keep, drop = a, b
        else:
            keep, drop = b, a
        merged[keep].extend(merged.pop(drop))

    return merged


def _set_prop(elem: ET.Element, prop: str, value: str) -> None:
    """Set a CSS property on an element, updating style= if it's defined there."""
    style = elem.get("style", "")
    if style:
        props = _parse_style(style)
        if prop in props:
            props[prop] = value
            elem.set("style", "; ".join(f"{k}:{v}" for k, v in props.items()))
            return
    elem.set(prop, value)


def _recolor_shapes(root: ET.Element, parent_map: dict, color: str) -> None:
    """Rewrite every shape's fill (or stroke) to use a single unified color."""
    for elem in root.iter():
        if elem.tag not in SHAPE_TAGS:
            continue
        fill = _resolve_prop(elem, parent_map, "fill", "#000000")
        if fill not in ("none", "transparent"):
            _set_prop(elem, "fill", color)
        else:
            _set_prop(elem, "stroke", color)


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


def split_svg(svg_path: str, outdir: str | None = None,
              max_colors: int | None = None) -> list[str]:
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
            color = _resolve_effective_color(elem, parent_map)
            if color is None:
                continue
            shapes_by_color[color].append(elem)

    if not shapes_by_color:
        print("No visible shapes found in the SVG.")
        return []

    if max_colors is not None and len(shapes_by_color) > max_colors:
        original_count = len(shapes_by_color)
        shapes_by_color = _merge_closest_colors(shapes_by_color, max_colors)
        print(f"Merged {original_count} colors down to {len(shapes_by_color)}.")

    shape_ids: dict[str, set[int]] = {
        color: {id(e) for e in elems}
        for color, elems in shapes_by_color.items()
    }

    written: list[str] = []
    label_counts: dict[str, int] = {}
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
        _recolor_shapes(clone_root, clone_parent_map, color)
        _add_registration_marks(clone_root, color)

        label = _color_label(color)
        label_counts[label] = label_counts.get(label, 0) + 1
        if label_counts[label] > 1:
            label = f"{label}_{label_counts[label]}"
        out_path = os.path.join(outdir, f"{stem}_{label}.svg")
        clone.write(out_path, xml_declaration=True, encoding="unicode")
        written.append(out_path)
        count = len(shapes_by_color[color])
        print(f"  {out_path}  ({count} shape{'s' if count != 1 else ''})")

    print(f"\nSplit into {len(written)} file(s).")
    return written


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Split an SVG into per-color SVGs."
    )
    parser.add_argument("svg", help="Path to the input SVG file")
    parser.add_argument(
        "--outdir",
        default=None,
        help="Output directory (defaults to same directory as input)",
    )
    parser.add_argument(
        "--max-colors",
        type=int,
        default=None,
        metavar="N",
        help="Limit output to N colors by merging the most similar groups",
    )
    args = parser.parse_args()

    if not os.path.isfile(args.svg):
        parser.error(f"File not found: {args.svg}")

    split_svg(args.svg, args.outdir, max_colors=args.max_colors)


if __name__ == "__main__":
    main()
