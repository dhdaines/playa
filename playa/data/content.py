"""Schemas for various content objects.

This module contains schemas (as TypedDict) for content from various
PLAYA objects.

"""

import dataclasses
from typing import List, Tuple, Union

try:
    # We only absolutely need this when using Pydantic TypeAdapter
    from typing_extensions import TypedDict
except ImportError:
    from typing import TypedDict

from playa.color import Color as _Color
from playa.color import ColorSpace as _ColorSpace
from playa.data._asobj import asobj
from playa.data.metadata import Font
from playa.content import DashPattern as _DashPattern
from playa.content import GlyphObject as _GlyphObject
from playa.content import GraphicState as _GraphicState
from playa.content import ImageObject as _ImageObject
from playa.content import MarkedContent as _MarkedContent
from playa.content import PathObject as _PathObject
from playa.content import PathSegment as _PathSegment
from playa.content import TagObject as _TagObject
from playa.content import TextObject as _TextObject
from playa.pdftypes import resolve_all, MATRIX_IDENTITY, Matrix, Point, Rect


class Text(TypedDict, total=False):
    chars: str
    """Unicode string representation of text."""
    bbox: Rect
    """Bounding rectangle for all glyphs in text in default user space."""
    matrix: Matrix
    """Text rendering matrix.  Note that the effective font size
    and the origin can be derived from this."""
    gstate: "GraphicState"
    """Graphic state."""
    mcstack: List["Tag"]
    """Stack of enclosing marked content sections."""


class GraphicState(TypedDict, total=False):
    clipping_path: None  # TODO
    """The current clipping path (sec. 8.5.4), default `None`"""
    linewidth: float
    """Line width in user space units (sec. 8.4.3.2), default 1"""
    linecap: int
    """Line cap style (sec. 8.4.3.3), default 0 """
    linejoin: int
    """Line join style (sec. 8.4.3.4), default 0"""
    miterlimit: float
    """Maximum length of mitered line joins (sec. 8.4.3.5), default 10"""
    dash: "DashPattern"
    """Dash pattern for stroking (sec 8.4.3.6), default solid line `((), 0)`"""
    intent: str
    """Rendering intent (sec. 8.6.5.8), default `RelativeColorimetric`'"""
    stroke_adjustment: bool
    """A flag specifying whether to compensate for possible rasterization
    effects when stroking a path with a line width that is small relative to
    the pixel resolution of the output device (sec. 10.7.5), default `False`"""
    blend_mode: Union[str, List[str]]
    """The current blend mode that shall be used in the transparent imaging
    model (sec. 11.3.5), default `Normal`"""
    smask: Union[None, dict]
    """A soft-mask dictionary (sec. 11.6.5.1) or None, default `None`"""
    salpha: float
    """The constant shape or constant opacity value used for stroking
    operations (sec. 11.3.7.2 & 11.6.4.4), default 1"""
    nalpha: float
    """The constant shape or constant opacity value used for non-stroking
    operations, default 1"""
    alpha_source: bool
    """A flag specifying whether the current soft mask and alpha constant
    parameters shall be interpreted as shape values (true) or opacity values
    (false), default `False`"""
    black_pt_comp: str
    """The black point compensation algorithm that shall be used when
    converting CIE-based colours (sec. 8.6.5.9), default `Default`"""
    flatness: float
    """The precision with which curves shall be rendered on
    the output device (sec. 10.6.2), default 1"""
    scolor: "Color"
    """Colour used for stroking operations, default black `((0,), None)`"""
    scs: "ColorSpace"
    """Colour space used for stroking operations, default `DeviceGray`"""
    ncolor: "Color"
    """Colour used for non-stroking operations, default black `((0,) None)`"""
    ncs: "ColorSpace"
    """Colour space used for non-stroking operations, default `DeviceGray`"""
    font: Font
    """Descriptor of current font."""
    fontsize: float
    """Font size in unscaled text space units (**not** in points, can
    be scaled using a text or glyph's `matrix` to obtain user space
    units), default if not present is 1.0."""
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
    knockout: bool
    """The text knockout flag, shall determine the behaviour of overlapping
    glyphs within a text object in the transparent imaging model (sec. 9.3.8),
    default `True`"""


class DashPattern(TypedDict, total=False):
    dash: Tuple[float, ...]
    """Lengths of dashes and gaps in user space units."""
    phase: float
    """Starting position in the dash pattern, default 0."""


class Color(TypedDict, total=False):
    values: Tuple[float, ...]
    """Component values."""
    pattern: Union[str, None]
    """Pattern name in page resources, if any."""


class ColorSpace(TypedDict, total=False):
    name: str
    """Name of colour space."""
    ncomponents: int
    """Number of components."""
    spec: list
    """Specification."""


class MarkedContent(TypedDict, total=False):
    name: str
    """Marked content section tag name."""
    mcid: int
    """Marked content section ID."""
    props: dict
    """Marked content property dictionary (without MCID)."""


class Tag(TypedDict, total=False):
    name: str
    """Tag name."""
    mcid: int
    """Marked content section ID."""
    props: dict
    """Marked content property dictionary (without MCID)."""


class Image(TypedDict, total=False):
    ctm: Matrix
    """Coordinate transformation matrix, default is `(1, 0, 0, 1, 0, 0)`"""
    xobject_name: str
    """Name of XObject in page resources, if any."""
    bbox: Rect
    """Bounding rectangle for image."""
    srcsize: Tuple[int, int]
    """Size of source image in pixels."""
    bits: int
    """Number of bits per component, if required (default 1)."""
    imagemask: bool
    """True if the image is a mask."""
    stream: dict
    """Content stream dictionary."""
    colorspace: Union[ColorSpace, None]
    """Colour space for this image, if required."""


class Path(TypedDict, total=False):
    ctm: Matrix
    """Coordinate transformation matrix, default is `(1, 0, 0, 1, 0, 0)`"""
    stroke: bool
    """True if the outline of the path is stroked."""
    fill: bool
    """True if the path is filled."""
    evenodd: bool
    """True if the filling of complex paths uses the even-odd
    winding rule, False if the non-zero winding number rule is
    used (PDF 1.7 section 8.5.3.3)"""
    segments: List["PathSegment"]
    """Path segments."""
    gstate: "GraphicState"
    """Graphic state."""
    mcstack: List["Tag"]
    """Stack of enclosing marked content sections."""


class PathSegment(TypedDict, total=False):
    operator: str
    """Normalized path operator (PDF 1.7 section 8.5.2).  Note that "re"
    will be expanded into its constituent line segments."""
    points: List[Point]
    """Point or control points for path segment."""


class Glyph(TypedDict, total=False):
    text: str
    """Unicode string representation of glyph, if any."""
    cid: int
    """Character ID for glyph in font."""
    bbox: Rect
    """Bounding rectangle."""
    matrix: Matrix
    """Rendering matrix for glyph.  Note that the effective font size
    and the origin can be derived from this."""
    displacement: Point
    """Displacement to origin of next glyph."""
    gstate: "GraphicState"
    """Graphic state."""
    mcstack: List["Tag"]
    """Stack of enclosing marked content sections."""


@asobj.register
def asobj_color(obj: _Color) -> Color:
    color = Color(values=obj.values)
    if obj.pattern is not None:
        color["pattern"] = obj.pattern
    return color


@asobj.register
def asobj_colorspace(obj: _ColorSpace) -> ColorSpace:
    cs = ColorSpace(name=obj.name, ncomponents=obj.ncomponents)
    if obj.spec:
        cs["spec"] = asobj(resolve_all(obj.spec))
    return cs


@asobj.register
def asobj_dashpattern(obj: _DashPattern) -> DashPattern:
    dash = DashPattern(dash=obj.dash)
    if obj.phase != 0:
        dash["phase"] = obj.phase
    return dash


GRAPHICSTATE_DEFAULTS = {f.name: f.default for f in dataclasses.fields(_GraphicState)}


@asobj.register
def asobj_gstate(obj: _GraphicState) -> GraphicState:
    gstate = GraphicState()
    if obj.font is not None:
        gstate["font"] = asobj(obj.font)
        # fontsize is always defined with font
        gstate["fontsize"] = obj.fontsize
    for field in (
        "clipping_path",
        "linewidth",
        "linecap",
        "linejoin",
        "miterlimit",
        "dash",
        "intent",
        "stroke_adjustment",
        "blend_mode",
        "smask",
        "salpha",
        "nalpha",
        "alpha_source",
        "black_pt_comp",
        "flatness",
        "scolor",
        "scs",
        "ncolor",
        "ncs",
        "charspace",
        "wordspace",
        "leading",
        "render_mode",
        "rise",
        "knockout",
    ):
        val = getattr(obj, field)
        if val != GRAPHICSTATE_DEFAULTS[field]:
            gstate[field] = asobj(val)
    return gstate


@asobj.register
def asobj_mcs(obj: _MarkedContent) -> MarkedContent:
    props = {k: v for k, v in obj.props.items() if k != "MCID"}
    tag = MarkedContent(name=obj.tag)
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
        matrix=obj.matrix,
    )
    gstate = asobj(obj.gstate)
    if gstate:
        text["gstate"] = gstate
    mcstack = [asobj(mcs) for mcs in obj.mcstack]
    if mcstack:
        text["mcstack"] = mcstack
    return text


@asobj.register
def asobj_tag(obj: _TagObject) -> Tag:
    props = {k: v for k, v in obj.mcs.props.items() if k != "MCID"}
    tag = Tag(name=obj.mcs.tag)
    if obj.mcs.mcid is not None:
        tag["mcid"] = obj.mcs.mcid
    if props:
        tag["props"] = props
    return tag


@asobj.register
def asobj_image(obj: _ImageObject) -> Image:
    img = Image(srcsize=obj.srcsize, bbox=obj.bbox, stream=asobj(obj.stream))
    if obj.ctm is not MATRIX_IDENTITY:
        img["ctm"] = obj.ctm
    if obj.xobjid is not None:
        img["xobject_name"] = obj.xobjid
    if obj.bits != 1:
        img["bits"] = obj.bits
    if obj.imagemask:
        img["imagemask"] = True
    if obj.colorspace is not None:
        img["colorspace"] = asobj(obj.colorspace)
    return img


@asobj.register
def asobj_path(obj: _PathObject) -> Path:
    path = Path(segments=[asobj(seg) for seg in obj.segments])
    gstate = asobj(obj.gstate)
    if gstate:
        path["gstate"] = gstate
    if obj.ctm is not MATRIX_IDENTITY:
        path["ctm"] = obj.ctm
    mcstack = [asobj(mcs) for mcs in obj.mcstack]
    if mcstack:
        path["mcstack"] = mcstack
    for attr in "stroke", "fill", "evenodd":
        val = getattr(obj, attr, False)
        if val:
            path[attr] = val
    return path


@asobj.register
def asobj_path_segment(obj: _PathSegment) -> PathSegment:
    seg = PathSegment(operator=obj.operator)
    if obj.points:
        seg["points"] = list(obj.points)
    return seg


@asobj.register
def asobj_glyph(obj: _GlyphObject) -> Glyph:
    glyph = Glyph(
        cid=obj.cid,
        bbox=obj.bbox,
        matrix=obj.matrix,
        displacement=obj.displacement,
    )
    # But there is a default graphic state
    gstate = asobj(obj.gstate)
    if gstate:
        glyph["gstate"] = gstate
    if obj.text:
        glyph["text"] = obj.text
    mcstack = [asobj(mcs) for mcs in obj.mcstack]
    if mcstack:
        glyph["mcstack"] = mcstack
    return glyph
