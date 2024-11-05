import logging
from dataclasses import dataclass
from typing import (
    List,
    NamedTuple,
    Optional,
    Tuple,
    Union,
)

from playa.color import Color, PDFColorSpace
from playa.font import PDFFont
from playa.pdftypes import ContentStream
from playa.utils import (
    Matrix,
    PathSegment,
    Point,
    Rect,
    apply_matrix_pt,
    get_bound,
)

logger = logging.getLogger(__name__)


@dataclass
class PDFGraphicState:
    linewidth: float = 0
    linecap: Optional[object] = None
    linejoin: Optional[object] = None
    miterlimit: Optional[object] = None
    dash: Optional[Tuple[object, object]] = None
    intent: Optional[object] = None
    flatness: Optional[object] = None
    # stroking color
    scolor: Optional[Color] = None
    # non stroking color
    ncolor: Optional[Color] = None


class Item(NamedTuple):
    itype: str
    x0: float
    y0: float
    x1: float
    y1: float
    name: Optional[str] = None
    tag: Optional[str] = None
    mcid: Optional[int] = None
    objs: Optional[List["Item"]] = None
    linewidth: Optional[float] = None
    pts: Optional[List[Point]] = None
    stroke: bool = False
    fill: bool = False
    evenodd: bool = False
    stroking_color: Optional[Color] = None
    non_stroking_color: Optional[Color] = None
    original_path: Optional[List[PathSegment]] = None
    dashing_style: Optional[Tuple[object, object]] = None
    ncs: Optional[PDFColorSpace] = None
    scs: Optional[PDFColorSpace] = None
    stream: Optional[ContentStream] = None
    srcsize: Optional[Tuple[int, int]] = None
    imagemask: Optional[bool] = None
    bits: Optional[int] = None
    colorspace: Optional[List[PDFColorSpace]] = None
    text: Optional[str] = None
    matrix: Optional[Matrix] = None
    fontname: Optional[str] = None
    upright: Optional[bool] = None
    size: Optional[float] = None

    @property
    def bbox(self) -> Rect:
        return (self.x0, self.y0, self.x1, self.y1)


def LTCurve(
    *,
    linewidth: float,
    pts: List[Point],
    stroke: bool = False,
    fill: bool = False,
    evenodd: bool = False,
    stroking_color: Optional[Color] = None,
    non_stroking_color: Optional[Color] = None,
    original_path: Optional[List[PathSegment]] = None,
    dashing_style: Optional[Tuple[object, object]] = None,
    ncs: Optional[PDFColorSpace] = None,
    scs: Optional[PDFColorSpace] = None,
) -> Item:
    """A generic Bezier curve

    The parameter `original_path` contains the original
    pathing information from the pdf (e.g. for reconstructing Bezier Curves).

    `dashing_style` contains the Dashing information if any.
    """
    bbox = get_bound(pts)
    return Item(
        itype="curve",
        x0=bbox[0],
        y0=bbox[1],
        x1=bbox[2],
        y1=bbox[3],
        pts=pts,
        ncs=ncs,
        scs=scs,
        linewidth=linewidth,
        stroke=stroke,
        fill=fill,
        evenodd=evenodd,
        stroking_color=stroking_color,
        non_stroking_color=non_stroking_color,
        original_path=original_path,
        dashing_style=dashing_style,
    )


def LTLine(
    *,
    linewidth: float,
    p0: Point,
    p1: Point,
    stroke: bool = False,
    fill: bool = False,
    evenodd: bool = False,
    stroking_color: Optional[Color] = None,
    non_stroking_color: Optional[Color] = None,
    original_path: Optional[List[PathSegment]] = None,
    dashing_style: Optional[Tuple[object, object]] = None,
    ncs: Optional[PDFColorSpace] = None,
    scs: Optional[PDFColorSpace] = None,
) -> Item:
    """A single straight line.

    Could be used for separating text or figures.
    """
    bbox = get_bound([p0, p1])
    return Item(
        itype="line",
        x0=bbox[0],
        y0=bbox[1],
        x1=bbox[2],
        y1=bbox[3],
        pts=[p0, p1],
        ncs=ncs,
        scs=scs,
        linewidth=linewidth,
        stroke=stroke,
        fill=fill,
        evenodd=evenodd,
        stroking_color=stroking_color,
        non_stroking_color=non_stroking_color,
        original_path=original_path,
        dashing_style=dashing_style,
    )


def LTRect(
    *,
    linewidth: float,
    bbox: Rect,
    stroke: bool = False,
    fill: bool = False,
    evenodd: bool = False,
    stroking_color: Optional[Color] = None,
    non_stroking_color: Optional[Color] = None,
    original_path: Optional[List[PathSegment]] = None,
    dashing_style: Optional[Tuple[object, object]] = None,
    ncs: Optional[PDFColorSpace] = None,
    scs: Optional[PDFColorSpace] = None,
) -> Item:
    """A rectangle.

    Could be used for framing another pictures or figures.
    """
    x0, y0, x1, y1 = bbox
    if x1 < x0:
        (x0, x1) = (x1, x0)
    if y1 < y0:
        (y0, y1) = (y1, y0)
    item = Item(
        itype="rect",
        x0=x0,
        y0=y0,
        x1=x1,
        y1=y1,
        pts=[(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
        ncs=ncs,
        scs=scs,
        linewidth=linewidth,
        stroke=stroke,
        fill=fill,
        evenodd=evenodd,
        stroking_color=stroking_color,
        non_stroking_color=non_stroking_color,
        original_path=original_path,
        dashing_style=dashing_style,
    )
    return item


def LTImage(name: str, stream: ContentStream, bbox: Rect) -> Item:
    """An image object.

    Embedded images can be in JPEG, Bitmap or JBIG2.
    """
    colorspace = stream.get_any(("CS", "ColorSpace"))
    if not isinstance(colorspace, list):
        colorspace = [colorspace]
    return Item(
        x0=bbox[0],
        y0=bbox[1],
        x1=bbox[2],
        y1=bbox[3],
        itype=name,
        stream=stream,
        srcsize=(stream.get_any(("W", "Width")), stream.get_any(("H", "Height"))),
        imagemask=stream.get_any(("IM", "ImageMask")),
        bits=stream.get_any(("BPC", "BitsPerComponent"), 1),
        colorspace=colorspace,
    )


def LTChar(
    *,
    matrix: Matrix,
    font: PDFFont,
    fontsize: float,
    scaling: float,
    rise: float,
    text: str,
    textwidth: float,
    textdisp: Union[float, Tuple[Optional[float], float]],
    ncs: Optional[PDFColorSpace] = None,
    scs: Optional[PDFColorSpace] = None,
    stroking_color: Optional[Color] = None,
    non_stroking_color: Optional[Color] = None,
) -> Item:
    """Actual letter in the text as a Unicode string."""
    # compute the boundary rectangle.
    adv = textwidth * fontsize * scaling
    vert = font.is_vertical()
    if vert:
        # vertical
        assert isinstance(textdisp, tuple)
        (vx, vy) = textdisp
        if vx is None:
            vx = fontsize * 0.5
        else:
            vx = vx * fontsize * 0.001
        vy = (1000 - vy) * fontsize * 0.001
        bbox_lower_left = (-vx, vy + rise + adv)
        bbox_upper_right = (-vx + fontsize, vy + rise)
    else:
        # horizontal
        descent = font.get_descent() * fontsize
        bbox_lower_left = (0, descent + rise)
        bbox_upper_right = (adv, descent + rise + fontsize)
    (a, b, c, d, e, f) = matrix
    upright = a * d * scaling > 0 and b * c <= 0
    (x0, y0) = apply_matrix_pt(matrix, bbox_lower_left)
    (x1, y1) = apply_matrix_pt(matrix, bbox_upper_right)
    if x1 < x0:
        (x0, x1) = (x1, x0)
    if y1 < y0:
        (y0, y1) = (y1, y0)
    if vert:
        size = x1 - x0
    else:
        size = y1 - y0
    return Item(
        itype="char",
        x0=x0,
        y0=y0,
        x1=x1,
        y1=y1,
        size=size,
        upright=upright,
        text=text,
        matrix=matrix,
        fontname=font.fontname,
        ncs=ncs,
        scs=scs,
        stroking_color=stroking_color,
        non_stroking_color=non_stroking_color,
    )


def LTFigure(*, name: str, bbox: Rect, matrix: Matrix) -> Item:
    """Represents an area used by PDF Form objects.

    PDF Forms can be used to present figures or pictures by embedding yet
    another PDF document within a page. Note that LTFigure objects can appear
    recursively.
    """
    (x, y, w, h) = bbox
    bounds = ((x, y), (x + w, y), (x, y + h), (x + w, y + h))
    bbox = get_bound(apply_matrix_pt(matrix, (p, q)) for (p, q) in bounds)
    return Item(
        itype="figure",
        name=name,
        matrix=matrix,
        x0=bbox[0],
        y0=bbox[1],
        x1=bbox[2],
        y1=bbox[3],
        objs=[],
    )
