"""Shared helpers and fixtures for SVG Color Splitter tests."""

import os
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from split_svg_by_color import REGISTRATION_MARK_RADIUS, SVG_NS, SHAPE_TAGS

FIXTURES_DIR = Path(__file__).parent / "fixtures"

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


def _is_registration_mark(elem: ET.Element) -> bool:
    return (
        elem.tag == f"{{{SVG_NS}}}circle"
        and elem.get("r") == str(REGISTRATION_MARK_RADIUS)
    )


def parse_shapes(svg_path: str) -> list[ET.Element]:
    """Return all shape elements from a written SVG file, excluding reg marks."""
    tree = ET.parse(svg_path)
    return [
        e for e in tree.getroot().iter()
        if e.tag in SHAPE_TAGS and not _is_registration_mark(e)
    ]


def get_viewbox(svg_path: str) -> str:
    tree = ET.parse(svg_path)
    return tree.getroot().get("viewBox")


def output_files(tmp_path) -> dict[str, str]:
    """Map color-label suffix -> file path for every *output* SVG in tmp_path."""
    files = {}
    for name in os.listdir(str(tmp_path)):
        if name.startswith("input_") and name.endswith(".svg"):
            label = name.removeprefix("input_").removesuffix(".svg")
            files[label] = os.path.join(str(tmp_path), name)
    return files


@pytest.fixture
def multicolor_svg() -> str:
    """Path to the multicolor fixture SVG on disk."""
    return str(FIXTURES_DIR / "multicolor.svg")
