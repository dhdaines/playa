import logging
import re
import weakref
from copy import copy
from dataclasses import dataclass
from typing import (
    TYPE_CHECKING,
    Callable,
    Dict,
    Iterable,
    Iterator,
    List,
    NamedTuple,
    Optional,
    Sequence,
    Tuple,
    TypedDict,
    Union,
    cast,
)

from playa import settings
from playa.casting import safe_float
from playa.color import PREDEFINED_COLORSPACE, Color, ColorGray, ColorSpace
from playa.exceptions import (
    PDFInterpreterError,
    PDFUnicodeNotDefined,
)
from playa.font import Font
from playa.parser import KWD, InlineImage, ObjectParser, PDFObject, Token
from playa.pdftypes import (
    LIT,
    ContentStream,
    ObjRef,
    PSKeyword,
    PSLiteral,
    dict_value,
    int_value,
    list_value,
    literal_name,
    num_value,
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
            assert self.contents is not None
            if not isinstance(self.contents, list):
                self.contents = [self.contents]
        else:
            self.contents = []

    @property
    def layout(self) -> Iterator["LayoutObject"]:
        return iter(PageInterpreter(self))

    def __iter__(self) -> Iterator[PDFObject]:
        for pos, obj in ContentParser(self.contents):
            yield obj

    @property
    def tokens(self) -> Iterator[Token]:
        parser = ContentParser(self.contents)
        while True:
            try:
                pos, tok = parser.nexttoken()
            except StopIteration:
                return
            yield tok

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


class DashingStyle(NamedTuple):
    dash: List[float]
    phase: float


@dataclass
class GraphicState:
    linewidth: float = 0
    linecap: Optional[object] = None
    linejoin: Optional[object] = None
    miterlimit: Optional[object] = None
    dash: DashingStyle = DashingStyle([], 0)
    intent: Optional[object] = None
    flatness: Optional[object] = None
    # stroking color
    scolor: Color = ColorGray(0)
    # stroking color space
    scs: ColorSpace = PREDEFINED_COLORSPACE["DeviceGray"]
    # non stroking color
    ncolor: Color = ColorGray(0)
    # non stroking color space
    ncs: ColorSpace = PREDEFINED_COLORSPACE["DeviceGray"]


class LayoutObject(TypedDict, total=False):
    """Dictionary-based layout objects.

    These closely match the dictionaries returned by pdfplumber, except
    that coordinates are expressed in PDF device space with (0, 0) at
    lower left.

    This API has some limitations, so it is preferable to use
    ContentObject instead.
    """

    object_type: str
    adv: float
    height: float
    linewidth: float
    pts: List[Point]
    size: float
    srcsize: Tuple[int, int]
    width: float
    x0: float
    x1: float
    y0: float
    y1: float
    bits: int
    matrix: Matrix
    upright: bool
    fontname: str
    colorspace: List[ColorSpace]  # for images
    ncs: ColorSpace  # for text/paths
    scs: ColorSpace  # for text/paths
    evenodd: bool
    stroke: bool
    fill: bool
    stroking_color: Color
    non_stroking_color: Color
    stream: ContentStream
    text: str
    imagemask: bool
    name: str
    mcid: Union[int, None]
    tag: Union[str, None]
    path: List[Tuple]
    dash: DashingStyle


class MarkedContentTag(NamedTuple):
    name: str
    attrs: Dict[str, PDFObject]


class MarkedContentSection(NamedTuple):
    mcid: int
    tag: MarkedContentTag


class ContentObject:
    object_type: str
    gstate: GraphicState
    mcs: MarkedContentSection

    @property
    def bbox(self) -> Rect:
        return (0, 0, 0, 0)


class TextObject(ContentObject):
    tstate: TextState

    def __iter__(self):
        yield from ()

    @property
    def strings(self) -> Iterator[Iterator[ContentObject]]:
        yield from ()

    @property
    def chars(self) -> Iterator[ContentObject]:
        yield from ()


class ContentParser(ObjectParser):
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

    def nexttoken(self) -> Tuple[int, Token]:
        """Override nexttoken() to continue parsing in subsequent streams.

        TODO: If we want to avoid evil implementation inheritance, we
        should do this in the lexer instead.
        """
        while True:
            try:
                return super().nexttoken()
            except StopIteration:
                # Will also raise StopIteration if there are no more,
                # which is exactly what we want
                stream = stream_value(next(self.streamiter))
                log.debug("ContentParser starting new stream %r", stream)
                self.newstream(stream.get_data())


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
        self._dispatch: Dict[PSKeyword, Tuple[Callable, int]] = {}
        for name in dir(self):
            if name.startswith("do_"):
                func = getattr(self, name)
                name = re.sub(r"_a", "*", name[3:])
                if name == "_q":
                    name = "'"
                if name == "_w":
                    name = '"'
                kwd = KWD(name.encode("iso-8859-1"))
                nargs = func.__code__.co_argcount - 1
                self._dispatch[kwd] = (func, nargs)
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
        self.argstack: List[PDFObject] = []

    def __iter__(self) -> Iterator[LayoutObject]:
        log.debug(
            "PageInterpreter: resources=%r, streams=%r, ctm=%r",
            self.resources,
            self.contents,
            self.ctm,
        )
        parser = ContentParser(self.contents)
        for _, obj in parser:
            # These are handled inside the parser as they don't obey
            # the normal syntax rules (PDF 1.7 sec 8.9.7)
            if isinstance(obj, InlineImage):
                yield from self.do_EI(obj)
            elif isinstance(obj, PSKeyword):
                if obj in self._dispatch:
                    method, nargs = self._dispatch[obj]
                    if nargs:
                        args = self.pop(nargs)
                        log.debug("exec: %r %r", obj, args)
                        if len(args) == nargs:
                            gen = method(*args)
                        else:
                            error_msg = (
                                "Insufficient arguments (%d) for operator: %r"
                                % (len(args), obj)
                            )
                            raise PDFInterpreterError(error_msg)
                    else:
                        log.debug("exec: %r", obj)
                        gen = method()
                    if gen is not None:
                        yield from gen
                else:
                    log.warning("Unknown operator: %r", obj)
            else:
                self.push(obj)

    def push(self, obj: PDFObject) -> None:
        self.argstack.append(obj)

    def pop(self, n: int) -> List[PDFObject]:
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
        a1: PDFObject,
        b1: PDFObject,
        c1: PDFObject,
        d1: PDFObject,
        e1: PDFObject,
        f1: PDFObject,
    ) -> None:
        """Concatenate matrix to current transformation matrix"""
        self.ctm = mult_matrix(cast(Matrix, (a1, b1, c1, d1, e1, f1)), self.ctm)

    def do_w(self, linewidth: PDFObject) -> None:
        """Set line width"""
        self.graphicstate.linewidth = cast(float, linewidth)

    def do_J(self, linecap: PDFObject) -> None:
        """Set line cap style"""
        self.graphicstate.linecap = linecap

    def do_j(self, linejoin: PDFObject) -> None:
        """Set line join style"""
        self.graphicstate.linejoin = linejoin

    def do_M(self, miterlimit: PDFObject) -> None:
        """Set miter limit"""
        self.graphicstate.miterlimit = miterlimit

    def do_d(self, dash: PDFObject, phase: PDFObject) -> None:
        """Set line dash pattern"""
        ndash = [num_value(x) for x in list_value(dash)]
        self.graphicstate.dash = DashingStyle(ndash, num_value(phase))

    def do_ri(self, intent: PDFObject) -> None:
        """Set color rendering intent"""
        self.graphicstate.intent = intent

    def do_i(self, flatness: PDFObject) -> None:
        """Set flatness tolerance"""
        self.graphicstate.flatness = flatness

    def do_gs(self, name: PDFObject) -> None:
        """Set parameters from graphics state parameter dictionary"""
        # TODO

    def do_m(self, x: PDFObject, y: PDFObject) -> None:
        """Begin new subpath"""
        self.curpath.append(("m", cast(float, x), cast(float, y)))

    def do_l(self, x: PDFObject, y: PDFObject) -> None:
        """Append straight line segment to path"""
        self.curpath.append(("l", cast(float, x), cast(float, y)))

    def do_c(
        self,
        x1: PDFObject,
        y1: PDFObject,
        x2: PDFObject,
        y2: PDFObject,
        x3: PDFObject,
        y3: PDFObject,
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

    def do_v(self, x2: PDFObject, y2: PDFObject, x3: PDFObject, y3: PDFObject) -> None:
        """Append curved segment to path (initial point replicated)"""
        self.curpath.append(
            ("v", cast(float, x2), cast(float, y2), cast(float, x3), cast(float, y3)),
        )

    def do_y(self, x1: PDFObject, y1: PDFObject, x3: PDFObject, y3: PDFObject) -> None:
        """Append curved segment to path (final point replicated)"""
        self.curpath.append(
            ("y", cast(float, x1), cast(float, y1), cast(float, x3), cast(float, y3)),
        )

    def do_h(self) -> None:
        """Close subpath"""
        self.curpath.append(("h",))

    def do_re(self, x: PDFObject, y: PDFObject, w: PDFObject, h: PDFObject) -> None:
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

    def do_S(self) -> Iterator[LayoutObject]:
        """Stroke path"""
        yield from self.paint_path(
            stroke=True, fill=False, evenodd=False, path=self.curpath
        )
        self.curpath = []

    def do_s(self) -> Iterator[LayoutObject]:
        """Close and stroke path"""
        self.do_h()
        yield from self.do_S()

    def do_f(self) -> Iterator[LayoutObject]:
        """Fill path using nonzero winding number rule"""
        yield from self.paint_path(
            stroke=False, fill=True, evenodd=False, path=self.curpath
        )
        self.curpath = []

    def do_F(self) -> None:
        """Fill path using nonzero winding number rule (obsolete)"""

    def do_f_a(self) -> Iterator[LayoutObject]:
        """Fill path using even-odd rule"""
        yield from self.paint_path(
            stroke=False, fill=True, evenodd=True, path=self.curpath
        )
        self.curpath = []

    def do_B(self) -> Iterator[LayoutObject]:
        """Fill and stroke path using nonzero winding number rule"""
        yield from self.paint_path(
            stroke=True, fill=True, evenodd=False, path=self.curpath
        )
        self.curpath = []

    def do_B_a(self) -> Iterator[LayoutObject]:
        """Fill and stroke path using even-odd rule"""
        yield from self.paint_path(
            stroke=True, fill=True, evenodd=True, path=self.curpath
        )
        self.curpath = []

    def do_b(self) -> Iterator[LayoutObject]:
        """Close, fill, and stroke path using nonzero winding number rule"""
        self.do_h()
        yield from self.do_B()

    def do_b_a(self) -> Iterator[LayoutObject]:
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

    def do_CS(self, name: PDFObject) -> None:
        """Set color space for stroking operations

        Introduced in PDF 1.1
        """
        try:
            self.graphicstate.scs = self.csmap[literal_name(name)]
        except KeyError:
            if settings.STRICT:
                raise PDFInterpreterError("Undefined ColorSpace: %r" % (name,))

    def do_cs(self, name: PDFObject) -> None:
        """Set color space for nonstroking operations"""
        try:
            self.graphicstate.ncs = self.csmap[literal_name(name)]
        except KeyError:
            if settings.STRICT:
                raise PDFInterpreterError("Undefined ColorSpace: %r" % (name,))

    def do_G(self, gray: PDFObject) -> None:
        """Set gray level for stroking operations"""
        self.graphicstate.scs = self.csmap["DeviceGray"]
        self.graphicstate.scolor = self.graphicstate.scs.make_color(gray)

    def do_g(self, gray: PDFObject) -> None:
        """Set gray level for nonstroking operations"""
        self.graphicstate.ncs = self.csmap["DeviceGray"]
        self.graphicstate.ncolor = self.graphicstate.ncs.make_color(gray)

    def do_RG(self, r: PDFObject, g: PDFObject, b: PDFObject) -> None:
        """Set RGB color for stroking operations"""
        self.graphicstate.scs = self.csmap["DeviceRGB"]
        self.graphicstate.scolor = self.graphicstate.scs.make_color(r, g, b)

    def do_rg(self, r: PDFObject, g: PDFObject, b: PDFObject) -> None:
        """Set RGB color for nonstroking operations"""
        self.graphicstate.ncs = self.csmap["DeviceRGB"]
        self.graphicstate.ncolor = self.graphicstate.ncs.make_color(r, g, b)

    def do_K(self, c: PDFObject, m: PDFObject, y: PDFObject, k: PDFObject) -> None:
        """Set CMYK color for stroking operations"""
        self.graphicstate.scs = self.csmap["DeviceCMYK"]
        self.graphicstate.scolor = self.graphicstate.scs.make_color(c, m, y, k)

    def do_k(self, c: PDFObject, m: PDFObject, y: PDFObject, k: PDFObject) -> None:
        """Set CMYK color for nonstroking operations"""
        self.graphicstate.ncs = self.csmap["DeviceCMYK"]
        self.graphicstate.ncolor = self.graphicstate.ncs.make_color(c, m, y, k)

    def do_SCN(self) -> None:
        """Set color for stroking operations."""
        if self.graphicstate.scs is None:
            if settings.STRICT:
                raise PDFInterpreterError("No colorspace specified!")
            self.graphicstate.scs = self.csmap["DeviceGray"]
        self.graphicstate.scolor = self.graphicstate.scs.make_color(
            *self.pop(self.graphicstate.scs.ncomponents)
        )

    def do_scn(self) -> None:
        """Set color for nonstroking operations"""
        if self.graphicstate.ncs is None:
            if settings.STRICT:
                raise PDFInterpreterError("No colorspace specified!")
            self.graphicstate.ncs = self.csmap["DeviceGray"]
        self.graphicstate.ncolor = self.graphicstate.ncs.make_color(
            *self.pop(self.graphicstate.ncs.ncomponents)
        )

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

    def do_MP(self, tag: PDFObject) -> None:
        """Define marked-content point"""
        self.do_tag(cast(PSLiteral, tag))

    def do_DP(self, tag: PDFObject, props: PDFObject) -> None:
        """Define marked-content point with property list"""
        self.do_tag(cast(PSLiteral, tag), props)

    def do_BMC(self, tag: PDFObject) -> None:
        """Begin marked-content sequence"""
        self.begin_tag(cast(PSLiteral, tag))

    def do_BDC(self, tag: PDFObject, props: PDFObject) -> None:
        """Begin marked-content sequence with property list"""
        self.begin_tag(cast(PSLiteral, tag), props)

    def do_EMC(self) -> None:
        """End marked-content sequence"""
        self.end_tag()

    def do_Tc(self, space: PDFObject) -> None:
        """Set character spacing.

        Character spacing is used by the Tj, TJ, and ' operators.

        :param space: a number expressed in unscaled text space units.
        """
        self.textstate.charspace = cast(float, space)

    def do_Tw(self, space: PDFObject) -> None:
        """Set the word spacing.

        Word spacing is used by the Tj, TJ, and ' operators.

        :param space: a number expressed in unscaled text space units
        """
        self.textstate.wordspace = cast(float, space)

    def do_Tz(self, scale: PDFObject) -> None:
        """Set the horizontal scaling.

        :param scale: is a number specifying the percentage of the normal width
        """
        self.textstate.scaling = cast(float, scale)

    def do_TL(self, leading: PDFObject) -> None:
        """Set the text leading.

        Text leading is used only by the T*, ', and " operators.

        :param leading: a number expressed in unscaled text space units
        """
        self.textstate.leading = -cast(float, leading)

    def do_Tf(self, fontid: PDFObject, fontsize: PDFObject) -> None:
        """Set the text font

        :param fontid: the name of a font resource in the Font subdictionary
            of the current resource dictionary
        :param fontsize: size is a number representing a scale factor.
        """
        try:
            self.textstate.font = self.fontmap[literal_name(fontid)]
        except KeyError:
            if settings.STRICT:
                raise PDFInterpreterError("Undefined Font id: %r" % (fontid,))
            doc = self.page.doc()
            if doc is None:
                raise RuntimeError("Document no longer exists!")
            self.textstate.font = doc.get_font(None, {})
        self.textstate.fontsize = cast(float, fontsize)

    def do_Tr(self, render: PDFObject) -> None:
        """Set the text rendering mode"""
        self.textstate.render = cast(int, render)

    def do_Ts(self, rise: PDFObject) -> None:
        """Set the text rise

        :param rise: a number expressed in unscaled text space units
        """
        self.textstate.rise = cast(float, rise)

    def do_Td(self, tx: PDFObject, ty: PDFObject) -> None:
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

    def do_TD(self, tx: PDFObject, ty: PDFObject) -> None:
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
        a: PDFObject,
        b: PDFObject,
        c: PDFObject,
        d: PDFObject,
        e: PDFObject,
        f: PDFObject,
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

    def do_TJ(self, seq: PDFObject) -> Iterator[LayoutObject]:
        """Show text, allowing individual glyph positioning"""
        if self.textstate.font is None:
            if settings.STRICT:
                raise PDFInterpreterError("No font specified!")
            return
        yield from self.render_string(
            cast(TextSeq, seq),
        )

    def do_Tj(self, s: PDFObject) -> Iterator[LayoutObject]:
        """Show text"""
        yield from self.do_TJ([s])

    def do__q(self, s: PDFObject) -> Iterator[LayoutObject]:
        """Move to next line and show text

        The ' (single quote) operator.
        """
        self.do_T_a()
        yield from self.do_TJ([s])

    def do__w(
        self, aw: PDFObject, ac: PDFObject, s: PDFObject
    ) -> Iterator[LayoutObject]:
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

    def do_EI(self, obj: PDFObject) -> Iterator[LayoutObject]:
        """End inline image object"""
        if isinstance(obj, InlineImage):
            # Inline images obviously are not indirect objects, so
            # have no object ID, so... make something up?
            iobjid = "inline_image_%d" % id(obj)
            yield self.render_image(iobjid, obj)
        else:
            # FIXME: Do... something?
            pass

    def do_Do(self, xobjid_arg: PDFObject) -> Iterator[LayoutObject]:
        """Invoke named XObject"""
        xobjid = literal_name(xobjid_arg)
        try:
            xobj = stream_value(self.xobjmap[xobjid])
        except KeyError:
            log.debug("Undefined xobject id: %r", xobjid)
            return
        log.debug("Processing xobj: %r", xobj)
        subtype = xobj.get("Subtype")
        if subtype is LITERAL_FORM and "BBox" in xobj:
            matrix = cast(Matrix, list_value(xobj.get("Matrix", MATRIX_IDENTITY)))
            # According to PDF reference 1.7 section 4.9.1, XObjects in
            # earlier PDFs (prior to v1.2) use the page's Resources entry
            # instead of having their own Resources entry.
            xobjres = xobj.get("Resources")
            resources = None if xobjres is None else dict_value(xobjres)
            interpreter = PageInterpreter(
                self.page, resources=resources, contents=[xobj]
            )
            interpreter.ctm = mult_matrix(matrix, self.ctm)
            yield from interpreter
        elif subtype is LITERAL_IMAGE and "Width" in xobj and "Height" in xobj:
            yield self.render_image(xobjid, xobj)
        else:
            # unsupported xobject type.
            pass

    def begin_tag(self, tag: PSLiteral, props: Optional[PDFObject] = None) -> None:
        """Handle beginning of tag, setting current MCID if any."""
        self.cur_tag = decode_text(tag.name)
        # FIXME: Many other useful things like ActualText
        if isinstance(props, dict) and "MCID" in props:
            self.cur_mcid = props["MCID"]
        else:
            self.cur_mcid = None

    def do_tag(self, tag: PSLiteral, props: Optional[PDFObject] = None) -> None:
        pass

    def end_tag(self) -> None:
        """Handle beginning of tag, clearing current MCID."""
        self.cur_tag = None
        self.cur_mcid = None

    def render_image(self, name: str, stream: ContentStream) -> LayoutObject:
        colorspace = stream.get_any(("CS", "ColorSpace"))
        if not isinstance(colorspace, list):
            colorspace = [colorspace]
        # PDF 1.7 sec 8.3.24: All images shall be 1 unit wide by 1
        # unit high in user space, regardless of the number of samples
        # in the image. To be painted, an image shall be mapped to a
        # region of the page by temporarily altering the CTM.
        bounds = ((0, 0), (1, 0), (0, 1), (1, 1))
        x0, y0, x1, y1 = get_bound(
            apply_matrix_pt(self.ctm, (p, q)) for (p, q) in bounds
        )
        return LayoutObject(
            object_type="image",
            x0=x0,
            y0=y0,
            x1=x1,
            y1=y1,
            width=x1 - x0,
            height=y1 - y0,
            stream=stream,
            name=name,
            mcid=self.cur_mcid,
            tag=self.cur_tag,
            srcsize=(stream.get_any(("W", "Width")), stream.get_any(("H", "Height"))),
            imagemask=stream.get_any(("IM", "ImageMask")),
            bits=stream.get_any(("BPC", "BitsPerComponent"), 1),
            colorspace=colorspace,
        )

    def paint_path(
        self,
        *,
        stroke: bool,
        fill: bool,
        evenodd: bool,
        path: Sequence[PathSegment],
    ) -> Iterator[LayoutObject]:
        """Paint paths described in section 4.4 of the PDF reference manual"""
        shape = "".join(x[0] for x in path)
        gstate = self.graphicstate
        ncs = self.graphicstate.ncs
        scs = self.graphicstate.scs

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
            # FIXME: WTF, this seems to repeat the same transformation
            # as the previous line?
            operators = [str(operation[0]) for operation in path]
            transformed_points = [
                [
                    apply_matrix_pt(self.ctm, (float(operand1), float(operand2)))
                    for operand1, operand2 in zip(operation[1::2], operation[2::2])
                ]
                for operation in path
            ]
            transformed_path = [(o, *p) for o, p in zip(operators, transformed_points)]

            if shape in {"mlh", "ml"}:
                # single line segment
                #
                # Note: 'ml', in conditional above, is a frequent anomaly
                # that we want to support.
                (x0, y0), (x1, y1) = pts[0:2]  # in case there is an 'h'
                if x0 > x1:
                    (x1, x0) = (x0, x1)
                if y0 > y1:
                    (y1, y0) = (y0, y1)
                yield LayoutObject(
                    object_type="line",
                    x0=x0,
                    y0=y0,
                    x1=x1,
                    y1=y1,
                    width=x1 - x0,
                    height=y1 - y0,
                    mcid=self.cur_mcid,
                    tag=self.cur_tag,
                    path=transformed_path,
                    pts=pts,
                    stroke=stroke,
                    fill=fill,
                    evenodd=evenodd,
                    linewidth=gstate.linewidth,
                    stroking_color=gstate.scolor,
                    non_stroking_color=gstate.ncolor,
                    dash=gstate.dash,
                    ncs=ncs,
                    scs=scs,
                )

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
                    yield LayoutObject(
                        object_type="rect",
                        x0=x0,
                        y0=y0,
                        x1=x2,
                        y1=y2,
                        width=x2 - x0,
                        height=y2 - y0,
                        mcid=self.cur_mcid,
                        tag=self.cur_tag,
                        path=transformed_path,
                        pts=pts,
                        stroke=stroke,
                        fill=fill,
                        evenodd=evenodd,
                        linewidth=gstate.linewidth,
                        stroking_color=gstate.scolor,
                        non_stroking_color=gstate.ncolor,
                        dash=gstate.dash,
                        ncs=ncs,
                        scs=scs,
                    )
                else:
                    x0, y0, x1, y1 = get_bound(pts)
                    yield LayoutObject(
                        object_type="curve",
                        x0=x0,
                        y0=y0,
                        x1=x1,
                        y1=y1,
                        width=x1 - x0,
                        height=y1 - y0,
                        mcid=self.cur_mcid,
                        tag=self.cur_tag,
                        path=transformed_path,
                        pts=pts,
                        stroke=stroke,
                        fill=fill,
                        evenodd=evenodd,
                        linewidth=gstate.linewidth,
                        stroking_color=gstate.scolor,
                        non_stroking_color=gstate.ncolor,
                        dash=gstate.dash,
                        ncs=ncs,
                        scs=scs,
                    )
            else:
                x0, y0, x1, y1 = get_bound(pts)
                yield LayoutObject(
                    object_type="curve",
                    x0=x0,
                    y0=y0,
                    x1=x1,
                    y1=y1,
                    width=x1 - x0,
                    height=y1 - y0,
                    mcid=self.cur_mcid,
                    tag=self.cur_tag,
                    path=transformed_path,
                    pts=pts,
                    stroke=stroke,
                    fill=fill,
                    evenodd=evenodd,
                    linewidth=gstate.linewidth,
                    stroking_color=gstate.scolor,
                    non_stroking_color=gstate.ncolor,
                    dash=gstate.dash,
                    ncs=ncs,
                    scs=scs,
                )

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
    ) -> Tuple[LayoutObject, float]:
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
        item = LayoutObject(
            object_type="char",
            x0=x0,
            y0=y0,
            x1=x1,
            y1=y1,
            width=x1 - x0,
            height=y1 - y0,
            size=size,
            adv=adv,
            upright=upright,
            text=text,
            matrix=matrix,
            fontname=font.fontname,
            dash=self.graphicstate.dash,
            ncs=self.graphicstate.ncs,
            scs=self.graphicstate.scs,
            stroking_color=self.graphicstate.scolor,
            non_stroking_color=self.graphicstate.ncolor,
            mcid=self.cur_mcid,
            tag=self.cur_tag,
        )
        return item, adv

    def render_string(
        self,
        seq: TextSeq,
    ) -> Iterator[LayoutObject]:
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
