import logging
from typing import (
    Generic,
    Iterable,
    Iterator,
    List,
    Optional,
    Tuple,
    TypeVar,
    Union,
    cast,
)

from playa.color import PDFColorSpace
from playa.exceptions import PDFValueError
from playa.font import PDFFont
from playa.pdftypes import ContentStream
from playa.utils import (
    INF,
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


class PDFGraphicState:
    def __init__(self) -> None:
        self.linewidth: float = 0
        self.linecap: Optional[object] = None
        self.linejoin: Optional[object] = None
        self.miterlimit: Optional[object] = None
        self.dash: Optional[Tuple[object, object]] = None
        self.intent: Optional[object] = None
        self.flatness: Optional[object] = None

        # stroking color
        self.scolor: Optional[Color] = None

        # non stroking color
        self.ncolor: Optional[Color] = None

    def copy(self) -> "PDFGraphicState":
        obj = PDFGraphicState()
        obj.linewidth = self.linewidth
        obj.linecap = self.linecap
        obj.linejoin = self.linejoin
        obj.miterlimit = self.miterlimit
        obj.dash = self.dash
        obj.intent = self.intent
        obj.flatness = self.flatness
        obj.scolor = self.scolor
        obj.ncolor = self.ncolor
        return obj

    def __repr__(self) -> str:
        return (
            "<PDFGraphicState: linewidth=%r, linecap=%r, linejoin=%r, "
            " miterlimit=%r, dash=%r, intent=%r, flatness=%r, "
            " stroking color=%r, non stroking color=%r>"
            % (
                self.linewidth,
                self.linecap,
                self.linejoin,
                self.miterlimit,
                self.dash,
                self.intent,
                self.flatness,
                self.scolor,
                self.ncolor,
            )
        )


class LTItem:
    """Interface for things that can be analyzed"""

    # Any item could be in a marked content section
    mcid: Optional[int] = None
    # Which could have a tag
    tag: Optional[str] = None


class LTText:
    """Interface for things that have text"""

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} {self.get_text()!r}>"

    def get_text(self) -> str:
        """Text contained in this object"""
        raise NotImplementedError


class LTComponent(LTItem):
    """Object with a bounding box"""

    def __init__(self, bbox: Rect) -> None:
        LTItem.__init__(self)
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

    def is_empty(self) -> bool:
        return self.width <= 0 or self.height <= 0

    def is_hoverlap(self, obj: "LTComponent") -> bool:
        assert isinstance(obj, LTComponent), str(type(obj))
        return obj.x0 <= self.x1 and self.x0 <= obj.x1

    def hdistance(self, obj: "LTComponent") -> float:
        assert isinstance(obj, LTComponent), str(type(obj))
        if self.is_hoverlap(obj):
            return 0
        else:
            return min(abs(self.x0 - obj.x1), abs(self.x1 - obj.x0))

    def hoverlap(self, obj: "LTComponent") -> float:
        assert isinstance(obj, LTComponent), str(type(obj))
        if self.is_hoverlap(obj):
            return min(abs(self.x0 - obj.x1), abs(self.x1 - obj.x0))
        else:
            return 0

    def is_voverlap(self, obj: "LTComponent") -> bool:
        assert isinstance(obj, LTComponent), str(type(obj))
        return obj.y0 <= self.y1 and self.y0 <= obj.y1

    def vdistance(self, obj: "LTComponent") -> float:
        assert isinstance(obj, LTComponent), str(type(obj))
        if self.is_voverlap(obj):
            return 0
        else:
            return min(abs(self.y0 - obj.y1), abs(self.y1 - obj.y0))

    def voverlap(self, obj: "LTComponent") -> float:
        assert isinstance(obj, LTComponent), str(type(obj))
        if self.is_voverlap(obj):
            return min(abs(self.y0 - obj.y1), abs(self.y1 - obj.y0))
        else:
            return 0


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


class LTAnno(LTItem, LTText):
    """Actual letter in the text as a Unicode string.

    Note that, while a LTChar object has actual boundaries, LTAnno objects does
    not, as these are "virtual" characters, inserted by a layout analyzer
    according to the relationship between two characters (e.g. a space).
    """

    def __init__(self, text: str) -> None:
        self._text = text

    def get_text(self) -> str:
        return self._text


class LTChar(LTComponent, LTText):
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
        LTText.__init__(self)
        self._text = text
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
        return f"<{self.__class__.__name__} {bbox2str(self.bbox)} matrix={matrix2str(self.matrix)} font={self.fontname!r} adv={self.adv} text={self.get_text()!r}>"

    def get_text(self) -> str:
        return self._text


LTItemT = TypeVar("LTItemT", bound=LTItem)


class LTContainer(LTComponent, Generic[LTItemT]):
    """Object that can be extended and analyzed"""

    def __init__(self, bbox: Rect) -> None:
        LTComponent.__init__(self, bbox)
        self._objs: List[LTItemT] = []

    def __iter__(self) -> Iterator[LTItemT]:
        return iter(self._objs)

    def __len__(self) -> int:
        return len(self._objs)

    def add(self, obj: LTItemT) -> None:
        self._objs.append(obj)

    def extend(self, objs: Iterable[LTItemT]) -> None:
        for obj in objs:
            self.add(obj)


class LTExpandableContainer(LTContainer[LTItemT]):
    def __init__(self) -> None:
        LTContainer.__init__(self, (+INF, +INF, -INF, -INF))

    # Incompatible override: we take an LTComponent (with bounding box), but
    # super() LTContainer only considers LTItem (no bounding box).
    def add(self, obj: LTComponent) -> None:  # type: ignore[override]
        LTContainer.add(self, cast(LTItemT, obj))
        self.set_bbox(
            (
                min(self.x0, obj.x0),
                min(self.y0, obj.y0),
                max(self.x1, obj.x1),
                max(self.y1, obj.y1),
            ),
        )


class LTLayoutContainer(LTContainer[LTComponent]):
    def __init__(self, bbox: Rect) -> None:
        LTContainer.__init__(self, bbox)


class LTFigure(LTLayoutContainer):
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
        LTLayoutContainer.__init__(self, bbox)

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}({self.name}) {bbox2str(self.bbox)} matrix={matrix2str(self.matrix)}>"


class LTPage(LTLayoutContainer):
    """Represents an entire page.

    Like any other LTLayoutContainer, an LTPage can be iterated to obtain child
    objects like LTTextBox, LTFigure, LTImage, LTRect, LTCurve and LTLine.
    """

    def __init__(self, pageid: int, bbox: Rect, rotate: float = 0) -> None:
        LTLayoutContainer.__init__(self, bbox)
        self.pageid = pageid
        self.rotate = rotate

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}({self.pageid!r}) {bbox2str(self.bbox)} rotate={self.rotate!r}>"
