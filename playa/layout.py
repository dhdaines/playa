import logging
from dataclasses import dataclass
from typing import (
    Iterable,
    Iterator,
    List,
    Optional,
    Tuple,
    Union,
)

from playa.color import PDFColorSpace
from playa.exceptions import PDFValueError
from playa.font import PDFFont
from playa.pdftypes import ContentStream
from playa.utils import (
    Matrix,
    PathSegment,
    Point,
    Rect,
    apply_matrix_pt,
    bbox2str,
    get_bound,
    matrix2str,
)

logger = logging.getLogger(__name__)


Color = Union[
    float,  # Greyscale
    Tuple[float, float, float],  # R, G, B
    Tuple[float, float, float, float],  # C, M, Y, K
]


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


class LTComponent:
    """Object with a bounding box"""

    def __init__(self, bbox: Rect) -> None:
        self.set_bbox(bbox)

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} {bbox2str(self.bbox)}>"

    # Disable comparison.
    def __lt__(self, _: object) -> bool:
        raise PDFValueError

    def __le__(self, _: object) -> bool:
        raise PDFValueError

    def __gt__(self, _: object) -> bool:
        raise PDFValueError

    def __ge__(self, _: object) -> bool:
        raise PDFValueError

    def set_bbox(self, bbox: Rect) -> None:
        (x0, y0, x1, y1) = bbox
        self.x0 = x0
        self.y0 = y0
        self.x1 = x1
        self.y1 = y1
        self.width = x1 - x0
        self.height = y1 - y0
        self.bbox = bbox


class LTCurve(LTComponent):
    """A generic Bezier curve

    The parameter `original_path` contains the original
    pathing information from the pdf (e.g. for reconstructing Bezier Curves).

    `dashing_style` contains the Dashing information if any.
    """

    def __init__(
        self,
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
    ) -> None:
        LTComponent.__init__(self, get_bound(pts))
        self.pts = pts
        self.ncs = ncs
        self.scs = scs
        self.linewidth = linewidth
        self.stroke = stroke
        self.fill = fill
        self.evenodd = evenodd
        self.stroking_color = stroking_color
        self.non_stroking_color = non_stroking_color
        self.original_path = original_path
        self.dashing_style = dashing_style

    def get_pts(self) -> str:
        return ",".join("%.3f,%.3f" % p for p in self.pts)


class LTLine(LTCurve):
    """A single straight line.

    Could be used for separating text or figures.
    """

    def __init__(
        self,
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
    ) -> None:
        LTCurve.__init__(
            self,
            linewidth,
            [p0, p1],
            stroke,
            fill,
            evenodd,
            stroking_color,
            non_stroking_color,
            original_path,
            dashing_style,
            ncs,
            scs,
        )


class LTRect(LTCurve):
    """A rectangle.

    Could be used for framing another pictures or figures.
    """

    def __init__(
        self,
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
    ) -> None:
        (x0, y0, x1, y1) = bbox
        LTCurve.__init__(
            self,
            linewidth,
            [(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
            stroke,
            fill,
            evenodd,
            stroking_color,
            non_stroking_color,
            original_path,
            dashing_style,
            ncs,
            scs,
        )


class LTImage(LTComponent):
    """An image object.

    Embedded images can be in JPEG, Bitmap or JBIG2.
    """

    def __init__(self, name: str, stream: ContentStream, bbox: Rect) -> None:
        LTComponent.__init__(self, bbox)
        self.name = name
        self.stream = stream
        self.srcsize = (stream.get_any(("W", "Width")), stream.get_any(("H", "Height")))
        self.imagemask = stream.get_any(("IM", "ImageMask"))
        self.bits = stream.get_any(("BPC", "BitsPerComponent"), 1)
        self.colorspace = stream.get_any(("CS", "ColorSpace"))
        if not isinstance(self.colorspace, list):
            self.colorspace = [self.colorspace]

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}({self.name}) {bbox2str(self.bbox)} {self.srcsize!r}>"


class LTChar(LTComponent):
    """Actual letter in the text as a Unicode string."""

    def __init__(
        self,
        matrix: Matrix,
        font: PDFFont,
        fontsize: float,
        scaling: float,
        rise: float,
        text: str,
        textwidth: float,
        textdisp: Union[float, Tuple[Optional[float], float]],
        ncs: PDFColorSpace,
        graphicstate: PDFGraphicState,
        # The ordering may seem strange but it needs to match pdfminer.
        scs: Optional[PDFColorSpace] = None,
        stroking_color: Optional[Color] = None,
        non_stroking_color: Optional[Color] = None,
    ) -> None:
        self.text = text
        self.matrix = matrix
        self.fontname = font.fontname
        self.ncs = ncs
        self.scs = scs
        self.stroking_color = stroking_color
        self.non_stroking_color = non_stroking_color
        self.graphicstate = graphicstate
        self.adv = textwidth * fontsize * scaling
        # compute the boundary rectangle.
        if font.is_vertical():
            # vertical
            assert isinstance(textdisp, tuple)
            (vx, vy) = textdisp
            if vx is None:
                vx = fontsize * 0.5
            else:
                vx = vx * fontsize * 0.001
            vy = (1000 - vy) * fontsize * 0.001
            bbox_lower_left = (-vx, vy + rise + self.adv)
            bbox_upper_right = (-vx + fontsize, vy + rise)
        else:
            # horizontal
            descent = font.get_descent() * fontsize
            bbox_lower_left = (0, descent + rise)
            bbox_upper_right = (self.adv, descent + rise + fontsize)
        (a, b, c, d, e, f) = self.matrix
        self.upright = a * d * scaling > 0 and b * c <= 0
        (x0, y0) = apply_matrix_pt(self.matrix, bbox_lower_left)
        (x1, y1) = apply_matrix_pt(self.matrix, bbox_upper_right)
        if x1 < x0:
            (x0, x1) = (x1, x0)
        if y1 < y0:
            (y0, y1) = (y1, y0)
        LTComponent.__init__(self, (x0, y0, x1, y1))
        if font.is_vertical():
            self.size = self.width
        else:
            self.size = self.height

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} {bbox2str(self.bbox)} matrix={matrix2str(self.matrix)} font={self.fontname!r} adv={self.adv} text={self.text!r}>"


class LTFigure(LTComponent):
    """Represents an area used by PDF Form objects.

    PDF Forms can be used to present figures or pictures by embedding yet
    another PDF document within a page. Note that LTFigure objects can appear
    recursively.
    """

    def __init__(self, name: str, bbox: Rect, matrix: Matrix) -> None:
        self.name = name
        self.matrix = matrix
        (x, y, w, h) = bbox
        bounds = ((x, y), (x + w, y), (x, y + h), (x + w, y + h))
        bbox = get_bound(apply_matrix_pt(matrix, (p, q)) for (p, q) in bounds)
        LTComponent.__init__(self, bbox)
        self._objs: List[LTComponent] = []

    def __iter__(self) -> Iterator[LTComponent]:
        return iter(self._objs)

    def __len__(self) -> int:
        return len(self._objs)

    def add(self, obj: LTComponent) -> None:
        self._objs.append(obj)

    def extend(self, objs: Iterable[LTComponent]) -> None:
        for obj in objs:
            self.add(obj)

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}({self.name}) {bbox2str(self.bbox)} matrix={matrix2str(self.matrix)}>"
