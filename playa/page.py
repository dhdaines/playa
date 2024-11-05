import logging
import re
import weakref
from copy import copy
from dataclasses import dataclass
from typing import (
    TYPE_CHECKING,
    Dict,
    Iterable,
    Iterator,
    List,
    NamedTuple,
    Optional,
    Sequence,
    Tuple,
    Union,
    cast,
)

from playa import settings
from playa.casting import safe_float
from playa.color import PREDEFINED_COLORSPACE, Color, ColorSpace
from playa.exceptions import (
    PDFInterpreterError,
    PDFSyntaxError,
    PDFUnicodeNotDefined,
)
from playa.font import Font
from playa.parser import Parser, PDFStackT, PSBaseParserToken
from playa.pdftypes import (
    KWD,
    LIT,
    LITERALS_ASCII85_DECODE,
    ContentStream,
    ObjRef,
    PSKeyword,
    PSLiteral,
    dict_value,
    int_value,
    keyword_name,
    list_value,
    literal_name,
    resolve1,
    stream_value,
)
from playa.utils import (
    MATRIX_IDENTITY,
    Matrix,
    PathSegment,
    Point,
    Rect,
    apply_matrix_pt,
    choplist,
    decode_text,
    get_bound,
    make_compat_bytes,
    mult_matrix,
    parse_rect,
    translate_matrix,
)

if TYPE_CHECKING:
    from playa.document import PDFDocument

log = logging.getLogger(__name__)

# some predefined literals and keywords.
LITERAL_PAGE = LIT("Page")
LITERAL_PAGES = LIT("Pages")
LITERAL_FORM = LIT("Form")
LITERAL_IMAGE = LIT("Image")
TextSeq = Iterable[Union[int, float, bytes]]


class Page:
    """An object that holds the information about a page.

    A Page object is merely a convenience class that has a set
    of keys and values, which describe the properties of a page
    and point to its contents.

    Attributes
    ----------
      pageid: the integer object ID associated with the page in the page tree
      attrs: a dictionary of page attributes.
      contents: a list of ContentStream objects that represents the page content.
      resources: a dictionary of resources used by the page.
      mediabox: the physical size of the page.
      cropbox: the crop rectangle of the page.
      rotate: the page rotation (in degree).
      label: the page's label (typically, the logical page number).
      page_number: the "physical" page number, indexed from 1.

    """

    def __init__(
        self,
        doc: "PDFDocument",
        pageid: int,
        attrs: Dict,
        label: Optional[str],
        page_idx: int = 0,
    ) -> None:
        """Initialize a page object.

        doc: a PDFDocument object.
        pageid: the integer PDF object ID associated with the page in the page tree.
        attrs: a dictionary of page attributes.
        label: page label string.
        page_idx: 0-based index of the page in the document.
        """
        self.doc = weakref.ref(doc)
        self.pageid = pageid
        self.attrs = attrs
        self.label = label
        self.page_idx = page_idx
        self.lastmod = resolve1(self.attrs.get("LastModified"))
        self.resources: Dict[object, object] = resolve1(
            self.attrs.get("Resources", dict()),
        )
        if "MediaBox" in self.attrs:
            self.mediabox = parse_rect(
                resolve1(val) for val in resolve1(self.attrs["MediaBox"])
            )
        else:
            log.warning(
                "MediaBox missing from /Page (and not inherited),"
                " defaulting to US Letter (612x792)"
            )
            self.mediabox = (0, 0, 612, 792)
        self.cropbox = self.mediabox
        if "CropBox" in self.attrs:
            try:
                self.cropbox = parse_rect(
                    resolve1(val) for val in resolve1(self.attrs["CropBox"])
                )
            except ValueError:
                log.warning("Invalid CropBox in /Page, defaulting to MediaBox")

        self.rotate = (int_value(self.attrs.get("Rotate", 0)) + 360) % 360
        self.annots = self.attrs.get("Annots")
        self.beads = self.attrs.get("B")
        if "Contents" in self.attrs:
            self.contents: List[object] = resolve1(self.attrs["Contents"])
            if not isinstance(self.contents, list):
                self.contents = [self.contents]
        else:
            self.contents = []

    @property
    def layout(self) -> Iterator["Item"]:
        return iter(PageInterpreter(self))

    def __repr__(self) -> str:
        return f"<Page: Resources={self.resources!r}, MediaBox={self.mediabox!r}>"


@dataclass
class TextState:
    matrix: Matrix = MATRIX_IDENTITY
    linematrix: Point = (0, 0)
    font: Optional[Font] = None
    fontsize: float = 0
    charspace: float = 0
    wordspace: float = 0
    scaling: float = 100
    leading: float = 0
    render: int = 0
    rise: float = 0

    def reset(self) -> None:
        self.matrix = MATRIX_IDENTITY
        self.linematrix = (0, 0)


@dataclass
class GraphicState:
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
    ncs: Optional[ColorSpace] = None
    scs: Optional[ColorSpace] = None
    stream: Optional[ContentStream] = None
    srcsize: Optional[Tuple[int, int]] = None
    imagemask: Optional[bool] = None
    bits: Optional[int] = None
    colorspace: Optional[List[ColorSpace]] = None
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
    ncs: Optional[ColorSpace] = None,
    scs: Optional[ColorSpace] = None,
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
    ncs: Optional[ColorSpace] = None,
    scs: Optional[ColorSpace] = None,
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
    ncs: Optional[ColorSpace] = None,
    scs: Optional[ColorSpace] = None,
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


KEYWORD_BI = KWD(b"BI")
KEYWORD_ID = KWD(b"ID")
KEYWORD_EI = KWD(b"EI")


class ContentParser(Parser[Union[PSKeyword, ContentStream]]):
    """Parse the concatenation of multiple content streams, as
    described in the spec (PDF 1.7, p.86):

    ...the effect shall be as if all of the streams in the array were
    concatenated, in order, to form a single stream.  Conforming
    writers can create image objects and other resources as they
    occur, even though they interrupt the content stream. The division
    between streams may occur only at the boundaries between lexical
    tokens (see 7.2, "Lexical Conventions") but shall be unrelated to
    the page’s logical content or organization.
    """

    def __init__(self, streams: Sequence[object]) -> None:
        self.streamiter = iter(streams)
        try:
            stream = stream_value(next(self.streamiter))
            log.debug("ContentParser starting stream %r", stream)
            super().__init__(stream.get_data())
        except StopIteration:
            log.debug("ContentParser has no content, returning nothing")
            super().__init__(b"")

    def nexttoken(self) -> Tuple[int, PSBaseParserToken]:
        while True:
            try:
                return super().nexttoken()
            except StopIteration:
                # Will also raise StopIteration if there are no more,
                # which is exactly what we want
                stream = stream_value(next(self.streamiter))
                log.debug("ContentParser starting new stream %r", stream)
                self.reinit(stream.get_data())

    def flush(self) -> None:
        self.add_results(*self.popall())

    def do_keyword(self, pos: int, token: PSKeyword) -> None:
        if token is KEYWORD_BI:
            # inline image within a content stream
            self.start_type(pos, "inline")
        elif token is KEYWORD_ID:
            try:
                (_, objs) = self.end_type("inline")
                if len(objs) % 2 != 0:
                    error_msg = f"Invalid dictionary construct: {objs!r}"
                    raise TypeError(error_msg)
                d = {literal_name(k): resolve1(v) for (k, v) in choplist(2, objs)}
                eos = b"EI"
                filter = d.get("F")
                if filter is not None:
                    if isinstance(filter, PSLiteral):
                        filter = [filter]
                    if filter[0] in LITERALS_ASCII85_DECODE:
                        eos = b"~>"
                # PDF 1.7 p. 215: Unless the image uses ASCIIHexDecode
                # or ASCII85Decode as one of its filters, the ID
                # operator shall be followed by a single white-space
                # character, and the next character shall be
                # interpreted as the first byte of image data.
                if eos == b"EI":
                    self.seek(pos + len(token.name) + 1)
                    (pos, data) = self.get_inline_data(target=eos)
                    # FIXME: it is totally unspecified what to do with
                    # a newline between the end of the data and "EI",
                    # since there is no explicit stream length.  (PDF
                    # 1.7 p. 756: There should be an end-of-line
                    # marker after the data and before endstream; this
                    # marker shall not be included in the stream
                    # length.)
                    data = data[: -len(eos)]
                else:
                    self.seek(pos + len(token.name))
                    (pos, data) = self.get_inline_data(target=eos)
                if pos == -1:
                    raise PDFSyntaxError("End of inline stream %r not found" % eos)
                obj = ContentStream(d, data)
                self.push((pos, obj))
                # This was included in the data but we need to "parse" it
                if eos == b"EI":
                    self.push((pos, KEYWORD_EI))
            except TypeError:
                if settings.STRICT:
                    raise
        else:
            self.push((pos, token))


class PageInterpreter:
    """Processor for the content of a PDF page

    Reference: PDF Reference, Appendix A, Operator Summary
    """

    ctm: Matrix
    cur_mcid: Optional[int] = None
    cur_tag: Optional[str] = None

    def __init__(
        self,
        page: Page,
        resources: Union[Dict, None] = None,
        contents: Union[List, None] = None,
    ) -> None:
        self.page = page
        self.contents = page.contents if contents is None else contents
        (x0, y0, x1, y1) = page.mediabox
        # FIXME: NO, this is bad, pdfplumber has a bug related to it
        # (specifically the translation, the rotation is kind of okay
        # it seems)
        if page.rotate == 90:
            ctm = (0, -1, 1, 0, -y0, x1)
        elif page.rotate == 180:
            ctm = (-1, 0, 0, -1, x1, y1)
        elif page.rotate == 270:
            ctm = (0, 1, -1, 0, y1, -x0)
        else:
            ctm = (1, 0, 0, 1, -x0, -y0)
        self.init_resources(page, page.resources if resources is None else resources)
        self.init_state(ctm)

    def init_resources(self, page: Page, resources: Dict) -> None:
        """Prepare the fonts and XObjects listed in the Resource attribute."""
        self.resources = resources
        self.fontmap: Dict[object, Font] = {}
        self.xobjmap = {}
        self.csmap: Dict[str, ColorSpace] = copy(PREDEFINED_COLORSPACE)
        if not self.resources:
            return
        doc = page.doc()
        if doc is None:
            raise RuntimeError("Document no longer exists!")

        def get_colorspace(spec: object) -> Optional[ColorSpace]:
            if isinstance(spec, list):
                name = literal_name(spec[0])
            else:
                name = literal_name(spec)
            if name == "ICCBased" and isinstance(spec, list) and len(spec) >= 2:
                return ColorSpace(name, stream_value(spec[1])["N"])
            elif name == "DeviceN" and isinstance(spec, list) and len(spec) >= 2:
                return ColorSpace(name, len(list_value(spec[1])))
            else:
                return PREDEFINED_COLORSPACE.get(name)

        for k, v in dict_value(self.resources).items():
            log.debug("Resource: %r: %r", k, v)
            if k == "Font":
                for fontid, spec in dict_value(v).items():
                    objid = None
                    if isinstance(spec, ObjRef):
                        objid = spec.objid
                    spec = dict_value(spec)
                    self.fontmap[fontid] = doc.get_font(objid, spec)
            elif k == "ColorSpace":
                for csid, spec in dict_value(v).items():
                    colorspace = get_colorspace(resolve1(spec))
                    if colorspace is not None:
                        self.csmap[csid] = colorspace
            elif k == "ProcSet":
                pass  # called get_procset which did exactly
                # nothing. perhaps we want to do something?
            elif k == "XObject":
                for xobjid, xobjstrm in dict_value(v).items():
                    self.xobjmap[xobjid] = xobjstrm

    def init_state(self, ctm: Matrix) -> None:
        """Initialize the text and graphic states for rendering a page."""
        # gstack: stack for graphical states.
        self.gstack: List[Tuple[Matrix, TextState, GraphicState]] = []
        self.ctm = ctm
        self.textstate = TextState()
        self.graphicstate = GraphicState()
        self.curpath: List[PathSegment] = []
        # argstack: stack for command arguments.
        self.argstack: List[PDFStackT] = []
        # set some global states.
        self.scs: Optional[ColorSpace] = None
        self.ncs: Optional[ColorSpace] = None
        if self.csmap:
            self.scs = self.ncs = next(iter(self.csmap.values()))

    def __iter__(self) -> Iterator[Item]:
        log.debug(
            "PageInterpreter: resources=%r, streams=%r, ctm=%r",
            self.resources,
            self.contents,
            self.ctm,
        )
        parser = ContentParser(self.contents)
        for _, obj in parser:
            if isinstance(obj, PSKeyword):
                name = keyword_name(obj)
                method = "do_%s" % name.replace("*", "_a").replace('"', "_w").replace(
                    "'",
                    "_q",
                )
                if hasattr(self, method):
                    func = getattr(self, method)
                    nargs = func.__code__.co_argcount - 1
                    if nargs:
                        args = self.pop(nargs)
                        log.debug("exec: %s %r", name, args)
                        if len(args) == nargs:
                            gen = func(*args)
                        else:
                            error_msg = (
                                "Insufficient arguments (%d) for operator: %r"
                                % (len(args), name)
                            )
                            raise PDFInterpreterError(error_msg)
                    else:
                        log.debug("exec: %s", name)
                        gen = func()
                    if gen is not None:
                        yield from gen
                elif settings.STRICT:
                    error_msg = "Unknown operator: %r" % name
                    raise PDFInterpreterError(error_msg)
            else:
                self.push(obj)

    def push(self, obj: PDFStackT) -> None:
        self.argstack.append(obj)

    def pop(self, n: int) -> List[PDFStackT]:
        if n == 0:
            return []
        x = self.argstack[-n:]
        self.argstack = self.argstack[:-n]
        return x

    def get_current_state(self) -> Tuple[Matrix, TextState, GraphicState]:
        return (self.ctm, copy(self.textstate), copy(self.graphicstate))

    def set_current_state(
        self,
        state: Tuple[Matrix, TextState, GraphicState],
    ) -> None:
        (self.ctm, self.textstate, self.graphicstate) = state

    def do_q(self) -> None:
        """Save graphics state"""
        self.gstack.append(self.get_current_state())

    def do_Q(self) -> None:
        """Restore graphics state"""
        if self.gstack:
            self.set_current_state(self.gstack.pop())

    def do_cm(
        self,
        a1: PDFStackT,
        b1: PDFStackT,
        c1: PDFStackT,
        d1: PDFStackT,
        e1: PDFStackT,
        f1: PDFStackT,
    ) -> None:
        """Concatenate matrix to current transformation matrix"""
        self.ctm = mult_matrix(cast(Matrix, (a1, b1, c1, d1, e1, f1)), self.ctm)

    def do_w(self, linewidth: PDFStackT) -> None:
        """Set line width"""
        self.graphicstate.linewidth = cast(float, linewidth)

    def do_J(self, linecap: PDFStackT) -> None:
        """Set line cap style"""
        self.graphicstate.linecap = linecap

    def do_j(self, linejoin: PDFStackT) -> None:
        """Set line join style"""
        self.graphicstate.linejoin = linejoin

    def do_M(self, miterlimit: PDFStackT) -> None:
        """Set miter limit"""
        self.graphicstate.miterlimit = miterlimit

    def do_d(self, dash: PDFStackT, phase: PDFStackT) -> None:
        """Set line dash pattern"""
        self.graphicstate.dash = (dash, phase)

    def do_ri(self, intent: PDFStackT) -> None:
        """Set color rendering intent"""
        self.graphicstate.intent = intent

    def do_i(self, flatness: PDFStackT) -> None:
        """Set flatness tolerance"""
        self.graphicstate.flatness = flatness

    def do_gs(self, name: PDFStackT) -> None:
        """Set parameters from graphics state parameter dictionary"""
        # TODO

    def do_m(self, x: PDFStackT, y: PDFStackT) -> None:
        """Begin new subpath"""
        self.curpath.append(("m", cast(float, x), cast(float, y)))

    def do_l(self, x: PDFStackT, y: PDFStackT) -> None:
        """Append straight line segment to path"""
        self.curpath.append(("l", cast(float, x), cast(float, y)))

    def do_c(
        self,
        x1: PDFStackT,
        y1: PDFStackT,
        x2: PDFStackT,
        y2: PDFStackT,
        x3: PDFStackT,
        y3: PDFStackT,
    ) -> None:
        """Append curved segment to path (three control points)"""
        self.curpath.append(
            (
                "c",
                cast(float, x1),
                cast(float, y1),
                cast(float, x2),
                cast(float, y2),
                cast(float, x3),
                cast(float, y3),
            ),
        )

    def do_v(self, x2: PDFStackT, y2: PDFStackT, x3: PDFStackT, y3: PDFStackT) -> None:
        """Append curved segment to path (initial point replicated)"""
        self.curpath.append(
            ("v", cast(float, x2), cast(float, y2), cast(float, x3), cast(float, y3)),
        )

    def do_y(self, x1: PDFStackT, y1: PDFStackT, x3: PDFStackT, y3: PDFStackT) -> None:
        """Append curved segment to path (final point replicated)"""
        self.curpath.append(
            ("y", cast(float, x1), cast(float, y1), cast(float, x3), cast(float, y3)),
        )

    def do_h(self) -> None:
        """Close subpath"""
        self.curpath.append(("h",))

    def do_re(self, x: PDFStackT, y: PDFStackT, w: PDFStackT, h: PDFStackT) -> None:
        """Append rectangle to path"""
        x = cast(float, x)
        y = cast(float, y)
        w = cast(float, w)
        h = cast(float, h)
        self.curpath.append(("m", x, y))
        self.curpath.append(("l", x + w, y))
        self.curpath.append(("l", x + w, y + h))
        self.curpath.append(("l", x, y + h))
        self.curpath.append(("h",))

    def do_S(self) -> Iterator[Item]:
        """Stroke path"""
        yield from self.paint_path(
            stroke=True, fill=False, evenodd=False, path=self.curpath
        )
        self.curpath = []

    def do_s(self) -> Iterator[Item]:
        """Close and stroke path"""
        self.do_h()
        yield from self.do_S()

    def do_f(self) -> Iterator[Item]:
        """Fill path using nonzero winding number rule"""
        yield from self.paint_path(
            stroke=False, fill=True, evenodd=False, path=self.curpath
        )
        self.curpath = []

    def do_F(self) -> None:
        """Fill path using nonzero winding number rule (obsolete)"""

    def do_f_a(self) -> Iterator[Item]:
        """Fill path using even-odd rule"""
        yield from self.paint_path(
            stroke=False, fill=True, evenodd=True, path=self.curpath
        )
        self.curpath = []

    def do_B(self) -> Iterator[Item]:
        """Fill and stroke path using nonzero winding number rule"""
        yield from self.paint_path(
            stroke=True, fill=True, evenodd=False, path=self.curpath
        )
        self.curpath = []

    def do_B_a(self) -> Iterator[Item]:
        """Fill and stroke path using even-odd rule"""
        yield from self.paint_path(
            stroke=True, fill=True, evenodd=True, path=self.curpath
        )
        self.curpath = []

    def do_b(self) -> Iterator[Item]:
        """Close, fill, and stroke path using nonzero winding number rule"""
        self.do_h()
        yield from self.do_B()

    def do_b_a(self) -> Iterator[Item]:
        """Close, fill, and stroke path using even-odd rule"""
        self.do_h()
        yield from self.do_B_a()

    def do_n(self) -> None:
        """End path without filling or stroking"""
        self.curpath = []

    def do_W(self) -> None:
        """Set clipping path using nonzero winding number rule"""

    def do_W_a(self) -> None:
        """Set clipping path using even-odd rule"""

    def do_CS(self, name: PDFStackT) -> None:
        """Set color space for stroking operations

        Introduced in PDF 1.1
        """
        try:
            self.scs = self.csmap[literal_name(name)]
        except KeyError:
            if settings.STRICT:
                raise PDFInterpreterError("Undefined ColorSpace: %r" % name)

    def do_cs(self, name: PDFStackT) -> None:
        """Set color space for nonstroking operations"""
        try:
            self.ncs = self.csmap[literal_name(name)]
        except KeyError:
            if settings.STRICT:
                raise PDFInterpreterError("Undefined ColorSpace: %r" % name)

    def do_G(self, gray: PDFStackT) -> None:
        """Set gray level for stroking operations"""
        self.scs = self.csmap["DeviceGray"]
        self.graphicstate.scolor = self.scs.make_color(gray)

    def do_g(self, gray: PDFStackT) -> None:
        """Set gray level for nonstroking operations"""
        self.ncs = self.csmap["DeviceGray"]
        self.graphicstate.ncolor = self.ncs.make_color(gray)

    def do_RG(self, r: PDFStackT, g: PDFStackT, b: PDFStackT) -> None:
        """Set RGB color for stroking operations"""
        self.scs = self.csmap["DeviceRGB"]
        self.graphicstate.scolor = self.scs.make_color(r, g, b)

    def do_rg(self, r: PDFStackT, g: PDFStackT, b: PDFStackT) -> None:
        """Set RGB color for nonstroking operations"""
        self.ncs = self.csmap["DeviceRGB"]
        self.graphicstate.ncolor = self.ncs.make_color(r, g, b)

    def do_K(self, c: PDFStackT, m: PDFStackT, y: PDFStackT, k: PDFStackT) -> None:
        """Set CMYK color for stroking operations"""
        self.scs = self.csmap["DeviceCMYK"]
        self.graphicstate.scolor = self.scs.make_color(c, m, y, k)

    def do_k(self, c: PDFStackT, m: PDFStackT, y: PDFStackT, k: PDFStackT) -> None:
        """Set CMYK color for nonstroking operations"""
        self.ncs = self.csmap["DeviceCMYK"]
        self.graphicstate.ncolor = self.ncs.make_color(c, m, y, k)

    def do_SCN(self) -> None:
        """Set color for stroking operations."""
        if self.scs is None:
            if settings.STRICT:
                raise PDFInterpreterError("No colorspace specified!")
            self.scs = self.csmap["DeviceGray"]
        self.graphicstate.scolor = self.scs.make_color(*self.pop(self.scs.ncomponents))

    def do_scn(self) -> None:
        """Set color for nonstroking operations"""
        if self.ncs is None:
            if settings.STRICT:
                raise PDFInterpreterError("No colorspace specified!")
            self.ncs = self.csmap["DeviceGray"]
        self.graphicstate.ncolor = self.ncs.make_color(*self.pop(self.ncs.ncomponents))

    def do_SC(self) -> None:
        """Set color for stroking operations"""
        self.do_SCN()

    def do_sc(self) -> None:
        """Set color for nonstroking operations"""
        self.do_scn()

    def do_sh(self, name: object) -> None:
        """Paint area defined by shading pattern"""

    def do_BT(self) -> None:
        """Begin text object

        Initializing the text matrix, Tm, and the text line matrix, Tlm, to
        the identity matrix. Text objects cannot be nested; a second BT cannot
        appear before an ET.
        """
        self.textstate.reset()

    def do_ET(self) -> None:
        """End a text object"""

    def do_BX(self) -> None:
        """Begin compatibility section"""

    def do_EX(self) -> None:
        """End compatibility section"""

    def do_MP(self, tag: PDFStackT) -> None:
        """Define marked-content point"""
        self.do_tag(cast(PSLiteral, tag))

    def do_DP(self, tag: PDFStackT, props: PDFStackT) -> None:
        """Define marked-content point with property list"""
        self.do_tag(cast(PSLiteral, tag), props)

    def do_BMC(self, tag: PDFStackT) -> None:
        """Begin marked-content sequence"""
        self.begin_tag(cast(PSLiteral, tag))

    def do_BDC(self, tag: PDFStackT, props: PDFStackT) -> None:
        """Begin marked-content sequence with property list"""
        self.begin_tag(cast(PSLiteral, tag), props)

    def do_EMC(self) -> None:
        """End marked-content sequence"""
        self.end_tag()

    def do_Tc(self, space: PDFStackT) -> None:
        """Set character spacing.

        Character spacing is used by the Tj, TJ, and ' operators.

        :param space: a number expressed in unscaled text space units.
        """
        self.textstate.charspace = cast(float, space)

    def do_Tw(self, space: PDFStackT) -> None:
        """Set the word spacing.

        Word spacing is used by the Tj, TJ, and ' operators.

        :param space: a number expressed in unscaled text space units
        """
        self.textstate.wordspace = cast(float, space)

    def do_Tz(self, scale: PDFStackT) -> None:
        """Set the horizontal scaling.

        :param scale: is a number specifying the percentage of the normal width
        """
        self.textstate.scaling = cast(float, scale)

    def do_TL(self, leading: PDFStackT) -> None:
        """Set the text leading.

        Text leading is used only by the T*, ', and " operators.

        :param leading: a number expressed in unscaled text space units
        """
        self.textstate.leading = -cast(float, leading)

    def do_Tf(self, fontid: PDFStackT, fontsize: PDFStackT) -> None:
        """Set the text font

        :param fontid: the name of a font resource in the Font subdictionary
            of the current resource dictionary
        :param fontsize: size is a number representing a scale factor.
        """
        try:
            self.textstate.font = self.fontmap[literal_name(fontid)]
        except KeyError:
            if settings.STRICT:
                raise PDFInterpreterError("Undefined Font id: %r" % fontid)
            doc = self.page.doc()
            if doc is None:
                raise RuntimeError("Document no longer exists!")
            self.textstate.font = doc.get_font(None, {})
        self.textstate.fontsize = cast(float, fontsize)

    def do_Tr(self, render: PDFStackT) -> None:
        """Set the text rendering mode"""
        self.textstate.render = cast(int, render)

    def do_Ts(self, rise: PDFStackT) -> None:
        """Set the text rise

        :param rise: a number expressed in unscaled text space units
        """
        self.textstate.rise = cast(float, rise)

    def do_Td(self, tx: PDFStackT, ty: PDFStackT) -> None:
        """Move to the start of the next line

        Offset from the start of the current line by (tx , ty).
        """
        tx_ = safe_float(tx)
        ty_ = safe_float(ty)
        if tx_ is not None and ty_ is not None:
            (a, b, c, d, e, f) = self.textstate.matrix
            e_new = tx_ * a + ty_ * c + e
            f_new = tx_ * b + ty_ * d + f
            self.textstate.matrix = (a, b, c, d, e_new, f_new)

        elif settings.STRICT:
            raise ValueError(f"Invalid offset ({tx!r}, {ty!r}) for Td")

        self.textstate.linematrix = (0, 0)

    def do_TD(self, tx: PDFStackT, ty: PDFStackT) -> None:
        """Move to the start of the next line.

        offset from the start of the current line by (tx , ty). As a side effect, this
        operator sets the leading parameter in the text state.
        """
        tx_ = safe_float(tx)
        ty_ = safe_float(ty)

        if tx_ is not None and ty_ is not None:
            (a, b, c, d, e, f) = self.textstate.matrix
            e_new = tx_ * a + ty_ * c + e
            f_new = tx_ * b + ty_ * d + f
            self.textstate.matrix = (a, b, c, d, e_new, f_new)

        elif settings.STRICT:
            raise ValueError("Invalid offset ({tx}, {ty}) for TD")

        if ty_ is not None:
            self.textstate.leading = ty_

        self.textstate.linematrix = (0, 0)

    def do_Tm(
        self,
        a: PDFStackT,
        b: PDFStackT,
        c: PDFStackT,
        d: PDFStackT,
        e: PDFStackT,
        f: PDFStackT,
    ) -> None:
        """Set text matrix and text line matrix"""
        self.textstate.matrix = cast(Matrix, (a, b, c, d, e, f))
        self.textstate.linematrix = (0, 0)

    def do_T_a(self) -> None:
        """Move to start of next text line"""
        (a, b, c, d, e, f) = self.textstate.matrix
        self.textstate.matrix = (
            a,
            b,
            c,
            d,
            self.textstate.leading * c + e,
            self.textstate.leading * d + f,
        )
        self.textstate.linematrix = (0, 0)

    def do_TJ(self, seq: PDFStackT) -> Iterator[Item]:
        """Show text, allowing individual glyph positioning"""
        if self.textstate.font is None:
            if settings.STRICT:
                raise PDFInterpreterError("No font specified!")
            return
        yield from self.render_string(
            cast(TextSeq, seq),
        )

    def do_Tj(self, s: PDFStackT) -> Iterator[Item]:
        """Show text"""
        yield from self.do_TJ([s])

    def do__q(self, s: PDFStackT) -> Iterator[Item]:
        """Move to next line and show text

        The ' (single quote) operator.
        """
        self.do_T_a()
        yield from self.do_TJ([s])

    def do__w(self, aw: PDFStackT, ac: PDFStackT, s: PDFStackT) -> Iterator[Item]:
        """Set word and character spacing, move to next line, and show text

        The " (double quote) operator.
        """
        self.do_Tw(aw)
        self.do_Tc(ac)
        yield from self.do_TJ([s])

    def do_BI(self) -> None:
        """Begin inline image object"""

    def do_ID(self) -> None:
        """Begin inline image data"""

    def do_EI(self, obj: PDFStackT) -> Iterator[Item]:
        """End inline image object"""
        if isinstance(obj, ContentStream) and "W" in obj and "H" in obj:
            iobjid = str(id(obj))
            fig = LTFigure(name=iobjid, bbox=(0, 0, 1, 1), matrix=self.ctm)
            assert fig.objs is not None
            fig.objs.append(self.render_image(iobjid, obj, fig))
            yield fig

    def do_Do(self, xobjid_arg: PDFStackT) -> Iterator[Item]:
        """Invoke named XObject"""
        xobjid = literal_name(xobjid_arg)
        try:
            xobj = stream_value(self.xobjmap[xobjid])
        except KeyError:
            if settings.STRICT:
                raise PDFInterpreterError("Undefined xobject id: %r" % xobjid)
            return
        log.debug("Processing xobj: %r", xobj)
        subtype = xobj.get("Subtype")
        if subtype is LITERAL_FORM and "BBox" in xobj:
            bbox = cast(Rect, list_value(xobj["BBox"]))
            matrix = cast(Matrix, list_value(xobj.get("Matrix", MATRIX_IDENTITY)))
            # According to PDF reference 1.7 section 4.9.1, XObjects in
            # earlier PDFs (prior to v1.2) use the page's Resources entry
            # instead of having their own Resources entry.
            xobjres = xobj.get("Resources")
            if xobjres:
                interpreter = PageInterpreter(
                    self.page, resources=dict_value(xobjres), contents=[xobj]
                )
            else:
                interpreter = PageInterpreter(self.page, contents=[xobj])
            interpreter.ctm = mult_matrix(matrix, self.ctm)
            fig = LTFigure(name=xobjid, bbox=bbox, matrix=interpreter.ctm)
            assert fig.objs is not None
            fig.objs.extend(interpreter)
            yield fig
        elif subtype is LITERAL_IMAGE and "Width" in xobj and "Height" in xobj:
            fig = LTFigure(name=xobjid, bbox=(0, 0, 1, 1), matrix=self.ctm)
            assert fig.objs is not None
            fig.objs.append(self.render_image(xobjid, xobj, fig))
            yield fig
        else:
            # unsupported xobject type.
            pass

    def begin_tag(self, tag: PSLiteral, props: Optional[PDFStackT] = None) -> None:
        """Handle beginning of tag, setting current MCID if any."""
        self.cur_tag = decode_text(tag.name)
        # FIXME: Many other useful things like ActualText
        if isinstance(props, dict) and "MCID" in props:
            self.cur_mcid = props["MCID"]
        else:
            self.cur_mcid = None

    def do_tag(self, tag: PSLiteral, props: Optional["PDFStackT"] = None) -> None:
        pass

    def end_tag(self) -> None:
        """Handle beginning of tag, clearing current MCID."""
        self.cur_tag = None
        self.cur_mcid = None

    def render_image(self, name: str, stream: ContentStream, figure: Item) -> Item:
        return LTImage(
            name=name,
            stream=stream,
            bbox=figure.bbox,
        )

    def paint_path(
        self,
        *,
        stroke: bool,
        fill: bool,
        evenodd: bool,
        path: Sequence[PathSegment],
    ) -> Iterator[Item]:
        """Paint paths described in section 4.4 of the PDF reference manual"""
        shape = "".join(x[0] for x in path)
        gstate = self.graphicstate
        ncs = self.ncs
        scs = self.scs

        if shape[:1] != "m":
            # Per PDF Reference Section 4.4.1, "path construction operators may
            # be invoked in any sequence, but the first one invoked must be m
            # or re to begin a new subpath." Since pdfminer.six already
            # converts all `re` (rectangle) operators to their equivelent
            # `mlllh` representation, paths ingested by `.paint_path(...)` that
            # do not begin with the `m` operator are invalid.
            pass

        elif shape.count("m") > 1:
            # recurse if there are multiple m's in this shape
            for m in re.finditer(r"m[^m]+", shape):
                subpath = path[m.start(0) : m.end(0)]
                yield from self.paint_path(
                    stroke=stroke, fill=fill, evenodd=evenodd, path=subpath
                )

        else:
            # Although the 'h' command does not not literally provide a
            # point-position, its position is (by definition) equal to the
            # subpath's starting point.
            #
            # And, per Section 4.4's Table 4.9, all other path commands place
            # their point-position in their final two arguments. (Any preceding
            # arguments represent control points on Bézier curves.)
            raw_pts = [
                cast(Point, p[-2:] if p[0] != "h" else path[0][-2:]) for p in path
            ]
            pts = [apply_matrix_pt(self.ctm, pt) for pt in raw_pts]

            operators = [str(operation[0]) for operation in path]
            transformed_points = [
                [
                    apply_matrix_pt(self.ctm, (float(operand1), float(operand2)))
                    for operand1, operand2 in zip(operation[1::2], operation[2::2])
                ]
                for operation in path
            ]
            transformed_path = [
                cast(PathSegment, (o, *p))
                for o, p in zip(operators, transformed_points)
            ]

            if shape in {"mlh", "ml"}:
                # single line segment
                #
                # Note: 'ml', in conditional above, is a frequent anomaly
                # that we want to support.
                line = LTLine(
                    linewidth=gstate.linewidth,
                    p0=pts[0],
                    p1=pts[1],
                    stroke=stroke,
                    fill=fill,
                    evenodd=evenodd,
                    stroking_color=gstate.scolor,
                    non_stroking_color=gstate.ncolor,
                    original_path=transformed_path,
                    dashing_style=gstate.dash,
                    ncs=ncs,
                    scs=scs,
                )
                yield line

            elif shape in {"mlllh", "mllll"}:
                (x0, y0), (x1, y1), (x2, y2), (x3, y3), _ = pts

                is_closed_loop = pts[0] == pts[4]
                has_square_coordinates = (
                    x0 == x1 and y1 == y2 and x2 == x3 and y3 == y0
                ) or (y0 == y1 and x1 == x2 and y2 == y3 and x3 == x0)
                if is_closed_loop and has_square_coordinates:
                    rect = LTRect(
                        linewidth=gstate.linewidth,
                        bbox=(*pts[0], *pts[2]),
                        stroke=stroke,
                        fill=fill,
                        evenodd=evenodd,
                        stroking_color=gstate.scolor,
                        non_stroking_color=gstate.ncolor,
                        original_path=transformed_path,
                        dashing_style=gstate.dash,
                        ncs=ncs,
                        scs=scs,
                    )
                    yield rect
                else:
                    curve = LTCurve(
                        linewidth=gstate.linewidth,
                        pts=pts,
                        stroke=stroke,
                        fill=fill,
                        evenodd=evenodd,
                        stroking_color=gstate.scolor,
                        non_stroking_color=gstate.ncolor,
                        original_path=transformed_path,
                        dashing_style=gstate.dash,
                        ncs=ncs,
                        scs=scs,
                    )
                    yield curve
            else:
                curve = LTCurve(
                    linewidth=gstate.linewidth,
                    pts=pts,
                    stroke=stroke,
                    fill=fill,
                    evenodd=evenodd,
                    stroking_color=gstate.scolor,
                    non_stroking_color=gstate.ncolor,
                    original_path=transformed_path,
                    dashing_style=gstate.dash,
                    ncs=ncs,
                    scs=scs,
                )
                yield curve

    def render_char(
        self,
        *,
        vertical: bool,
        matrix: Matrix,
        font: Font,
        fontsize: float,
        scaling: float,
        rise: float,
        cid: int,
    ) -> Tuple[Item, float]:
        try:
            text = font.to_unichr(cid)
            assert isinstance(text, str), f"Text {text!r} is not a str"
        except PDFUnicodeNotDefined:
            text = self.handle_undefined_char(font, cid)
        textwidth = font.char_width(cid)
        textdisp = font.char_disp(cid)
        adv = textwidth * fontsize * scaling
        if vertical:
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
        if vertical:
            size = x1 - x0
        else:
            size = y1 - y0
        item = Item(
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
            ncs=self.ncs,
            scs=self.scs,
            stroking_color=self.graphicstate.scolor,
            non_stroking_color=self.graphicstate.ncolor,
            mcid=self.cur_mcid,
            tag=self.cur_tag,
        )
        return item, adv

    def render_string(
        self,
        seq: TextSeq,
    ) -> Iterator[Item]:
        assert self.textstate.font is not None
        vert = self.textstate.font.vertical
        assert self.ctm is not None
        matrix = mult_matrix(self.textstate.matrix, self.ctm)
        fontsize = self.textstate.fontsize
        scaling = self.textstate.scaling * 0.01
        charspace = self.textstate.charspace * scaling
        wordspace = self.textstate.wordspace * scaling
        rise = self.textstate.rise
        if self.textstate.font.multibyte:
            wordspace = 0
        dxscale = 0.001 * fontsize * scaling
        (x, y) = self.textstate.linematrix
        pos = y if vert else x
        needcharspace = False
        for obj in seq:
            if isinstance(obj, (int, float)):
                pos -= obj * dxscale
                needcharspace = True
            else:
                if isinstance(obj, str):
                    obj = make_compat_bytes(obj)
                if not isinstance(obj, bytes):
                    continue
                for cid in self.textstate.font.decode(obj):
                    if needcharspace:
                        pos += charspace
                    lm = (x, pos) if vert else (pos, y)
                    item, adv = self.render_char(
                        vertical=vert,
                        matrix=translate_matrix(matrix, lm),
                        font=self.textstate.font,
                        fontsize=fontsize,
                        scaling=scaling,
                        rise=rise,
                        cid=cid,
                    )
                    pos += adv
                    yield item
                    if cid == 32 and wordspace:
                        pos += wordspace
                    needcharspace = True
        self.textstate.linematrix = (x, pos) if vert else (pos, y)

    def handle_undefined_char(self, font: Font, cid: int) -> str:
        log.debug("undefined: %r, %r", font, cid)
        return "(cid:%d)" % cid
