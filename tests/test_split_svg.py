"""Tests for split_svg_by_color.py"""

import os
import shutil
import xml.etree.ElementTree as ET

import pytest
import webcolors

from split_svg_by_color import (
    REGISTRATION_MARK_RADIUS,
    SVG_NS,
    _color_label,
    _normalize_color,
    _parse_style,
    split_svg,
)

from tests.conftest import (
    output_files,
    parse_shapes,
    get_viewbox,
    write_svg,
)

# ---------------------------------------------------------------------------
# Reusable shape fragments
# ---------------------------------------------------------------------------

RED_CIRCLE = '<circle cx="50" cy="50" r="10" fill="red"/>'
RED_RECT = '<rect x="0" y="0" width="10" height="10" fill="#ff0000"/>'
GREEN_PATH = '<path d="M0 0 L10 10" fill="green"/>'
BLACK_ELLIPSE = '<ellipse cx="100" cy="100" rx="30" ry="20" fill="black"/>'
BLUE_POLYGON = '<polygon points="10,10 40,10 25,40" fill="blue"/>'
NONE_PATH = '<path d="M0 0 L5 5" fill="none"/>'
STROKE_ONLY_LINE = '<line x1="0" y1="0" x2="100" y2="100" fill="none" stroke="green" stroke-width="3"/>'
STROKE_ONLY_PATH = '<path d="M10 20 L90 80" fill="none" stroke="blue" stroke-width="2"/>'


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
    def test_exact_color_name(self):
        assert _color_label("#ff0000") == "red"
        assert _color_label("#000000") == "black"

    def test_near_red_labels_as_red(self):
        assert _color_label("#fe0100") == "red"

    def test_near_white_labels_as_white(self):
        assert _color_label("#fffffe") == "white"

    def test_near_blue_labels_as_blue(self):
        assert _color_label("#0000fe") == "blue"

    def test_nearest_is_valid_css3_name(self):
        label = _color_label("#ab12cd")
        try:
            webcolors.name_to_hex(label)
        except ValueError:
            pytest.fail(f"{label!r} is not a valid CSS3 color name")

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
# Integration tests: real fixture file
# ---------------------------------------------------------------------------


class TestFixtureFile:
    """Tests that use the actual multicolor.svg fixture on disk."""

    def test_split_multicolor_fixture(self, tmp_path, multicolor_svg):
        dest = os.path.join(str(tmp_path), "input.svg")
        shutil.copy(multicolor_svg, dest)
        split_svg(dest, str(tmp_path))

        files = output_files(tmp_path)
        assert set(files.keys()) == {"red", "green", "black", "blue"}

    def test_multicolor_fixture_red_has_two_shapes(self, tmp_path, multicolor_svg):
        dest = os.path.join(str(tmp_path), "input.svg")
        shutil.copy(multicolor_svg, dest)
        split_svg(dest, str(tmp_path))

        files = output_files(tmp_path)
        assert len(parse_shapes(files["red"])) == 2

    def test_multicolor_fixture_preserves_viewbox(self, tmp_path, multicolor_svg):
        dest = os.path.join(str(tmp_path), "input.svg")
        shutil.copy(multicolor_svg, dest)
        split_svg(dest, str(tmp_path))

        for path in output_files(tmp_path).values():
            assert get_viewbox(path) == "0 0 200 200"


# ---------------------------------------------------------------------------
# Integration tests: end-to-end split (inline SVGs)
# ---------------------------------------------------------------------------


class TestSplitBasic:
    """Core splitting behavior with simple multi-color SVGs."""

    def test_splits_into_correct_file_count(self, tmp_path):
        write_svg(tmp_path, RED_CIRCLE + GREEN_PATH)
        split_svg(os.path.join(str(tmp_path), "input.svg"), str(tmp_path))

        files = output_files(tmp_path)
        assert len(files) == 2
        assert "red" in files
        assert "green" in files

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

    def test_style_overrides_attribute(self, tmp_path):
        body = '<rect x="0" y="0" width="10" height="10" fill="red" style="fill:blue"/>'
        write_svg(tmp_path, body)
        split_svg(os.path.join(str(tmp_path), "input.svg"), str(tmp_path))

        files = output_files(tmp_path)
        assert "blue" in files
        assert "red" not in files


class TestEdgeCases:
    def test_none_fill_excluded(self, tmp_path):
        write_svg(tmp_path, RED_CIRCLE + NONE_PATH)
        split_svg(os.path.join(str(tmp_path), "input.svg"), str(tmp_path))

        files = output_files(tmp_path)
        assert len(files) == 1
        assert "red" in files

    def test_no_shapes_produces_no_files(self, tmp_path):
        write_svg(tmp_path, NONE_PATH)
        result = split_svg(os.path.join(str(tmp_path), "input.svg"), str(tmp_path))
        assert result == []

    def test_single_color(self, tmp_path):
        write_svg(tmp_path, RED_CIRCLE + RED_RECT)
        split_svg(os.path.join(str(tmp_path), "input.svg"), str(tmp_path))

        files = output_files(tmp_path)
        assert len(files) == 1
        assert "red" in files
        assert len(parse_shapes(files["red"])) == 2

    def test_many_colors(self, tmp_path):
        body = RED_CIRCLE + GREEN_PATH + BLACK_ELLIPSE + BLUE_POLYGON
        write_svg(tmp_path, body)
        split_svg(os.path.join(str(tmp_path), "input.svg"), str(tmp_path))

        files = output_files(tmp_path)
        assert set(files.keys()) == {"red", "green", "black", "blue"}

    def test_custom_outdir(self, tmp_path):
        svg = write_svg(tmp_path, RED_CIRCLE + GREEN_PATH)
        out = os.path.join(str(tmp_path), "output")
        split_svg(svg, out)

        assert os.path.isfile(os.path.join(out, "input_red.svg"))
        assert os.path.isfile(os.path.join(out, "input_green.svg"))


class TestNearestColorNaming:
    """Non-exact hex colors should get the nearest CSS3 name in the filename."""

    def test_near_red_gets_red_filename(self, tmp_path):
        body = '<circle cx="50" cy="50" r="10" fill="#fe0100"/>'
        write_svg(tmp_path, body)
        split_svg(os.path.join(str(tmp_path), "input.svg"), str(tmp_path))

        files = output_files(tmp_path)
        assert "red" in files

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


# ---------------------------------------------------------------------------
# Integration tests: stroke fallback
# ---------------------------------------------------------------------------


class TestStrokeFallback:
    """Shapes with fill=none but a visible stroke are grouped by stroke color."""

    def test_stroke_only_line_included(self, tmp_path):
        write_svg(tmp_path, RED_CIRCLE + STROKE_ONLY_LINE)
        split_svg(os.path.join(str(tmp_path), "input.svg"), str(tmp_path))

        files = output_files(tmp_path)
        assert "red" in files
        assert "green" in files

    def test_stroke_only_path_included(self, tmp_path):
        write_svg(tmp_path, STROKE_ONLY_PATH)
        split_svg(os.path.join(str(tmp_path), "input.svg"), str(tmp_path))

        files = output_files(tmp_path)
        assert "blue" in files
        assert len(parse_shapes(files["blue"])) == 1

    def test_stroke_and_fill_same_color_merge(self, tmp_path):
        body = (
            GREEN_PATH
            + STROKE_ONLY_LINE  # also green
        )
        write_svg(tmp_path, body)
        split_svg(os.path.join(str(tmp_path), "input.svg"), str(tmp_path))

        files = output_files(tmp_path)
        assert len(files) == 1
        assert "green" in files
        assert len(parse_shapes(files["green"])) == 2

    def test_fill_takes_precedence_over_stroke(self, tmp_path):
        body = '<rect x="0" y="0" width="10" height="10" fill="red" stroke="blue"/>'
        write_svg(tmp_path, body)
        split_svg(os.path.join(str(tmp_path), "input.svg"), str(tmp_path))

        files = output_files(tmp_path)
        assert "red" in files
        assert "blue" not in files

    def test_no_fill_no_stroke_excluded(self, tmp_path):
        body = '<path d="M0 0 L5 5" fill="none" stroke="none"/>'
        write_svg(tmp_path, body)
        result = split_svg(os.path.join(str(tmp_path), "input.svg"), str(tmp_path))
        assert result == []

    def test_inherited_fill_none_falls_back_to_stroke(self, tmp_path):
        body = (
            '<g fill="none">'
            '  <path d="M0 0 L50 50" stroke="orange" stroke-width="2"/>'
            "</g>"
        )
        write_svg(tmp_path, body)
        split_svg(os.path.join(str(tmp_path), "input.svg"), str(tmp_path))

        files = output_files(tmp_path)
        assert "orange" in files

    def test_stroke_in_style_attribute(self, tmp_path):
        body = '<line x1="0" y1="0" x2="50" y2="50" fill="none" style="stroke:purple; stroke-width:3"/>'
        write_svg(tmp_path, body)
        split_svg(os.path.join(str(tmp_path), "input.svg"), str(tmp_path))

        files = output_files(tmp_path)
        assert "purple" in files


# ---------------------------------------------------------------------------
# Registration marks for slicer alignment
# ---------------------------------------------------------------------------


def _find_reg_marks(svg_path: str) -> list[ET.Element]:
    """Return all circles with the registration mark radius."""
    tree = ET.parse(svg_path)
    r_str = str(REGISTRATION_MARK_RADIUS)
    return [
        e for e in tree.getroot().iter()
        if e.tag == f"{{{SVG_NS}}}circle" and e.get("r") == r_str
    ]


class TestRegistrationMarks:
    """Each output SVG gets tiny circles at opposite viewBox corners."""

    def test_marks_present_in_every_output(self, tmp_path):
        write_svg(tmp_path, RED_CIRCLE + GREEN_PATH)
        split_svg(os.path.join(str(tmp_path), "input.svg"), str(tmp_path))

        for path in output_files(tmp_path).values():
            marks = _find_reg_marks(path)
            assert len(marks) == 2

    def test_marks_at_viewbox_corners(self, tmp_path):
        write_svg(tmp_path, RED_CIRCLE, viewbox="10 20 300 400")
        split_svg(os.path.join(str(tmp_path), "input.svg"), str(tmp_path))

        marks = _find_reg_marks(output_files(tmp_path)["red"])
        coords = {(m.get("cx"), m.get("cy")) for m in marks}
        assert coords == {("10.0", "20.0"), ("310.0", "420.0")}

    def test_marks_use_file_color(self, tmp_path):
        write_svg(tmp_path, RED_CIRCLE + GREEN_PATH)
        split_svg(os.path.join(str(tmp_path), "input.svg"), str(tmp_path))

        files = output_files(tmp_path)
        for mark in _find_reg_marks(files["red"]):
            assert mark.get("fill") == "#ff0000"
        for mark in _find_reg_marks(files["green"]):
            assert mark.get("fill") == "#008000"

    def test_marks_same_position_across_files(self, tmp_path):
        write_svg(tmp_path, RED_CIRCLE + GREEN_PATH)
        split_svg(os.path.join(str(tmp_path), "input.svg"), str(tmp_path))

        files = output_files(tmp_path)
        red_coords = {(m.get("cx"), m.get("cy")) for m in _find_reg_marks(files["red"])}
        green_coords = {(m.get("cx"), m.get("cy")) for m in _find_reg_marks(files["green"])}
        assert red_coords == green_coords


# ---------------------------------------------------------------------------
# max_colors: merge visually similar colors
# ---------------------------------------------------------------------------


class TestMaxColors:
    """--max-colors merges the most similar color groups."""

    def test_merges_four_colors_to_two(self, tmp_path):
        body = RED_CIRCLE + GREEN_PATH + BLACK_ELLIPSE + BLUE_POLYGON
        write_svg(tmp_path, body)
        split_svg(os.path.join(str(tmp_path), "input.svg"), str(tmp_path),
                  max_colors=2)

        files = output_files(tmp_path)
        assert len(files) == 2

    def test_merges_similar_colors_first(self, tmp_path):
        body = (
            '<circle cx="10" cy="10" r="5" fill="#ff0000"/>'  # red
            '<circle cx="20" cy="20" r="5" fill="#dd0000"/>'  # dark red
            '<circle cx="30" cy="30" r="5" fill="#0000ff"/>'  # blue
        )
        write_svg(tmp_path, body)
        split_svg(os.path.join(str(tmp_path), "input.svg"), str(tmp_path),
                  max_colors=2)

        files = output_files(tmp_path)
        assert len(files) == 2
        # Red and dark-red should merge; blue stays separate
        assert "blue" in files

    def test_max_colors_none_is_noop(self, tmp_path):
        body = RED_CIRCLE + GREEN_PATH + BLACK_ELLIPSE
        write_svg(tmp_path, body)
        split_svg(os.path.join(str(tmp_path), "input.svg"), str(tmp_path),
                  max_colors=None)

        files = output_files(tmp_path)
        assert len(files) == 3

    def test_max_colors_ge_actual_is_noop(self, tmp_path):
        body = RED_CIRCLE + GREEN_PATH
        write_svg(tmp_path, body)
        split_svg(os.path.join(str(tmp_path), "input.svg"), str(tmp_path),
                  max_colors=10)

        files = output_files(tmp_path)
        assert len(files) == 2

    def test_max_colors_one_merges_everything(self, tmp_path):
        body = RED_CIRCLE + GREEN_PATH + BLUE_POLYGON
        write_svg(tmp_path, body)
        split_svg(os.path.join(str(tmp_path), "input.svg"), str(tmp_path),
                  max_colors=1)

        files = output_files(tmp_path)
        assert len(files) == 1

    def test_merged_file_has_all_shapes(self, tmp_path):
        body = RED_CIRCLE + GREEN_PATH + BLUE_POLYGON
        write_svg(tmp_path, body)
        split_svg(os.path.join(str(tmp_path), "input.svg"), str(tmp_path),
                  max_colors=1)

        files = output_files(tmp_path)
        only_file = list(files.values())[0]
        assert len(parse_shapes(only_file)) == 3

    def test_dominant_color_kept_as_label(self, tmp_path):
        body = (
            '<circle cx="10" cy="10" r="5" fill="red"/>'
            '<circle cx="20" cy="20" r="5" fill="red"/>'
            '<circle cx="30" cy="30" r="5" fill="red"/>'
            '<circle cx="40" cy="40" r="5" fill="#dd0000"/>'  # near-red, 1 shape
        )
        write_svg(tmp_path, body)
        split_svg(os.path.join(str(tmp_path), "input.svg"), str(tmp_path),
                  max_colors=1)

        files = output_files(tmp_path)
        assert "red" in files
