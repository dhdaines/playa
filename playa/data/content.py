"""Schemas for various content objects.

This module contains schemas (as TypedDict) for content from various
PLAYA objects.

"""

from typing import List

try:
    # We only absolutely need this when using Pydantic TypeAdapter
    from typing_extensions import TypedDict
except ImportError:
    from typing import TypedDict

from playa.data.asobj import asobj
from playa.data.metadata import Font
from playa.page import GraphicState as _GraphicState
from playa.page import (
    MarkedContent,
)
from playa.page import TextObject as _TextObject
from playa.page import TextState as _TextState
from playa.utils import MATRIX_IDENTITY, Matrix, Point, Rect


class Text(TypedDict, total=False):
    """Text object on a page."""

    chars: str
    """Unicode string representation of text."""
    bbox: Rect
    """Bounding rectangle for all glyphs in text."""
    ctm: Matrix
    """Coordinate transformation matrix, default if not present is the
    identity matrix `[1 0 0 1 0 0]`."""
    textstate: "TextState"
    """Text state."""
    gstate: "GraphicState"
    """Graphic state."""
    mcstack: List["Tag"]
    """Stack of enclosing marked content sections."""


class TextState(TypedDict, total=False):
    line_matrix: Matrix
    """Coordinate transformation matrix for start of current line."""
    glyph_offset: Point
    """Offset of text object in relation to current line, in default text
    space units, default if not present is (0, 0)."""
    font: Font
    """Descriptor of current font."""
    fontsize: float
    """Font size in unscaled text space units (**not** in points, can be
    scaled using `line_matrix` to obtain user space units), default if
    not present is 1.0."""
    charspace: float
    """Character spacing in unscaled text space units, default if not present is 0."""
    wordspace: float
    """Word spacing in unscaled text space units, default if not present is 0."""
    scaling: float
    """Horizontal scaling factor multiplied by 100, default if not present is 100."""
    leading: float
    """Leading in unscaled text space units, default if not present is 0."""
    render_mode: int
    """Text rendering mode (PDF 1.7 Table 106), default if not present is 0."""
    rise: float
    """Text rise (for super and subscript) in unscaled text space
    units, default if not present is 0."""


class GraphicState(TypedDict, total=False):
    """Graphic state."""


class Tag(TypedDict, total=False):
    """Marked content section."""

    name: str
    """Tag name."""
    mcid: int
    """Marked content section ID."""
    props: dict
    """Marked content property dictionary (without MCID)."""


@asobj.register
def asobj_textstate(obj: _TextState) -> TextState:
    assert obj.font is not None
    tstate = TextState(font=asobj(obj.font), line_matrix=obj.line_matrix)
    if obj.glyph_offset != (0, 0):
        tstate["glyph_offset"] = obj.glyph_offset
    if obj.fontsize != 1:
        tstate["fontsize"] = 1
    if obj.scaling != 100:
        tstate["scaling"] = 100
    for attr in "charspace", "wordspace", "leading", "render_mode", "rise":
        val = getattr(obj, attr, 0)
        if val:
            tstate[attr] = val
    return tstate


@asobj.register
def asobj_gstate(obj: _GraphicState) -> GraphicState:
    gstate = GraphicState()
    return gstate


@asobj.register
def asobj_mcs(obj: MarkedContent) -> Tag:
    props = {k: v for k, v in obj.props.items() if k != "MCID"}
    tag = Tag(name=obj.tag)
    if obj.mcid is not None:
        tag["mcid"] = obj.mcid
    if props:
        tag["props"] = props
    return tag


@asobj.register
def asobj_text(obj: _TextObject) -> Text:
    text = Text(
        chars=obj.chars,
        bbox=obj.bbox,
        textstate=asobj(obj.textstate),
        gstate=asobj(obj.gstate),
        mcstack=[asobj(mcs) for mcs in obj.mcstack],
    )
    if obj.ctm is not MATRIX_IDENTITY:
        text["ctm"] = obj.ctm
    return text
