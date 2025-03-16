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
from playa.utils import Rect, Matrix
from playa.page import TextObject as _TextObject


class Text(TypedDict, total=False):
    """Text object on a page."""

    chars: str
    """Unicode string representation of text."""
    bbox: Rect
    """Bounding rectangle for all glyphs in text."""
    textstate: "TextState"
    """Text state."""
    gstate: "GraphicState"
    """Graphic state."""
    mcstack: List["Tag"]
    """Stack of enclosing marked content sections."""


class TextState(TypedDict, total=False):
    """Text state."""

    matrix: Matrix
    """Text matrix for current glyph."""
    line_matrix: Matrix
    """Text matrix for start of current line."""
    font: str
    """Name of current font (properties can be found in the page metadata)."""
    font_size: float
    """Font size in unscaled text space units (**not** in points, can
    be scaled using `text_matrix` to obtain default user space units)"""
    char_space: float
    """Character spacing in unscaled text space units."""
    word_space: float
    """Word spacing in unscaled text space units."""
    scaling: float
    """Horizontal scaling factor multiplied by 100."""
    leading: float
    """Leading in unscaled text space units."""
    render_mode: int
    """Text rendering mode (PDF 1.7 Table 106)"""
    rise: float
    """Text rise (for super and subscript) in unscaled text space
    units."""
    knockout: bool
    """Text knockout (PDF 1.7 sec 9.3.8)"""


class GraphicState(TypedDict, total=False):
    """Graphic state."""


class Tag(TypedDict, total=False):
    """Marked content section."""

    name: str


@asobj.register(_TextObject)
def asobj_text(text: _TextObject) -> Text:
    return Text(
        chars=text.chars,
        bbox=text.bbox,
        textstate=asobj(text.textstate),
        gstate=asobj(text.gstate),
        mcstack=[asobj(mcs) for mcs in text.mcstack],
    )
