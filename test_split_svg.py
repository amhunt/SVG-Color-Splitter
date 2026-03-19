"""Tests for split_svg_by_color.py"""

import os
import xml.etree.ElementTree as ET

import pytest

from split_svg_by_color import (
    SVG_NS,
    SHAPE_TAGS,
    _color_label,
    _normalize_color,
    _parse_style,
    split_svg,
)

import webcolors

# ---------------------------------------------------------------------------
# Reusable helpers & fixtures
# ---------------------------------------------------------------------------

VIEWBOX = "0 0 200 200"
WIDTH = "200"
HEIGHT = "200"


def make_svg(body: str, viewbox: str = VIEWBOX) -> str:
    """Wrap shape/group XML in a minimal SVG root."""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg"'
        f' viewBox="{viewbox}" width="{WIDTH}" height="{HEIGHT}">'
        f"{body}"
        f"</svg>"
    )


def write_svg(tmp_path, body: str, name: str = "input.svg", **kw) -> str:
    """Write an SVG file into tmp_path and return its path."""
    path = os.path.join(str(tmp_path), name)
    with open(path, "w") as f:
        f.write(make_svg(body, **kw))
    return path


def parse_shapes(svg_path: str) -> list[ET.Element]:
    """Return all shape elements from a written SVG file."""
    tree = ET.parse(svg_path)
    return [e for e in tree.getroot().iter() if e.tag in SHAPE_TAGS]


def get_viewbox(svg_path: str) -> str:
    tree = ET.parse(svg_path)
    return tree.getroot().get("viewBox")


def output_files(tmp_path) -> dict[str, str]:
    """Map color-label suffix → file path for every *output* SVG in tmp_path."""
    files = {}
    for name in os.listdir(str(tmp_path)):
        if name.startswith("input_") and name.endswith(".svg"):
            label = name.removeprefix("input_").removesuffix(".svg")
            files[label] = os.path.join(str(tmp_path), name)
    return files


# Reusable shape fragments
RED_CIRCLE = '<circle cx="50" cy="50" r="10" fill="red"/>'
RED_RECT = '<rect x="0" y="0" width="10" height="10" fill="#ff0000"/>'
GREEN_PATH = '<path d="M0 0 L10 10" fill="green"/>'
BLACK_ELLIPSE = '<ellipse cx="100" cy="100" rx="30" ry="20" fill="black"/>'
BLUE_POLYGON = '<polygon points="10,10 40,10 25,40" fill="blue"/>'
NONE_PATH = '<path d="M0 0 L5 5" fill="none"/>'


# ---------------------------------------------------------------------------
# Unit tests: color normalization
# ---------------------------------------------------------------------------


class TestNormalizeColor:
    """All equivalent color representations should map to the same hex."""

    def test_named_color(self):
        assert _normalize_color("red") == "#ff0000"

    def test_named_color_case_insensitive(self):
        assert _normalize_color("Red") == "#ff0000"
        assert _normalize_color("RED") == "#ff0000"

    def test_hex_6_digit(self):
        assert _normalize_color("#ff0000") == "#ff0000"

    def test_hex_3_digit_expands(self):
        assert _normalize_color("#f00") == "#ff0000"
        assert _normalize_color("#000") == "#000000"

    def test_hex_8_digit_strips_alpha(self):
        assert _normalize_color("#ff000080") == "#ff0000"

    def test_rgb_functional(self):
        assert _normalize_color("rgb(255, 0, 0)") == "#ff0000"
        assert _normalize_color("rgb(0,128,0)") == "#008000"

    def test_rgba_functional(self):
        assert _normalize_color("rgba(255, 0, 0, 0.5)") == "#ff0000"

    def test_none_passthrough(self):
        assert _normalize_color("none") == "none"

    def test_transparent_passthrough(self):
        assert _normalize_color("transparent") == "transparent"

    def test_whitespace_stripped(self):
        assert _normalize_color("  red  ") == "#ff0000"


# ---------------------------------------------------------------------------
# Unit tests: color labeling (used in output filenames)
# ---------------------------------------------------------------------------


class TestColorLabel:
    # Exact CSS3 match → returns the name directly
    def test_exact_color_name(self):
        assert _color_label("#ff0000") == "red"
        assert _color_label("#000000") == "black"

    # Near-miss hex → falls back to closest CSS3 name
    def test_near_red_labels_as_red(self):
        assert _color_label("#fe0100") == "red"

    def test_near_white_labels_as_white(self):
        assert _color_label("#fffffe") == "white"

    def test_near_blue_labels_as_blue(self):
        assert _color_label("#0000fe") == "blue"

    # The nearest match should itself be a valid CSS3 color name
    def test_nearest_is_valid_css3_name(self):
        label = _color_label("#ab12cd")
        try:
            webcolors.name_to_hex(label)
        except ValueError:
            pytest.fail(f"{label!r} is not a valid CSS3 color name")

    # Non-hex strings still get sanitized for filenames
    def test_special_chars_sanitized(self):
        assert _color_label("some/weird:color") == "some_weird_color"


# ---------------------------------------------------------------------------
# Unit tests: inline style parsing
# ---------------------------------------------------------------------------


class TestParseStyle:
    def test_single_property(self):
        assert _parse_style("fill: red")["fill"] == "red"

    def test_multiple_properties(self):
        result = _parse_style("fill:#00ff00; stroke:black; opacity:0.5")
        assert result["fill"] == "#00ff00"
        assert result["stroke"] == "black"

    def test_empty_string(self):
        assert _parse_style("") == {}

    def test_trailing_semicolon(self):
        result = _parse_style("fill:blue;")
        assert result["fill"] == "blue"


# ---------------------------------------------------------------------------
# Integration tests: end-to-end split
# ---------------------------------------------------------------------------


class TestSplitBasic:
    """Core splitting behavior with simple multi-color SVGs."""

    # Two distinct colors → two output files
    def test_splits_into_correct_file_count(self, tmp_path):
        write_svg(tmp_path, RED_CIRCLE + GREEN_PATH)
        split_svg(os.path.join(str(tmp_path), "input.svg"), str(tmp_path))

        files = output_files(tmp_path)
        assert len(files) == 2
        assert "red" in files
        assert "green" in files

    # Each output has exactly the shapes of its color
    def test_correct_shape_count_per_file(self, tmp_path):
        body = RED_CIRCLE + RED_RECT + GREEN_PATH + BLACK_ELLIPSE
        write_svg(tmp_path, body)
        split_svg(os.path.join(str(tmp_path), "input.svg"), str(tmp_path))

        files = output_files(tmp_path)
        assert len(parse_shapes(files["red"])) == 2
        assert len(parse_shapes(files["green"])) == 1
        assert len(parse_shapes(files["black"])) == 1


class TestBoundingBoxPreserved:
    """Every output SVG must keep the original viewBox so layers align."""

    def test_viewbox_matches_original(self, tmp_path):
        write_svg(tmp_path, RED_CIRCLE + GREEN_PATH, viewbox="0 0 500 300")
        split_svg(os.path.join(str(tmp_path), "input.svg"), str(tmp_path))

        for path in output_files(tmp_path).values():
            assert get_viewbox(path) == "0 0 500 300"


class TestColorEquivalence:
    """Shapes with different representations of the same color merge."""

    # 'red', '#ff0000', '#f00', and 'rgb(255,0,0)' are all red
    def test_all_red_variants_in_one_file(self, tmp_path):
        body = (
            '<circle cx="10" cy="10" r="5" fill="red"/>'
            '<circle cx="20" cy="20" r="5" fill="#ff0000"/>'
            '<circle cx="30" cy="30" r="5" fill="#f00"/>'
            '<circle cx="40" cy="40" r="5" fill="rgb(255,0,0)"/>'
        )
        write_svg(tmp_path, body)
        split_svg(os.path.join(str(tmp_path), "input.svg"), str(tmp_path))

        files = output_files(tmp_path)
        assert len(files) == 1, "all reds should merge into a single file"
        assert len(parse_shapes(files["red"])) == 4


class TestFillInheritance:
    """Fill on a parent <g> should propagate to ungrouped children."""

    def test_group_fill_inherited(self, tmp_path):
        body = (
            '<g fill="blue">'
            '  <rect x="0" y="0" width="10" height="10"/>'
            '  <circle cx="50" cy="50" r="5"/>'
            "</g>"
            + RED_CIRCLE
        )
        write_svg(tmp_path, body)
        split_svg(os.path.join(str(tmp_path), "input.svg"), str(tmp_path))

        files = output_files(tmp_path)
        assert len(parse_shapes(files["blue"])) == 2
        assert len(parse_shapes(files["red"])) == 1

    # No fill anywhere → SVG default is black
    def test_default_fill_is_black(self, tmp_path):
        body = '<rect x="0" y="0" width="10" height="10"/>'
        write_svg(tmp_path, body)
        split_svg(os.path.join(str(tmp_path), "input.svg"), str(tmp_path))

        files = output_files(tmp_path)
        assert "black" in files


class TestStyleAttribute:
    """Fill specified via inline style= should be detected."""

    def test_fill_in_style(self, tmp_path):
        body = (
            '<rect x="0" y="0" width="10" height="10" style="fill:orange; stroke:black"/>'
            + GREEN_PATH
        )
        write_svg(tmp_path, body)
        split_svg(os.path.join(str(tmp_path), "input.svg"), str(tmp_path))

        files = output_files(tmp_path)
        assert "orange" in files
        assert "green" in files

    # style= fill takes precedence over fill= attribute
    def test_style_overrides_attribute(self, tmp_path):
        body = '<rect x="0" y="0" width="10" height="10" fill="red" style="fill:blue"/>'
        write_svg(tmp_path, body)
        split_svg(os.path.join(str(tmp_path), "input.svg"), str(tmp_path))

        files = output_files(tmp_path)
        assert "blue" in files
        assert "red" not in files


class TestEdgeCases:
    # fill="none" shapes should be excluded entirely
    def test_none_fill_excluded(self, tmp_path):
        write_svg(tmp_path, RED_CIRCLE + NONE_PATH)
        split_svg(os.path.join(str(tmp_path), "input.svg"), str(tmp_path))

        files = output_files(tmp_path)
        assert len(files) == 1
        assert "red" in files

    # SVG with zero filled shapes → no output files
    def test_no_shapes_produces_no_files(self, tmp_path):
        write_svg(tmp_path, NONE_PATH)
        result = split_svg(os.path.join(str(tmp_path), "input.svg"), str(tmp_path))
        assert result == []

    # Single color → one output file
    def test_single_color(self, tmp_path):
        write_svg(tmp_path, RED_CIRCLE + RED_RECT)
        split_svg(os.path.join(str(tmp_path), "input.svg"), str(tmp_path))

        files = output_files(tmp_path)
        assert len(files) == 1
        assert "red" in files
        assert len(parse_shapes(files["red"])) == 2

    # Many colors → one file per color
    def test_many_colors(self, tmp_path):
        body = RED_CIRCLE + GREEN_PATH + BLACK_ELLIPSE + BLUE_POLYGON
        write_svg(tmp_path, body)
        split_svg(os.path.join(str(tmp_path), "input.svg"), str(tmp_path))

        files = output_files(tmp_path)
        assert set(files.keys()) == {"red", "green", "black", "blue"}

    # --outdir puts files in the requested directory
    def test_custom_outdir(self, tmp_path):
        svg = write_svg(tmp_path, RED_CIRCLE + GREEN_PATH)
        out = os.path.join(str(tmp_path), "output")
        split_svg(svg, out)

        assert os.path.isfile(os.path.join(out, "input_red.svg"))
        assert os.path.isfile(os.path.join(out, "input_green.svg"))


class TestNearestColorNaming:
    """Non-exact hex colors should get the nearest CSS3 name in the filename."""

    # #fe0100 is one tick off pure red → file should be named _red.svg
    def test_near_red_gets_red_filename(self, tmp_path):
        body = '<circle cx="50" cy="50" r="10" fill="#fe0100"/>'
        write_svg(tmp_path, body)
        split_svg(os.path.join(str(tmp_path), "input.svg"), str(tmp_path))

        files = output_files(tmp_path)
        assert "red" in files

    # Two near-reds that normalize to different hex values stay separate
    def test_distinct_near_colors_stay_separate(self, tmp_path):
        body = (
            '<circle cx="10" cy="10" r="5" fill="#ff0000"/>'
            '<circle cx="50" cy="50" r="5" fill="#00ff00"/>'
        )
        write_svg(tmp_path, body)
        split_svg(os.path.join(str(tmp_path), "input.svg"), str(tmp_path))

        files = output_files(tmp_path)
        assert len(files) == 2


class TestGroupPruning:
    """Empty <g> wrappers should be removed after filtering."""

    def test_empty_groups_pruned(self, tmp_path):
        body = (
            "<g>"
            '  <circle cx="10" cy="10" r="5" fill="red"/>'
            "</g>"
            "<g>"
            '  <circle cx="20" cy="20" r="5" fill="blue"/>'
            "</g>"
        )
        write_svg(tmp_path, body)
        split_svg(os.path.join(str(tmp_path), "input.svg"), str(tmp_path))

        files = output_files(tmp_path)
        red_tree = ET.parse(files["red"])
        groups = [e for e in red_tree.getroot().iter() if e.tag == f"{{{SVG_NS}}}g"]
        for g in groups:
            assert len(g) > 0, "empty <g> should have been pruned"
