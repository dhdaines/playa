"""
Reimplementation of pdfminer.six layout analysis on top of PLAYA.
"""

import heapq
import logging
import multiprocessing
from functools import partial, singledispatch
from multiprocessing.context import BaseContext
from pathlib import Path
from typing import (
    Any,
    Callable,
    Dict,
    Generic,
    Iterable,
    Iterator,
    List,
    Optional,
    Sequence,
    Set,
    Tuple,
    TypeVar,
    Union,
)

from mypy_extensions import trait

import playa
from playa import pdftypes
from playa.color import ColorSpace
from playa.data_structures import NameTree, NumberTree
from playa.document import Document as PDFDocument
from playa.exceptions import PDFException
from playa.content import (
    ContentObject,
    GlyphObject,
    GraphicState,
    ImageObject,
    MarkedContent,
    PathOperator,
    PathSegment as PLAYAPathSegment,
)
from playa.page import Page
from playa.page import Page as PDFPage
from playa.page import PathObject, TextObject, XObjectObject
from playa.parser import PSLiteral, PDFObject
from playa.pdftypes import ObjRef as PDFObjRef
from playa.pdftypes import resolve1, resolve_all, LIT, KWD
from playa.utils import (
    Matrix,
    PDFDocEncoding,
    Point,
    Rect,
    apply_matrix_pt,
    decode_text,
    get_bound,
    transform_bbox,
)

PSException = Exception
__all__ = [
    "ColorSpace",
    "GraphicState",
    "KWD",
    "LIT",
    "NameTree",
    "NumberTree",
    "PDFDocEncoding",
    "PDFDocument",
    "PDFPage",
    "PDFException",
    "PDFObjRef",
    "PDFObject",
    "PSException",
    "PSLiteral",
    "decode_text",
    "extract",
    "extract_page",
    "pdftypes",
    "resolve1",
    "resolve_all",
]

# Contains much code from layout.py and utils.py in pdfminer.six:
# Copyright (c) 2004-2016  Yusuke Shinyama <yusuke at shinyama dot jp>
# MIT License (as with PLAYA in general)

logger = logging.getLogger(__name__)
LTComponentT = TypeVar("LTComponentT", bound="LTComponent")
_T = TypeVar("_T")
# This is **not** infinity, just an arbitrary big number we use for
# initializing bounding boxes.
INF = (1 << 31) - 1
# This is an "infinite" bounding box used as a default
BBOX_INF = (+INF, +INF, -INF, -INF)
# Ugly pdfminer.six type which represents what it *actually* puts in
# `LTCurve.original_path` (see
# https://github.com/pdfminer/pdfminer.six/issues/1180)
PathSegment = Union[
    Tuple[str],  # Literal['h']
    Tuple[str, Point],  # Literal['m', 'l']
    Tuple[str, Point, Point],  # Literal['v', 'y']
    Tuple[str, Point, Point, Point],
]  # Literal['c']


class PDFTypeError(PDFException):
    """
    TypeError, but for PDFs (not a subclass of TypeError, unlike in pdfminer.six)
    """

    pass


class PDFValueError(PDFException):
    """
    ValueError, but for PDFs (not a subclass of ValueError, unlike in pdfminer.six)
    """

    pass


def uniq(objs: Iterable[_T]) -> Iterator[_T]:
    """Eliminates duplicated elements."""
    # Duplicated here means the same object (this horrible code was
    # horribly written without any notion of hashable or non-hashable
    # types, SMH)
    done: Set[int] = set()
    for obj in objs:
        if id(obj) in done:
            continue
        done.add(id(obj))
        yield obj


def fsplit(pred: Callable[[_T], bool], objs: Iterable[_T]) -> Tuple[List[_T], List[_T]]:
    """Split a list into two classes according to the predicate."""
    t = []
    f = []
    for obj in objs:
        if pred(obj):
            t.append(obj)
        else:
            f.append(obj)
    return t, f


def drange(v0: float, v1: float, d: int) -> range:
    """Returns a discrete range."""
    return range(int(v0) // d, int(v1 + d) // d)


def bbox2str(bbox: Rect) -> str:
    (x0, y0, x1, y1) = bbox
    return f"{x0:.3f},{y0:.3f},{x1:.3f},{y1:.3f}"


def matrix2str(m: Matrix) -> str:
    (a, b, c, d, e, f) = m
    return f"[{a:.2f},{b:.2f},{c:.2f},{d:.2f}, ({e:.2f},{f:.2f})]"


class Plane(Generic[LTComponentT]):
    """A set-like data structure for objects placed on a plane.

    Can efficiently find objects in a certain rectangular area.
    It maintains two parallel lists of objects, each of
    which is sorted by its x or y coordinate.
    """

    def __init__(self, bbox: Rect, gridsize: int = 50) -> None:
        self._seq: List[LTComponentT] = []  # preserve the object order.
        self._objs: Dict[int, LTComponentT] = {}  # store unique objects
        self._grid: Dict[Point, List[LTComponentT]] = {}
        self.gridsize = gridsize
        (self.x0, self.y0, self.x1, self.y1) = bbox

    def __repr__(self) -> str:
        return "<Plane objs=%r>" % list(self)

    def __iter__(self) -> Iterator[LTComponentT]:
        for obj in self._seq:
            if id(obj) in self._objs:
                yield obj

    def __len__(self) -> int:
        return len(self._objs)

    def __contains__(self, obj: LTComponentT) -> bool:
        return id(obj) in self._objs

    def _getrange(self, bbox: Rect) -> Iterator[Point]:
        (x0, y0, x1, y1) = bbox
        if x1 <= self.x0 or self.x1 <= x0 or y1 <= self.y0 or self.y1 <= y0:
            return
        x0 = max(self.x0, x0)
        y0 = max(self.y0, y0)
        x1 = min(self.x1, x1)
        y1 = min(self.y1, y1)
        for grid_y in drange(y0, y1, self.gridsize):
            for grid_x in drange(x0, x1, self.gridsize):
                yield (grid_x, grid_y)

    def extend(self, objs: Iterable[LTComponentT]) -> None:
        for obj in objs:
            self.add(obj)

    def add(self, obj: LTComponentT) -> None:
        """Place an object."""
        for k in self._getrange((obj.x0, obj.y0, obj.x1, obj.y1)):
            if k not in self._grid:
                r: List[LTComponentT] = []
                self._grid[k] = r
            else:
                r = self._grid[k]
            r.append(obj)
        self._seq.append(obj)
        self._objs[id(obj)] = obj

    def remove(self, obj: LTComponentT) -> None:
        """Displace an object."""
        for k in self._getrange((obj.x0, obj.y0, obj.x1, obj.y1)):
            try:
                self._grid[k].remove(obj)
            except (KeyError, ValueError):
                pass
        del self._objs[id(obj)]

    def find(self, bbox: Rect) -> Iterator[LTComponentT]:
        """Finds objects that are in a certain area."""
        (x0, y0, x1, y1) = bbox
        done: Set[int] = set()
        for k in self._getrange(bbox):
            if k not in self._grid:
                continue
            for obj in self._grid[k]:
                if id(obj) in done:
                    continue
                done.add(id(obj))
                if obj.x1 <= x0 or x1 <= obj.x0 or obj.y1 <= y0 or y1 <= obj.y0:
                    continue
                yield obj


class IndexAssigner:
    def __init__(self, index: int = 0) -> None:
        self.index = index

    def run(self, obj: "LTItem") -> None:
        if isinstance(obj, LTTextBox):
            obj.index = self.index
            self.index += 1
        elif isinstance(obj, LTTextGroup):
            for x in obj:
                self.run(x)


class LAParams:
    """Parameters for layout analysis

    :param line_overlap: If two characters have more overlap than this they
        are considered to be on the same line. The overlap is specified
        relative to the minimum height of both characters.
    :param char_margin: If two characters are closer together than this
        margin they are considered part of the same line. The margin is
        specified relative to the width of the character.
    :param word_margin: If two characters on the same line are further apart
        than this margin then they are considered to be two separate words, and
        an intermediate space will be added for readability. The margin is
        specified relative to the width of the character.
    :param line_margin: If two lines are are close together they are
        considered to be part of the same paragraph. The margin is
        specified relative to the height of a line.
    :param boxes_flow: Specifies how much a horizontal and vertical position
        of a text matters when determining the order of text boxes. The value
        should be within the range of -1.0 (only horizontal position
        matters) to +1.0 (only vertical position matters). You can also pass
        `None` to disable advanced layout analysis, and instead return text
        based on the position of the bottom left corner of the text box.
    :param detect_vertical: If vertical text should be considered during
        layout analysis
    :param all_texts: If layout analysis should be performed on text in
        figures.
    """

    def __init__(
        self,
        line_overlap: float = 0.5,
        char_margin: float = 2.0,
        line_margin: float = 0.5,
        word_margin: float = 0.1,
        boxes_flow: Optional[float] = 0.5,
        detect_vertical: bool = False,
        all_texts: bool = False,
    ) -> None:
        self.line_overlap = line_overlap
        self.char_margin = char_margin
        self.line_margin = line_margin
        self.word_margin = word_margin
        self.boxes_flow = boxes_flow
        self.detect_vertical = detect_vertical
        self.all_texts = all_texts

        self._validate()

    def _validate(self) -> None:
        if self.boxes_flow is not None:
            boxes_flow_err_msg = (
                "LAParam boxes_flow should be None, or a number between -1 and +1"
            )
            if not isinstance(self.boxes_flow, (int, float)):
                raise PDFTypeError(boxes_flow_err_msg)
            if not -1 <= self.boxes_flow <= 1:
                raise PDFValueError(boxes_flow_err_msg)

    def __repr__(self) -> str:
        return (
            "<LAParams: char_margin=%.1f, line_margin=%.1f, "
            "word_margin=%.1f all_texts=%r>"
            % (self.char_margin, self.line_margin, self.word_margin, self.all_texts)
        )


@trait
class LTItem:
    """Interface for things that can be analyzed"""

    def analyze(self, laparams: LAParams) -> None:
        """Perform the layout analysis."""


@trait
class LTText:
    """Interface for things that have text"""

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} {self.get_text()!r}>"

    def get_text(self) -> str:
        """Text contained in this object"""
        raise NotImplementedError


class LTComponent(LTItem):
    """Object with a bounding box"""

    def __init__(
        self, bbox: Union[Rect, None] = None, mcstack: Tuple[MarkedContent, ...] = ()
    ) -> None:
        if bbox is None:
            # No initialization, for pickling purposes (see
            # https://mypyc.readthedocs.io/en/latest/differences_from_python.html#pickling-and-copying-objects)
            return
        self.set_bbox(bbox)
        self.mcstack = mcstack

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} {bbox2str(self.bbox)}>"

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
        return obj.x0 <= self.x1 and self.x0 <= obj.x1

    def hdistance(self, obj: "LTComponent") -> float:
        if self.is_hoverlap(obj):
            return 0
        else:
            return min(abs(self.x0 - obj.x1), abs(self.x1 - obj.x0))

    def hoverlap(self, obj: "LTComponent") -> float:
        if self.is_hoverlap(obj):
            return min(abs(self.x0 - obj.x1), abs(self.x1 - obj.x0))
        else:
            return 0

    def is_voverlap(self, obj: "LTComponent") -> bool:
        return obj.y0 <= self.y1 and self.y0 <= obj.y1

    def vdistance(self, obj: "LTComponent") -> float:
        if self.is_voverlap(obj):
            return 0
        else:
            return min(abs(self.y0 - obj.y1), abs(self.y1 - obj.y0))

    def voverlap(self, obj: "LTComponent") -> float:
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
        path: Union[PathObject, None] = None,
        pts: List[Point] = [],  # These are actually immutable so not a problem
        transformed_path: List[PathSegment] = [],
    ) -> None:
        if path is None:
            # No initialization, for pickling purposes
            return
        super().__init__(get_bound(pts), path.mcstack)
        self.pts = pts
        self.linewidth = path.gstate.linewidth
        self.stroke = path.stroke
        self.fill = path.fill
        self.evenodd = path.evenodd
        gstate = path.gstate
        self.graphicstate = gstate
        self.stroking_color = gstate.scolor
        self.non_stroking_color = gstate.ncolor
        self.scs = gstate.scs
        self.ncs = gstate.ncs
        self.original_path = transformed_path
        self.dashing_style = gstate.dash

    def get_pts(self) -> str:
        return ",".join("%.3f,%.3f" % p for p in self.pts)


class LTLine(LTCurve):
    """A single straight line.

    Could be used for separating text or figures.
    """

    def __init__(
        self,
        path: Union[PathObject, None] = None,
        p0: Point = (0, 0),
        p1: Point = (0, 0),
        transformed_path: List[PathSegment] = [],
    ) -> None:
        if path is None:
            # No initialization, for pickling purposes
            return
        LTCurve.__init__(
            self,
            path,
            [p0, p1],
            transformed_path,
        )


class LTRect(LTCurve):
    """A rectangle.

    Could be used for framing another pictures or figures.
    """

    def __init__(
        self,
        path: Union[PathObject, None] = None,
        bbox: Rect = (0, 0, 0, 0),
        transformed_path: List[PathSegment] = [],
    ) -> None:
        if path is None:
            # No initialization, for pickling purposes
            return
        (x0, y0, x1, y1) = bbox
        LTCurve.__init__(
            self,
            path,
            [(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
            transformed_path,
        )


class LTImage(LTComponent):
    """An image object.

    Embedded images can be in JPEG, Bitmap or JBIG2.
    """

    def __init__(self, obj: Union[ImageObject, None] = None) -> None:
        if obj is None:
            # No initialization, for pickling purposes
            return
        super().__init__(obj.bbox, obj.mcstack)
        # Inline images don't actually have an xobjid, so we make shit
        # up like pdfminer.six does.
        if obj.xobjid is None:
            self.name = str(id(obj))
        else:
            self.name = obj.xobjid
        self.stream = obj.stream
        self.srcsize = obj.srcsize
        self.imagemask = obj.imagemask
        self.bits = obj.bits
        self.colorspace = obj.colorspace

    def __repr__(self) -> str:
        return (
            f"<{self.__class__.__name__}({self.name})"
            f" {bbox2str(self.bbox)} {self.srcsize!r}>"
        )


class LTAnno(LTItem, LTText):
    """Actual letter in the text as a Unicode string.

    Note that, while a LTChar object has actual boundaries, LTAnno objects does
    not, as these are "virtual" characters, inserted by a layout analyzer
    according to the relationship between two characters (e.g. a space).
    """

    def __init__(self, text: Union[str, None] = None) -> None:
        if text is None:
            # No initialization, for pickling purposes
            return
        self._text = text

    def get_text(self) -> str:
        return self._text


class LTChar(LTComponent, LTText):
    """Actual letter in the text as a Unicode string."""

    def __init__(
        self,
        glyph: Union[GlyphObject, None] = None,
    ) -> None:
        super().__init__()
        if glyph is None:
            # No initialization, for pickling purposes
            return
        gstate = glyph.gstate
        matrix = glyph.matrix
        font = glyph.font
        if glyph.text is None:
            logger.debug("undefined: %r, %r", font, glyph.cid)
            # Horrible awful pdfminer.six behaviour
            self._text = "(cid:%d)" % glyph.cid
        else:
            self._text = glyph.text
        self.mcstack = glyph.mcstack
        self.fontname = font.fontname
        self.graphicstate = gstate
        self.render_mode = gstate.render_mode
        self.stroking_color = gstate.scolor
        self.non_stroking_color = gstate.ncolor
        self.scs = gstate.scs
        self.ncs = gstate.ncs
        scaling = gstate.scaling * 0.01
        fontsize = gstate.fontsize
        (a, b, c, d, e, f) = matrix
        # FIXME: Still really not sure what this means
        self.upright = a * d * scaling > 0 and b * c <= 0
        # Unscale the matrix to match pdfminer.six
        xscale = 1 / (fontsize * scaling)
        yscale = 1 / fontsize
        self.matrix = (a * xscale, b * yscale, c * xscale, d * yscale, e, f)
        # Recreate pdfminer.six's bogus bboxes
        if font.vertical:
            vdisp = font.vdisp(glyph.cid)
            self.adv = vdisp * fontsize
            vx, vy = font.position(glyph.cid)
            textbox = (-vx, vy + vdisp, -vx + 1, vy)
        else:
            textwidth = font.hdisp(glyph.cid)
            self.adv = textwidth * fontsize * scaling
            descent = font.descent * font.matrix[3]
            textbox = (0, descent, textwidth, descent + 1)
        miner_box = transform_bbox(matrix, textbox)
        super().__init__(miner_box, glyph.mcstack)
        # FIXME: This is quite wrong for rotated glyphs, but so is pdfminer.six
        if font.vertical:
            self.size = self.width
        else:
            self.size = self.height

    def __repr__(self) -> str:
        return (
            f"<{self.__class__.__name__} {bbox2str(self.bbox)} "
            f"matrix={matrix2str(self.matrix)} font={self.fontname!r} "
            f"adv={self.adv} text={self.get_text()!r}>"
        )

    def get_text(self) -> str:
        return self._text


LTItemT = TypeVar("LTItemT", bound=LTItem)


class LTContainer(LTComponent, Generic[LTItemT]):
    """Object that can be extended and analyzed"""

    def __init__(
        self, bbox: Union[Rect, None] = None, mcstack: Tuple[MarkedContent, ...] = ()
    ) -> None:
        if bbox is None:
            # No initialization, for pickling purposes
            return
        super().__init__(bbox, mcstack)
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

    def analyze(self, laparams: LAParams) -> None:
        for obj in self._objs:
            obj.analyze(laparams)


class LTExpandableContainer(LTContainer):
    def __init__(self) -> None:
        super().__init__(BBOX_INF)

    def add(self, obj: LTComponent) -> None:  # type: ignore[override]
        super().add(obj)
        self.set_bbox(
            (
                min(self.x0, obj.x0),
                min(self.y0, obj.y0),
                max(self.x1, obj.x1),
                max(self.y1, obj.y1),
            ),
        )


class LTTextContainer(LTExpandableContainer, LTText):
    def __init__(self) -> None:
        super().__init__()

    def get_text(self) -> str:
        return "".join(
            obj.get_text() for obj in self if isinstance(obj, LTText)
        )


TextLineElement = Union[LTChar, LTAnno]


class LTTextLine(LTTextContainer):
    """Contains a list of LTChar objects that represent a single text line.

    The characters are aligned either horizontally or vertically, depending on
    the text's writing mode.
    """

    def __init__(self, word_margin: float = 0.0) -> None:
        super().__init__()
        self.word_margin = word_margin

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} {bbox2str(self.bbox)} {self.get_text()!r}>"

    def analyze(self, laparams: LAParams) -> None:
        for obj in self._objs:
            obj.analyze(laparams)
        # FIXME: Should probably inherit mcstack somehow
        LTContainer.add(self, LTAnno("\n"))

    def find_neighbors(
        self,
        plane: Plane[LTComponentT],
        ratio: float,
    ) -> List["LTTextLine"]:
        raise NotImplementedError

    def is_empty(self) -> bool:
        return super().is_empty() or self.get_text().isspace()


class LTTextLineHorizontal(LTTextLine):
    def __init__(self, word_margin: float = 0.0) -> None:
        super().__init__(word_margin)
        self._x1 = +INF + 0.0

    # Incompatible override: we take an LTComponent (with bounding box), but
    # LTContainer only considers LTItem (no bounding box).
    def add(self, obj: LTComponent) -> None:  # type: ignore[override]
        if isinstance(obj, LTChar) and self.word_margin:
            margin = self.word_margin * max(obj.width, obj.height)
            if self._x1 < obj.x0 - margin:
                # FIXME: Should probably inherit mcstack somehow
                LTContainer.add(self, LTAnno(" "))
        self._x1 = obj.x1
        super().add(obj)

    def find_neighbors(
        self,
        plane: Plane[LTComponentT],
        ratio: float,
    ) -> List[LTTextLine]:
        """Finds neighboring LTTextLineHorizontals in the plane.

        Returns a list of other LTTestLineHorizontals in the plane which are
        close to self. "Close" can be controlled by ratio. The returned objects
        will be the same height as self, and also either left-, right-, or
        centrally-aligned.
        """
        d = ratio * self.height
        objs = plane.find((self.x0, self.y0 - d, self.x1, self.y1 + d))
        return [
            obj
            for obj in objs
            if (
                isinstance(obj, LTTextLineHorizontal)
                and self._is_same_height_as(obj, tolerance=d)
                and (
                    self._is_left_aligned_with(obj, tolerance=d)
                    or self._is_right_aligned_with(obj, tolerance=d)
                    or self._is_centrally_aligned_with(obj, tolerance=d)
                )
            )
        ]

    def _is_left_aligned_with(self, other: LTComponent, tolerance: float = 0.0) -> bool:
        """Whether the left-hand edge of `other` is within `tolerance`."""
        return abs(other.x0 - self.x0) <= tolerance

    def _is_right_aligned_with(
        self, other: LTComponent, tolerance: float = 0.0
    ) -> bool:
        """Whether the right-hand edge of `other` is within `tolerance`."""
        return abs(other.x1 - self.x1) <= tolerance

    def _is_centrally_aligned_with(
        self,
        other: LTComponent,
        tolerance: float = 0,
    ) -> bool:
        """Whether the horizontal center of `other` is within `tolerance`."""
        return abs((other.x0 + other.x1) / 2 - (self.x0 + self.x1) / 2) <= tolerance

    def _is_same_height_as(self, other: LTComponent, tolerance: float = 0) -> bool:
        return abs(other.height - self.height) <= tolerance


class LTTextLineVertical(LTTextLine):
    def __init__(self, word_margin: float = 0.0) -> None:
        super().__init__(word_margin)
        self._y0: float = -INF + 0.0

    # Incompatible override: we take an LTComponent (with bounding box), but
    # LTContainer only considers LTItem (no bounding box).
    def add(self, obj: LTComponent) -> None:  # type: ignore[override]
        if isinstance(obj, LTChar) and self.word_margin:
            margin = self.word_margin * max(obj.width, obj.height)
            if obj.y1 + margin < self._y0:
                # FIXME: Should probably inherit mcstack somehow
                LTContainer.add(self, LTAnno(" "))
        self._y0 = obj.y0
        super().add(obj)

    def find_neighbors(
        self,
        plane: Plane[LTComponentT],
        ratio: float,
    ) -> List[LTTextLine]:
        """Finds neighboring LTTextLineVerticals in the plane.

        Returns a list of other LTTextLineVerticals in the plane which are
        close to self. "Close" can be controlled by ratio. The returned objects
        will be the same width as self, and also either upper-, lower-, or
        centrally-aligned.
        """
        d = ratio * self.width
        objs = plane.find((self.x0 - d, self.y0, self.x1 + d, self.y1))
        return [
            obj
            for obj in objs
            if (
                isinstance(obj, LTTextLineVertical)
                and self._is_same_width_as(obj, tolerance=d)
                and (
                    self._is_lower_aligned_with(obj, tolerance=d)
                    or self._is_upper_aligned_with(obj, tolerance=d)
                    or self._is_centrally_aligned_with(obj, tolerance=d)
                )
            )
        ]

    def _is_lower_aligned_with(self, other: LTComponent, tolerance: float = 0) -> bool:
        """Whether the lower edge of `other` is within `tolerance`."""
        return abs(other.y0 - self.y0) <= tolerance

    def _is_upper_aligned_with(self, other: LTComponent, tolerance: float = 0) -> bool:
        """Whether the upper edge of `other` is within `tolerance`."""
        return abs(other.y1 - self.y1) <= tolerance

    def _is_centrally_aligned_with(
        self,
        other: LTComponent,
        tolerance: float = 0,
    ) -> bool:
        """Whether the vertical center of `other` is within `tolerance`."""
        return abs((other.y0 + other.y1) / 2 - (self.y0 + self.y1) / 2) <= tolerance

    def _is_same_width_as(self, other: LTComponent, tolerance: float) -> bool:
        return abs(other.width - self.width) <= tolerance


class LTTextBox(LTTextContainer):
    """Represents a group of text chunks in a rectangular area.

    Note that this box is created by geometric analysis and does not
    necessarily represents a logical boundary of the text. It contains a list
    of LTTextLine objects.
    """

    def __init__(self) -> None:
        super().__init__()
        self.index: int = -1

    def __repr__(self) -> str:
        return (
            f"<{self.__class__.__name__}({self.index}) "
            f"{bbox2str(self.bbox)} {self.get_text()!r}>"
        )

    def get_writing_mode(self) -> str:
        raise NotImplementedError


class LTTextBoxHorizontal(LTTextBox):
    def analyze(self, laparams: LAParams) -> None:
        super().analyze(laparams)
        self._objs.sort(key=lambda obj: -obj.y1)

    def get_writing_mode(self) -> str:
        return "lr-tb"


class LTTextBoxVertical(LTTextBox):
    def analyze(self, laparams: LAParams) -> None:
        super().analyze(laparams)
        self._objs.sort(key=lambda obj: -obj.x1)

    def get_writing_mode(self) -> str:
        return "tb-rl"


TextGroupElement = Union[LTTextBox, "LTTextGroup"]


class LTTextGroup(LTTextContainer):
    def __init__(self, objs: Iterable[TextGroupElement] = ()) -> None:
        super().__init__()
        self.extend(objs)


class LTTextGroupLRTB(LTTextGroup):
    def analyze(self, laparams: LAParams) -> None:
        super().analyze(laparams)
        assert laparams.boxes_flow is not None
        boxes_flow = laparams.boxes_flow
        # reorder the objects from top-left to bottom-right.
        self._objs.sort(
            key=lambda obj: (1 - boxes_flow) * obj.x0
            - (1 + boxes_flow) * (obj.y0 + obj.y1),
        )


class LTTextGroupTBRL(LTTextGroup):
    def analyze(self, laparams: LAParams) -> None:
        super().analyze(laparams)
        assert laparams.boxes_flow is not None
        boxes_flow = laparams.boxes_flow
        # reorder the objects from top-right to bottom-left.
        self._objs.sort(
            key=lambda obj: -(1 + boxes_flow) * (obj.x0 + obj.x1)
            - (1 - boxes_flow) * obj.y1,
        )


class LTLayoutContainer(LTContainer[LTComponent]):
    def __init__(
        self, bbox: Union[Rect, None] = None, mcstack: Tuple[MarkedContent, ...] = ()
    ) -> None:
        if bbox is None:
            # No initialization, for pickling purposes
            return
        super().__init__(bbox, mcstack)
        self.groups: Optional[List[LTTextGroup]] = None

    # group_objects: group text object to textlines.
    def group_objects(
        self,
        laparams: LAParams,
        objs: Iterable[LTComponent],
    ) -> Iterator[LTTextLine]:
        obj0: Any = None
        line: Any = None
        for obj1 in objs:
            if obj0 is not None:
                # halign: obj0 and obj1 is horizontally aligned.
                #
                #   +------+ - - -
                #   | obj0 | - - +------+   -
                #   |      |     | obj1 |   | (line_overlap)
                #   +------+ - - |      |   -
                #          - - - +------+
                #
                #          |<--->|
                #        (char_margin)
                halign = (
                    obj0.is_voverlap(obj1)
                    and min(obj0.height, obj1.height) * laparams.line_overlap
                    < obj0.voverlap(obj1)
                    and obj0.hdistance(obj1)
                    < max(obj0.width, obj1.width) * laparams.char_margin
                )

                # valign: obj0 and obj1 is vertically aligned.
                #
                #   +------+
                #   | obj0 |
                #   |      |
                #   +------+ - - -
                #     |    |     | (char_margin)
                #     +------+ - -
                #     | obj1 |
                #     |      |
                #     +------+
                #
                #     |<-->|
                #   (line_overlap)
                valign = (
                    laparams.detect_vertical
                    and obj0.is_hoverlap(obj1)
                    and min(obj0.width, obj1.width) * laparams.line_overlap
                    < obj0.hoverlap(obj1)
                    and obj0.vdistance(obj1)
                    < max(obj0.height, obj1.height) * laparams.char_margin
                )

                if (halign and isinstance(line, LTTextLineHorizontal)) or (
                    valign and isinstance(line, LTTextLineVertical)
                ):
                    line.add(obj1)
                elif line is not None:
                    yield line
                    line = None
                elif valign and not halign:
                    line = LTTextLineVertical(laparams.word_margin)
                    line.add(obj0)
                    line.add(obj1)
                elif halign and not valign:
                    line = LTTextLineHorizontal(laparams.word_margin)
                    line.add(obj0)
                    line.add(obj1)
                else:
                    line = LTTextLineHorizontal(laparams.word_margin)
                    line.add(obj0)
                    yield line
                    line = None
            obj0 = obj1
        if line is None:
            line = LTTextLineHorizontal(laparams.word_margin)
            assert obj0 is not None
            line.add(obj0)
        yield line

    def group_textlines(
        self,
        laparams: LAParams,
        lines: Iterable[LTTextLine],
    ) -> Iterator[LTTextBox]:
        """Group neighboring lines to textboxes"""
        plane: Plane[LTTextLine] = Plane(self.bbox)
        plane.extend(lines)
        boxes: Dict[int, LTTextBox] = {}
        for line in lines:
            neighbors = line.find_neighbors(plane, laparams.line_margin)
            members = [line]
            for obj1 in neighbors:
                members.append(obj1)
                if id(obj1) in boxes:
                    members.extend(boxes[id(obj1)])
                    del boxes[id(obj1)]
            if isinstance(line, LTTextLineHorizontal):
                box: LTTextBox = LTTextBoxHorizontal()
            else:
                box = LTTextBoxVertical()
            for obj in uniq(members):
                box.add(obj)
                boxes[id(obj)] = box
        done: Set[int] = set()
        for line in lines:
            if id(line) not in boxes:
                continue
            box = boxes[id(line)]
            if id(box) in done:
                continue
            done.add(id(box))
            if not box.is_empty():
                yield box

    def group_textboxes(
        self,
        laparams: LAParams,
        boxes: Sequence[LTTextBox],
    ) -> List[LTTextGroup]:
        """Group textboxes hierarchically.

        Get pair-wise distances, via dist func defined below, and then merge
        from the closest textbox pair. Once obj1 and obj2 are merged /
        grouped, the resulting group is considered as a new object, and its
        distances to other objects & groups are added to the process queue.

        For performance reason, pair-wise distances and object pair info are
        maintained in a heap of (idx, dist, id(obj1), id(obj2), obj1, obj2)
        tuples. It ensures quick access to the smallest element. Note that
        since comparison operators, e.g., __lt__, are disabled for
        LTComponent, id(obj) has to appear before obj in element tuples.

        :param laparams: LAParams object.
        :param boxes: All textbox objects to be grouped.
        :return: a list that has only one element, the final top level group.
        """
        ElementT = Union[LTTextBox, LTTextGroup]
        plane: Plane[ElementT] = Plane(self.bbox)

        def dist(obj1: LTComponent, obj2: LTComponent) -> float:
            """A distance function between two TextBoxes.

            Consider the bounding rectangle for obj1 and obj2.
            Return its area less the areas of obj1 and obj2,
            shown as 'www' below. This value may be negative.
                    +------+..........+ (x1, y1)
                    | obj1 |wwwwwwwwww:
                    +------+www+------+
                    :wwwwwwwwww| obj2 |
            (x0, y0) +..........+------+
            """
            x0 = min(obj1.x0, obj2.x0)
            y0 = min(obj1.y0, obj2.y0)
            x1 = max(obj1.x1, obj2.x1)
            y1 = max(obj1.y1, obj2.y1)
            return (
                (x1 - x0) * (y1 - y0)
                - obj1.width * obj1.height
                - obj2.width * obj2.height
            )

        def isany(obj1: ElementT, obj2: ElementT) -> bool:
            """Check if there's any other object between obj1 and obj2."""
            x0 = min(obj1.x0, obj2.x0)
            y0 = min(obj1.y0, obj2.y0)
            x1 = max(obj1.x1, obj2.x1)
            y1 = max(obj1.y1, obj2.y1)
            for obj in plane.find((x0, y0, x1, y1)):
                if obj not in (obj1, obj2):
                    break
            else:
                return False
            return True

        # If there's only one box, no grouping need be done, but we
        # should still always return a group!
        if len(boxes) == 1:
            return [LTTextGroup(boxes)]

        dists: List[Tuple[bool, float, int, int, ElementT, ElementT]] = []
        for i in range(len(boxes)):
            box1 = boxes[i]
            for j in range(i + 1, len(boxes)):
                box2 = boxes[j]
                dists.append((False, dist(box1, box2), id(box1), id(box2), box1, box2))
        heapq.heapify(dists)

        plane.extend(boxes)
        done: Set[int] = set()
        while len(dists) > 0:
            (skip_isany, d, id1, id2, obj1, obj2) = heapq.heappop(dists)
            # Skip objects that are already merged
            if (id1 in done) or (id2 in done):
                continue
            if not skip_isany and isany(obj1, obj2):
                heapq.heappush(dists, (True, d, id1, id2, obj1, obj2))
                continue
            if isinstance(obj1, (LTTextBoxVertical, LTTextGroupTBRL)) or isinstance(
                obj2,
                (LTTextBoxVertical, LTTextGroupTBRL),
            ):
                group: LTTextGroup = LTTextGroupTBRL([obj1, obj2])
            else:
                group = LTTextGroupLRTB([obj1, obj2])
            plane.remove(obj1)
            done.add(id1)
            plane.remove(obj2)
            done.add(id2)

            for other in plane:
                heapq.heappush(
                    dists,
                    (False, dist(group, other), id(group), id(other), group, other),
                )
            plane.add(group)
        # The plane should now only contain groups, otherwise it's a bug
        groups: List[LTTextGroup] = []
        for g in plane:
            assert isinstance(g, LTTextGroup)
            groups.append(g)
        return groups

    def analyze(self, laparams: LAParams) -> None:
        # textobjs is a list of LTChar objects, i.e.
        # it has all the individual characters in the page.
        (textobjs, otherobjs) = fsplit(lambda obj: isinstance(obj, LTChar), self)
        for obj in otherobjs:
            obj.analyze(laparams)
        if not textobjs:
            return
        textlines = list(self.group_objects(laparams, textobjs))
        (empties, textlines) = fsplit(lambda obj: obj.is_empty(), textlines)
        for obj in empties:
            obj.analyze(laparams)
        textboxes = list(self.group_textlines(laparams, textlines))
        if laparams.boxes_flow is None:
            for textbox in textboxes:
                textbox.analyze(laparams)

            def getkey(box: LTTextBox) -> Tuple[int, float, float]:
                if isinstance(box, LTTextBoxVertical):
                    return (0, -box.x1, -box.y0)
                else:
                    return (1, -box.y0, box.x0)

            textboxes.sort(key=getkey)
        else:
            self.groups = self.group_textboxes(laparams, textboxes)
            assigner = IndexAssigner()
            for group in self.groups:
                group.analyze(laparams)
                assigner.run(group)
            textboxes.sort(key=lambda box: box.index)
        self._objs = [*textboxes, *otherobjs, *empties]


class LTFigure(LTLayoutContainer):
    """Represents an area used by PDF Form objects.

    PDF Forms can be used to present figures or pictures by embedding yet
    another PDF document within a page. Note that LTFigure objects can appear
    recursively.
    """

    def __init__(self, obj: Union[ImageObject, XObjectObject, None] = None) -> None:
        if obj is None:
            # No initialization, for pickling purposes
            return
        if obj.xobjid is None:
            self.name = str(id(obj))
        else:
            self.name = obj.xobjid
        self.matrix = obj.ctm
        super().__init__(obj.bbox, obj.mcstack)

    def __repr__(self) -> str:
        return (
            f"<{self.__class__.__name__}({self.name}) "
            f"{bbox2str(self.bbox)} matrix={matrix2str(self.matrix)}>"
        )

    def analyze(self, laparams: LAParams) -> None:
        if not laparams.all_texts:
            return
        LTLayoutContainer.analyze(self, laparams)


class LTPage(LTLayoutContainer):
    """Represents an entire page.

    Like any other LTLayoutContainer, an LTPage can be iterated to obtain child
    objects like LTTextBox, LTFigure, LTImage, LTRect, LTCurve and LTLine.
    """

    def __init__(self, pageid: int, bbox: Rect, rotate: float = 0) -> None:
        super().__init__(bbox, ())
        self.pageid = pageid
        self.rotate = rotate

    def __repr__(self) -> str:
        return (
            f"<{self.__class__.__name__}({self.pageid!r}) "
            f"{bbox2str(self.bbox)} rotate={self.rotate!r}>"
        )


@singledispatch
def process_object(obj: ContentObject) -> Iterator[LTComponent]:
    """Handle obj according to its type"""
    yield from ()


def subpaths(path: PathObject) -> Iterator[PathObject]:
    """Iterate over "subpaths".

    Note: subpaths inherit the values of `fill` and `evenodd` from
    the parent path, but these values are no longer meaningful
    since the winding rules must be applied to the composite path
    as a whole (this is not a bug, just don't rely on them to know
    which regions are filled or not).

    """
    # FIXME: Is there an itertool or a more_itertool for this?
    segs: List[PLAYAPathSegment] = []
    for seg in path.raw_segments:
        if seg.operator == "m" and segs:
            yield PathObject(
                _pageref=path._pageref,
                _parentkey=path._parentkey,
                gstate=path.gstate,
                ctm=path.ctm,
                mcstack=path.mcstack,
                raw_segments=segs,
                stroke=path.stroke,
                fill=path.fill,
                evenodd=path.evenodd,
            )
            segs = []
        segs.append(seg)
    if segs:
        yield PathObject(
            _pageref=path._pageref,
            _parentkey=path._parentkey,
            gstate=path.gstate,
            ctm=path.ctm,
            mcstack=path.mcstack,
            raw_segments=segs,
            stroke=path.stroke,
            fill=path.fill,
            evenodd=path.evenodd,
        )


def make_path_segment(op: PathOperator, points: List[Point]) -> PathSegment:
    """Create a type-safe PathSegment, unlike pdfminer.six."""
    if len(points) == 0:
        if op != "h":
            raise ValueError("Incorrect arguments for {op!r}: {points!r}")
        return (str(op),)
    if len(points) == 1:
        if op not in "ml":
            raise ValueError("Incorrect arguments for {op!r}: {points!r}")
        return (str(op), points[0])
    if len(points) == 2:
        if op not in "vy":
            raise ValueError("Incorrect arguments for {op!r}: {points!r}")
        return (str(op), points[0], points[1])
    if len(points) == 3:
        if op != "c":
            raise ValueError("Incorrect arguments for {op!r}: {points!r}")
        return (str(op), points[0], points[1], points[2])
    raise ValueError(f"Path segment has unknown number of points: {op!r} {points!r}")


@process_object.register
def process_path(obj: PathObject) -> Iterator[LTComponent]:
    for path in subpaths(obj):
        ops = []
        pts: List[Point] = []
        for seg in path.raw_segments:
            ops.append(seg.operator)
            if seg.operator == "h":
                pts.append(pts[0])
            else:
                pts.append(apply_matrix_pt(obj.ctm, seg.points[-1]))
        # Drop a redundant "l" on a path closed with "h"
        shape = "".join(ops)
        if len(ops) > 3 and shape[-2:] == "lh" and pts[-2] == pts[0]:
            shape = shape[:-2] + "h"
            pts.pop()
        transformed_path: List[PathSegment] = []
        for op, seg in zip(ops, path.raw_segments):
            transformed_path.append(
                make_path_segment(
                    op,
                    [
                        # FIXME: Redundant computation for final point
                        apply_matrix_pt(obj.ctm, point)
                        for point in seg.points
                    ],
                )
            )
        if shape in {"mlh", "ml"}:
            # single line segment ("ml" is a frequent anomaly)
            line = LTLine(
                path,
                pts[0],
                pts[1],
                transformed_path,
            )
            yield line
        elif shape in {"mlllh", "mllll"}:
            (x0, y0), (x1, y1), (x2, y2), (x3, y3), _ = pts
            is_closed_loop = pts[0] == pts[4]
            has_square_coordinates = (
                x0 == x1 and y1 == y2 and x2 == x3 and y3 == y0
            ) or (y0 == y1 and x1 == x2 and y2 == y3 and x3 == x0)
            if is_closed_loop and has_square_coordinates:
                if x0 > x2:
                    (x2, x0) = (x0, x2)
                if y0 > y2:
                    (y2, y0) = (y0, y2)
                rect = LTRect(
                    path,
                    (*pts[0], *pts[2]),
                    transformed_path,
                )
                yield rect
            else:
                curve = LTCurve(
                    path,
                    pts,
                    transformed_path,
                )
                yield curve
        else:
            curve = LTCurve(
                path,
                pts,
                transformed_path,
            )
            yield curve


@process_object.register
def process_xobject(obj: XObjectObject) -> Iterator[LTComponent]:
    fig = LTFigure(obj)
    for child in obj:
        for grandchild in process_object(child):
            fig.add(grandchild)
    yield fig


@process_object.register
def process_image(obj: ImageObject) -> Iterator[LTComponent]:
    # pdfminer.six creates a redundant "figure" for images, even
    # inline ones, so we will do the same.
    fig = LTFigure(obj)
    img = LTImage(obj)
    fig.add(img)
    yield fig


@process_object.register
def process_text(obj: TextObject) -> Iterator[LTComponent]:
    # We only create LTChar, the rest is some dark magic
    for glyph in obj:
        yield LTChar(glyph)


def extract_page(page: Page, laparams: Union[LAParams, None] = None) -> LTPage:
    """Extract an LTPage from a Page, and possibly do some layout analysis.

    Args:
        page: a Page as returned by PLAYA (please create this with
              space="page" if you want pdfminer.six compatibility).
        laparams: if None, no layout analysis is done. Otherwise do
                  some kind of heuristic magic that all "Artificial
                  Intelligence" depends on but nobody actually
                  understands.

    Returns:
        An analysis of the page as `pdfminer.six` would give you.
    """
    # This is the mediabox in device space rather than default user
    # space, which is the source of some confusion
    (x0, y0, x1, y1) = page.mediabox
    # Note that a page can never be rotated by a non-multiple of 90
    # degrees (pi / 2 for nerds) so that's why we only care about two
    # of its corners
    (x0, y0) = apply_matrix_pt(page.ctm, (x0, y0))
    (x1, y1) = apply_matrix_pt(page.ctm, (x1, y1))
    # FIXME: The translation of the mediabox here is useless due to
    # the above transformation (but this should be verified against
    # pdfminer.six)
    mediabox = (0, 0, abs(x0 - x1), abs(y0 - y1))
    ltpage = LTPage(page.page_idx + 1, mediabox)

    # Emulating PDFLayoutAnalyzer is fairly simple and maps almost
    # directly onto PLAYA's lazy API.  XObjects and inline images
    # produce an LTFigure, characters produce an LTChar, everything
    # else produces an LTLine, LTRect, or LTCurve.
    for obj in page:
        # Put this in some functions to avoid isinstance abuse
        for item in process_object(obj):
            ltpage.add(item)

    if laparams is not None:
        ltpage.analyze(laparams)

    return ltpage


def extract(
    path: Path,
    laparams: Union[LAParams, None] = None,
    max_workers: Union[int, None] = 1,
    mp_context: Union[BaseContext, None] = None,
) -> Iterator[LTPage]:
    """Extract LTPages from a document."""
    if max_workers is None:
        max_workers = multiprocessing.cpu_count()
    with playa.open(
        path,
        space="page",
        max_workers=max_workers,
        mp_context=mp_context,
    ) as pdf:
        if max_workers == 1:
            for page in pdf.pages:
                yield extract_page(page, laparams)
        else:
            yield from pdf.pages.map(partial(extract_page, laparams=laparams))
