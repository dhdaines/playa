"""
Classes for looking at pages and their contents.
"""

import itertools
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
    Literal,
    NamedTuple,
    Optional,
    Sequence,
    Tuple,
    TypedDict,
    Union,
    cast,
)

from playa.color import (
    PREDEFINED_COLORSPACE,
    LITERAL_RELATIVE_COLORIMETRIC,
    BASIC_BLACK,
    Color,
    ColorSpace,
    get_colorspace,
)
from playa.exceptions import (
    PDFInterpreterError,
    PDFUnicodeNotDefined,
)
from playa.font import Font

# FIXME: PDFObject needs to go in pdftypes somehow
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
    Point,
    Rect,
    apply_matrix_pt,
    apply_matrix_norm,
    decode_text,
    get_bound,
    get_transformed_bound,
    make_compat_bytes,
    mult_matrix,
    parse_rect,
    normalize_rect,
    translate_matrix,
)

if TYPE_CHECKING:
    from playa.document import Document

# Stub out Polars if not present
try:
    import polars as pl
except ImportError:

    class pl:  # type: ignore
        def Array(*args, **kwargs): ...
        def List(*args, **kwargs): ...
        def Object(*args, **kwargs): ...


log = logging.getLogger(__name__)

# some predefined literals and keywords.
LITERAL_PAGE = LIT("Page")
LITERAL_PAGES = LIT("Pages")
LITERAL_FORM = LIT("Form")
LITERAL_IMAGE = LIT("Image")
TextSeq = Iterable[Union[int, float, bytes]]
DeviceSpace = Literal["page", "screen", "user"]


class Page:
    """An object that holds the information about a page.

    Args:
      doc: a Document object.
      pageid: the integer PDF object ID associated with the page in the page tree.
      attrs: a dictionary of page attributes.
      label: page label string.
      page_idx: 0-based index of the page in the document.
      space: the device space to use for interpreting content

    Attributes:
      pageid: the integer object ID associated with the page in the page tree
      attrs: a dictionary of page attributes.
      resources: a dictionary of resources used by the page.
      mediabox: the physical size of the page.
      cropbox: the crop rectangle of the page.
      rotate: the page rotation (in degree).
      label: the page's label (typically, the logical page number).
      page_number: the "physical" page number, indexed from 1.

    """

    def __init__(
        self,
        doc: "Document",
        pageid: int,
        attrs: Dict,
        label: Optional[str],
        page_idx: int = 0,
        space: DeviceSpace = "screen",
    ) -> None:
        self.doc = weakref.ref(doc)
        self.pageid = pageid
        self.attrs = attrs
        self.label = label
        self.page_idx = page_idx
        self.space = space
        self.lastmod = resolve1(self.attrs.get("LastModified"))
        self.resources: Dict[str, PDFObject] = dict_value(
            self.attrs.get("Resources", {})
        )
        if "MediaBox" in self.attrs:
            self.mediabox = normalize_rect(
                parse_rect(resolve1(val) for val in resolve1(self.attrs["MediaBox"]))
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
                self.cropbox = normalize_rect(
                    parse_rect(resolve1(val) for val in resolve1(self.attrs["CropBox"]))
                )
            except ValueError:
                log.warning("Invalid CropBox in /Page, defaulting to MediaBox")

        self.rotate = (int_value(self.attrs.get("Rotate", 0)) + 360) % 360
        self.annots = self.attrs.get("Annots")
        self.beads = self.attrs.get("B")
        if "Contents" in self.attrs:
            self._contents: List[PDFObject] = resolve1(self.attrs["Contents"])
            assert self._contents is not None
            if not isinstance(self._contents, list):
                self._contents = [self._contents]
        else:
            self._contents = []

    @property
    def streams(self) -> Iterator[ContentStream]:
        """Return resolved content streams."""
        for obj in self._contents:
            yield stream_value(obj)

    @property
    def width(self) -> float:
        """Width of the page in default user space units."""
        x0, _, x1, _ = self.mediabox
        return x1 - x0

    @property
    def height(self) -> float:
        """Width of the page in default user space units."""
        _, y0, _, y1 = self.mediabox
        return y1 - y0

    @property
    def contents(self) -> Iterator[PDFObject]:
        """Iterator over PDF objects in the content streams."""
        for pos, obj in ContentParser(self._contents):
            yield obj

    def __iter__(self) -> Iterator["ContentObject"]:
        """Iterator over lazy layout objects."""
        return iter(LazyInterpreter(self, self._contents))

    @property
    def paths(self) -> Iterator["PathObject"]:
        """Iterator over lazy path objects."""
        return (obj for obj in self if isinstance(obj, PathObject))

    @property
    def images(self) -> Iterator["ImageObject"]:
        """Iterator over lazy image objects."""
        return (obj for obj in self if isinstance(obj, ImageObject))

    @property
    def texts(self) -> Iterator["TextObject"]:
        """Iterator over lazy text objects."""
        return (obj for obj in self if isinstance(obj, TextObject))

    @property
    def xobjects(self) -> Iterator["XObjectObject"]:
        """Return resolved and rendered Form XObjects.

        This does *not* return any image or PostScript XObjects.  You
        can get images via the `images` property.  Apparently you
        aren't supposed to use PostScript XObjects for anything, ever.

        Note that these are the XObjects as rendered on the page, so
        you may see the same named XObject multiple times.  If you
        need to access their actual definitions you'll have to look at
        `page.resources`.
        """
        return (obj for obj in self if isinstance(obj, XObjectObject))

    @property
    def layout(self) -> Iterator["LayoutDict"]:
        """Iterator over eager layout object dictionaries."""
        return iter(PageInterpreter(self, self._contents))

    @property
    def tokens(self) -> Iterator[Token]:
        """Iterator over tokens in the content streams."""
        parser = ContentParser(self._contents)
        while True:
            try:
                pos, tok = parser.nexttoken()
            except StopIteration:
                return
            yield tok

    def __repr__(self) -> str:
        return f"<Page: Resources={self.resources!r}, MediaBox={self.mediabox!r}>"


TextOperator = Literal["Tc", "Tw", "Tz", "TL", "Tf", "Tr", "Ts", "Td", "Tm", "T*", "TJ"]
TextArgument = Union[float, bytes, Font]


@dataclass
class TextState:
    """PDF Text State (PDF 1.7 section 9.3.1).

    Exceptionally, the line matrix and text matrix are represented
    more compactly with the line matrix itself in `line_matrix`, which
    gets translated by `glyph_offset` for the current glyph (note:
    expressed in **user space**), which pdfminer confusingly called
    `linematrix`, to produce the text matrix.

    Attributes:
      line_matrix: The text line matrix, which defines (in user
        space) the start of the current line of text, which may or may
        not correspond to an actual line because PDF is a presentation
        format.
      glyph_offset: The offset of the current glyph with relation to
        the line matrix (in user space).  To get this in device space
        you may use `playa.utils.apply_matrix_norm` with
        `TextObject.ctm`.
      font: The current font.
      fontsize: The current font size, **in text space units**.
        This is often just 1.0 as it relies on the text matrix (you
        may use `line_matrix` here) to scale it to the actual size in
        user space.
      charspace: Extra spacing to add between each glyph, in
        text space units.
      wordspace: The width of a space, defined curiously as `cid==32`
        (But PDF Is A prESeNTaTion fORmAT sO ThERe maY NOt Be aNY
        SpACeS!!), in text space units.
      scaling: The horizontal scaling factor as defined by the PDF
        standard.
      leading: The leading as defined by the PDF standard.
      render_mode: The PDF rendering mode.  The really important one
        here is 3, which means "don't render the text".  You might
        want to use this to detect invisible text.
      rise: The text rise (superscript or subscript position), in text
        space units.
    """

    line_matrix: Matrix = MATRIX_IDENTITY
    glyph_offset: Point = (0, 0)
    font: Optional[Font] = None
    fontsize: float = 0
    charspace: float = 0
    wordspace: float = 0
    scaling: float = 100
    leading: float = 0
    render_mode: int = 0
    rise: float = 0

    def reset(self) -> None:
        """Reset the text state"""
        self.line_matrix = MATRIX_IDENTITY
        self.glyph_offset = (0, 0)

    def update(self, operator: TextOperator, *args: TextArgument):
        """Apply a text state operator"""
        if operator == "Tc":
            # FIXME: these casts are not evil like the other ones,
            # but it would be nice to be able to avoid them.
            self.charspace = cast(float, args[0])
        elif operator == "Tw":
            self.wordspace = cast(float, args[0])
        elif operator == "Tz":
            self.scaling = cast(float, args[0])
        elif operator == "TL":
            self.leading = cast(float, args[0])
        elif operator == "Tf":
            self.font = cast(Font, args[0])
            self.fontsize = cast(float, args[1])
        elif operator == "Tr":
            self.render_mode = cast(int, args[0])
        elif operator == "Ts":
            self.rise = cast(float, args[0])
        elif operator == "Td":
            tx = cast(float, args[0])
            ty = cast(float, args[1])
            (a, b, c, d, e, f) = self.line_matrix
            e_new = tx * a + ty * c + e
            f_new = tx * b + ty * d + f
            self.line_matrix = (a, b, c, d, e_new, f_new)
            self.glyph_offset = (0, 0)
        elif operator == "Tm":
            a, b, c, d, e, f = (cast(float, x) for x in args)
            self.line_matrix = (a, b, c, d, e, f)
            self.glyph_offset = (0, 0)
        elif operator == "T*":
            # PDF 1.7 table 108: equivalent to 0 -leading Td - but
            # because we are lazy we don't know the leading until
            # we get here, so we can't expand it in advance.
            (a, b, c, d, e, f) = self.line_matrix
            self.line_matrix = (
                a,
                b,
                c,
                d,
                -self.leading * c + e,
                -self.leading * d + f,
            )
            self.glyph_offset = (0, 0)


class DashPattern(NamedTuple):
    """
    Line dash pattern in PDF graphics state (PDF 1.7 section 8.4.3.6).

    Attributes:
      dash: lengths of dashes and gaps in user space units
      phase: starting position in the dash pattern
    """

    dash: Tuple[float, ...]
    phase: float

    def __str__(self):
        if len(self.dash) == 0:
            return ""
        else:
            return f"{self.dash} {self.phase}"


@dataclass
class GraphicState:
    """PDF Graphics state (PDF 1.7 section 8.4)

    Attributes:
      linewidth: Line width in user space units (sec. 8.4.3.2)
      linecap: Line cap style (sec. 8.4.3.3)
      linejoin: Line join style (sec. 8.4.3.4)
      miterlimit: Maximum length of mitered line joins (sec. 8.4.3.5)
      dash: Dash pattern for stroking (sec 8.4.3.6)
      intent: Rendering intent (sec. 8.6.5.8)
      flatness: The precision with which curves shall be rendered on
        the output device (sec. 10.6.2)
      scolor: Colour used for stroking operations
      scs: Colour space used for stroking operations
      ncolor: Colour used for non-stroking operations
      scs: Colour space used for non-stroking operations
    """

    linewidth: float = 0
    linecap: int = 0
    linejoin: int = 0
    miterlimit: float = 10
    dash: DashPattern = DashPattern((), 0)
    intent: PSLiteral = LITERAL_RELATIVE_COLORIMETRIC
    flatness: float = 1
    # stroking color
    scolor: Color = BASIC_BLACK
    # stroking color space
    scs: ColorSpace = PREDEFINED_COLORSPACE["DeviceGray"]
    # non stroking color
    ncolor: Color = BASIC_BLACK
    # non stroking color space
    ncs: ColorSpace = PREDEFINED_COLORSPACE["DeviceGray"]


class LayoutDict(TypedDict, total=False):
    """Dictionary-based layout objects.

    These are somewhat like the `T_obj` dictionaries returned by
    pdfplumber.  The type of coordinates returned are determined by
    the `space` argument passed to `Page`.  By default, `(0, 0)` is
    the top-left corner of the page, with 72 units per inch.

    All values can be converted to strings in some meaningful fashion,
    such that you can simply write one of these to a CSV.  You can access
    the field names through the `__annotations__` property:

        writer = DictWriter(fieldnames=LayoutDict.__annotations__.keys())
        dictwriter.write_rows(writer)

    Attributes:
      object_type: Type of object as a string.
      mcid: Containing marked content section ID (or None if marked
        content has no ID, such as artifacts or if there is no logical
        structure).
      tag: Containing marked content tag name (or None if not in a marked
        content section).
      xobjid: String name of containing Form XObject, if any.
      cid: Integer character ID of glyph, if `object_type == "char"`.
      text: Unicode mapping for glyph, if any.
      fontname: str
      size: Font size in device space.
      glyph_offset_x: Horizontal offset (in device space) of glyph
        from start of line.
      glyph_offset_y: Vertical offset (in device space) of glyph from
        start of line.
      render_mode: Text rendering mode.
      upright: FIXME: Not really sure what this means.  pdfminer.six?
      x0: Minimum x coordinate of bounding box (top or bottom
        depending on device space).
      x1: Maximum x coordinate of bounding box (top or bottom
        depending on device space).
      y0: Minimum y coordinate of bounding box (left or right
        depending on device space).
      x1: Minimum x coordinate of bounding box (left or right
        depending on device space).
      stroking_colorspace: String name of colour space for stroking
        operations.
      stroking_color: Numeric parameters for stroking color.
      stroking_pattern: Name of stroking pattern, if any.
      non_stroking_colorspace: String name of colour space for non-stroking
        operations.
      non_stroking_color: Numeric parameters for non-stroking color.
      non_stroking_pattern: Name of stroking pattern, if any.
      path_ops: Sequence of path operations (e.g. `"mllh"` for a
        triangle or `"mlllh"` for a quadrilateral)
      dash_pattern: Sequence of user space units for alternating
        stroke and non-stroke segments of dash pattern, `()` for solid
        line. (Cannot be in device space because this would depend on
        which direction the line or curve is drawn).
      dash_phase: Initial position in `dash_pattern` in user space
        units.  (see above for why it's in user space)
      evenodd: Was this path filled with Even-Odd (if `True`) or
        Nonzero-Winding-Number rule (if `False`)?  Note that this is
        **meaningless** for determining if a path is actually filled
        since subpaths have already been decomposed.  If you really
        care then use the lazy API instead.
      stroke: Is this path stroked?
      fill: Is this path filled?
      linewidth: Line width in user space units (again, not possible
        to transform to device space).
      pts_x: X coordinates of path endpoints, one for each character
        in `path_ops`.  This is optimized for CSV/DataFrame output, if
        you care about the control points then use the lazy API.
      pts_y: Y coordinates of path endpoints, one for each character
        in `path_ops`.  This is optimized for CSV/DataFrame output, if
        you care about the control points then use the lazy API.
      stream: Object number and generation number for the content
        stream associated with an image, or `None` for inline images.
        If you want image data then use the lazy API.
      imagemask: Is this image a mask?
      image_colorspace: String description of image colour space, or
        `None` if irrelevant/forbidden,
      srcsize: Source dimensions of image in pixels.
      bits: Number of bits per channel of image.
    """

    object_type: str
    mcid: Union[int, None]
    tag: Union[str, None]
    xobjid: Union[str, None]
    cid: int
    text: Union[str, None]
    fontname: str
    size: float
    glyph_offset_x: float
    glyph_offset_y: float
    render_mode: int
    upright: bool
    x0: float
    y0: float
    x1: float
    y1: float
    stroking_colorspace: str
    stroking_color: Tuple[float, ...]
    stroking_pattern: Union[str, None]
    non_stroking_colorspace: str
    non_stroking_color: Tuple[float, ...]
    non_stroking_pattern: Union[str, None]
    path_ops: str
    dash_pattern: Tuple[float, ...]
    dash_phase: float
    evenodd: bool
    stroke: bool
    fill: bool
    linewidth: float
    pts_x: List[float]
    pts_y: List[float]
    stream: Union[Tuple[int, int], None]
    imagemask: bool
    image_colorspace: Union[ColorSpace, None]
    srcsize: Tuple[int, int]
    bits: int


fieldnames = LayoutDict.__annotations__.keys()
schema = {
    "object_type": str,
    "mcid": int,
    "tag": str,
    "xobjid": str,
    "text": str,
    "cid": int,
    "fontname": str,
    "size": float,
    "glyph_offset_x": float,
    "glyph_offset_y": float,
    "render_mode": int,
    "upright": bool,
    "x0": float,
    "x1": float,
    "y0": float,
    "y1": float,
    "stroking_colorspace": str,
    "non_stroking_colorspace": str,
    "stroking_color": pl.List(float),
    "non_stroking_color": pl.List(float),
    "path_ops": str,
    "dash_pattern": pl.List(float),
    "dash_phase": float,
    "evenodd": bool,
    "stroke": bool,
    "fill": bool,
    "linewidth": float,
    "pts_x": pl.List(float),
    "pts_y": pl.List(float),
    "stream": pl.Array(int, 2),
    "imagemask": bool,
    "image_colorspace": str,
    "srcsize": pl.Array(int, 2),
    "bits": int,
}


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

    def __init__(self, streams: Iterable[PDFObject]) -> None:
        self.streamiter = iter(streams)
        try:
            stream = stream_value(next(self.streamiter))
            log.debug("ContentParser starting stream %r", stream)
            super().__init__(stream.buffer)
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
                self.newstream(stream.buffer)


class MarkedContent(NamedTuple):
    """
    Marked content point or section in a PDF page.

    Attributes:
      mcid: Marked content section ID, or `None` for a marked content point.
      tag: Name of tag for this marked content.
      props: Marked content property dictionary.
    """

    mcid: Union[int, None]
    tag: str
    props: Dict[str, PDFObject]


PathOperator = Literal["h", "m", "l", "v", "c", "y"]


class PathSegment(NamedTuple):
    """
    Segment in a PDF graphics path.
    """

    operator: PathOperator
    points: Tuple[Point, ...]


def make_seg(operator: PathOperator, *points: Point):
    return PathSegment(operator, points)


def point_value(x: PDFObject, y: PDFObject) -> Point:
    return (num_value(x), num_value(y))


class BaseInterpreter:
    """Core state for the PDF interpreter."""

    mcs: Union[MarkedContent, None] = None
    ctm: Matrix
    device_ctm: Matrix

    def __init__(
        self,
        page: Page,
        contents: Iterable[PDFObject],
        resources: Union[Dict, None] = None,
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
        self.contents = contents
        (x0, y0, x1, y1) = page.mediabox
        width = x1 - x0
        height = y1 - y0
        # PDF 1.7 section 8.4.1: Initial value: a matrix that
        # transforms default user coordinates to device coordinates.
        #
        # We keep this as `device_ctm` in order to transform layout
        # attributes in tagged PDFs which are specified in default
        # user space (PDF 1.7 section 14.8.5.4.3, table 344)
        #
        # "screen" device space: origin is top left of MediaBox
        if page.space == "screen":
            ctm = self.device_ctm = (1.0, 0.0, 0.0, -1.0, -x0, y1)
        # "page" device space: origin is bottom left of MediaBox
        elif page.space == "page":
            ctm = self.device_ctm = (1.0, 0.0, 0.0, 1.0, -x0, -y0)
        # "user" device space: no transformation or rotation
        else:
            if page.space != "user":
                log.warning("Unknown device space: %r", page.space)
            ctm = self.device_ctm = MATRIX_IDENTITY
            width = height = 0
        # If rotation is requested, apply rotation to the initial ctm
        if page.rotate == 90:
            # x' = y
            # y' = width - x
            ctm = mult_matrix((0, -1, 1, 0, 0, width), ctm)
        elif page.rotate == 180:
            # x' = width - x
            # y' = height - y
            ctm = mult_matrix((-1, 0, 0, -1, width, height), ctm)
        elif page.rotate == 270:
            # x' = height - y
            # y' = x
            ctm = mult_matrix((0, 1, -1, 0, height, 0), ctm)
        elif page.rotate != 0:
            log.warning("Invalid /Rotate: %r", page.rotate)
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
        self.graphicstate.linewidth = num_value(linewidth)

    def do_J(self, linecap: PDFObject) -> None:
        """Set line cap style"""
        self.graphicstate.linecap = int_value(linecap)

    def do_j(self, linejoin: PDFObject) -> None:
        """Set line join style"""
        self.graphicstate.linejoin = int_value(linejoin)

    def do_M(self, miterlimit: PDFObject) -> None:
        """Set miter limit"""
        self.graphicstate.miterlimit = num_value(miterlimit)

    def do_d(self, dash: PDFObject, phase: PDFObject) -> None:
        """Set line dash pattern"""
        ndash = tuple(num_value(x) for x in list_value(dash))
        self.graphicstate.dash = DashPattern(ndash, num_value(phase))

    def do_ri(self, intent: PDFObject) -> None:
        """Set color rendering intent"""
        # FIXME: Should actually be a (runtime checked) enum
        self.graphicstate.intent = cast(PSLiteral, intent)

    def do_i(self, flatness: PDFObject) -> None:
        """Set flatness tolerance"""
        self.graphicstate.flatness = num_value(flatness)

    def do_gs(self, name: PDFObject) -> None:
        """Set parameters from graphics state parameter dictionary"""
        # TODO

    def do_m(self, x: PDFObject, y: PDFObject) -> None:
        """Begin new subpath"""
        self.curpath.append(make_seg("m", point_value(x, y)))

    def do_l(self, x: PDFObject, y: PDFObject) -> None:
        """Append straight line segment to path"""
        self.curpath.append(make_seg("l", point_value(x, y)))

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
            make_seg(
                "c",
                point_value(x1, y1),
                point_value(x2, y2),
                point_value(x3, y3),
            ),
        )

    def do_v(self, x2: PDFObject, y2: PDFObject, x3: PDFObject, y3: PDFObject) -> None:
        """Append curved segment to path (initial point replicated)"""
        self.curpath.append(
            make_seg(
                "v",
                point_value(x2, y2),
                point_value(x3, y3),
            )
        )

    def do_y(self, x1: PDFObject, y1: PDFObject, x3: PDFObject, y3: PDFObject) -> None:
        """Append curved segment to path (final point replicated)"""
        self.curpath.append(
            make_seg(
                "y",
                point_value(x1, y1),
                point_value(x3, y3),
            )
        )

    def do_h(self) -> None:
        """Close subpath"""
        self.curpath.append(make_seg("h"))

    def do_re(self, x: PDFObject, y: PDFObject, w: PDFObject, h: PDFObject) -> None:
        """Append rectangle to path"""
        x = num_value(x)
        y = num_value(y)
        w = num_value(w)
        h = num_value(h)
        self.curpath.append(make_seg("m", point_value(x, y)))
        self.curpath.append(make_seg("l", point_value(x + w, y)))
        self.curpath.append(make_seg("l", point_value(x + w, y + h)))
        self.curpath.append(make_seg("l", point_value(x, y + h)))
        self.curpath.append(make_seg("h"))

    def do_n(self) -> None:
        """End path without filling or stroking"""
        self.curpath = []

    def do_W(self) -> None:
        """Set clipping path using nonzero winding number rule"""

    def do_W_a(self) -> None:
        """Set clipping path using even-odd rule"""

    def do_CS(self, name: PDFObject) -> None:
        """Set color space for stroking operators

        Introduced in PDF 1.1
        """
        try:
            self.graphicstate.scs = self.csmap[literal_name(name)]
        except KeyError:
            log.warning("Undefined ColorSpace: %r", name)

    def do_cs(self, name: PDFObject) -> None:
        """Set color space for nonstroking operators"""
        try:
            self.graphicstate.ncs = self.csmap[literal_name(name)]
        except KeyError:
            log.warning("Undefined ColorSpace: %r", name)

    def do_G(self, gray: PDFObject) -> None:
        """Set gray level for stroking operators"""
        self.graphicstate.scs = self.csmap["DeviceGray"]
        self.graphicstate.scolor = self.graphicstate.scs.make_color(gray)

    def do_g(self, gray: PDFObject) -> None:
        """Set gray level for nonstroking operators"""
        self.graphicstate.ncs = self.csmap["DeviceGray"]
        self.graphicstate.ncolor = self.graphicstate.ncs.make_color(gray)

    def do_RG(self, r: PDFObject, g: PDFObject, b: PDFObject) -> None:
        """Set RGB color for stroking operators"""
        self.graphicstate.scs = self.csmap["DeviceRGB"]
        self.graphicstate.scolor = self.graphicstate.scs.make_color(r, g, b)

    def do_rg(self, r: PDFObject, g: PDFObject, b: PDFObject) -> None:
        """Set RGB color for nonstroking operators"""
        self.graphicstate.ncs = self.csmap["DeviceRGB"]
        self.graphicstate.ncolor = self.graphicstate.ncs.make_color(r, g, b)

    def do_K(self, c: PDFObject, m: PDFObject, y: PDFObject, k: PDFObject) -> None:
        """Set CMYK color for stroking operators"""
        self.graphicstate.scs = self.csmap["DeviceCMYK"]
        self.graphicstate.scolor = self.graphicstate.scs.make_color(c, m, y, k)

    def do_k(self, c: PDFObject, m: PDFObject, y: PDFObject, k: PDFObject) -> None:
        """Set CMYK color for nonstroking operators"""
        self.graphicstate.ncs = self.csmap["DeviceCMYK"]
        self.graphicstate.ncolor = self.graphicstate.ncs.make_color(c, m, y, k)

    def do_SCN(self) -> None:
        """Set color for stroking operators."""
        if self.graphicstate.scs is None:
            log.warning("No colorspace specified, using default DeviceGray")
            self.graphicstate.scs = self.csmap["DeviceGray"]
        self.graphicstate.scolor = self.graphicstate.scs.make_color(
            *self.pop(self.graphicstate.scs.ncomponents)
        )

    def do_scn(self) -> None:
        """Set color for nonstroking operators"""
        if self.graphicstate.ncs is None:
            log.warning("No colorspace specified, using default DeviceGray")
            self.graphicstate.ncs = self.csmap["DeviceGray"]
        self.graphicstate.ncolor = self.graphicstate.ncs.make_color(
            *self.pop(self.graphicstate.ncs.ncomponents)
        )

    def do_SC(self) -> None:
        """Set color for stroking operators"""
        self.do_SCN()

    def do_sc(self) -> None:
        """Set color for nonstroking operators"""
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

    def do_ET(self) -> Union[None, Iterator]:
        """End a text object"""
        return None

    def do_BX(self) -> None:
        """Begin compatibility section"""

    def do_EX(self) -> None:
        """End compatibility section"""

    def do_Tc(self, space: PDFObject) -> None:
        """Set character spacing.

        Character spacing is used by the Tj, TJ, and ' operators.

        :param space: a number expressed in unscaled text space units.
        """
        self.textstate.charspace = num_value(space)

    def do_Tw(self, space: PDFObject) -> None:
        """Set the word spacing.

        Word spacing is used by the Tj, TJ, and ' operators.

        :param space: a number expressed in unscaled text space units
        """
        self.textstate.wordspace = num_value(space)

    def do_Tz(self, scale: PDFObject) -> None:
        """Set the horizontal scaling.

        :param scale: is a number specifying the percentage of the normal width
        """
        self.textstate.scaling = num_value(scale)

    def do_TL(self, leading: PDFObject) -> None:
        """Set the text leading.

        Text leading is used only by the T*, ', and " operators.

        :param leading: a number expressed in unscaled text space units
        """
        self.textstate.leading = num_value(leading)

    def do_Tf(self, fontid: PDFObject, fontsize: PDFObject) -> None:
        """Set the text font

        :param fontid: the name of a font resource in the Font subdictionary
            of the current resource dictionary
        :param fontsize: size is a number representing a scale factor.
        """
        try:
            self.textstate.font = self.fontmap[literal_name(fontid)]
        except KeyError:
            log.warning("Undefined Font id: %r", fontid)
            doc = self.page.doc()
            if doc is None:
                raise RuntimeError("Document no longer exists!")
            self.textstate.font = doc.get_font(None, {})
        self.textstate.fontsize = num_value(fontsize)

    def do_Tr(self, render: PDFObject) -> None:
        """Set the text rendering mode"""
        self.textstate.render_mode = int_value(render)

    def do_Ts(self, rise: PDFObject) -> None:
        """Set the text rise

        :param rise: a number expressed in unscaled text space units
        """
        self.textstate.rise = num_value(rise)

    def do_Td(self, tx: PDFObject, ty: PDFObject) -> None:
        """Move to the start of the next line

        Offset from the start of the current line by (tx , ty).
        """
        try:
            tx = num_value(tx)
            ty = num_value(ty)
            (a, b, c, d, e, f) = self.textstate.line_matrix
            e_new = tx * a + ty * c + e
            f_new = tx * b + ty * d + f
            self.textstate.line_matrix = (a, b, c, d, e_new, f_new)
        except TypeError:
            log.warning("Invalid offset (%r, %r) for Td", tx, ty)
        self.textstate.glyph_offset = (0, 0)

    def do_TD(self, tx: PDFObject, ty: PDFObject) -> None:
        """Move to the start of the next line.

        offset from the start of the current line by (tx , ty). As a side effect, this
        operator sets the leading parameter in the text state.
        """
        try:
            tx = num_value(tx)
            ty = num_value(ty)
            (a, b, c, d, e, f) = self.textstate.line_matrix
            e_new = tx * a + ty * c + e
            f_new = tx * b + ty * d + f
            self.textstate.line_matrix = (a, b, c, d, e_new, f_new)
            if ty is not None:
                self.textstate.leading = -ty
        except TypeError:
            log.warning("Invalid offset (%r, %r) for TD", tx, ty)
        self.textstate.glyph_offset = (0, 0)

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
        self.textstate.line_matrix = cast(Matrix, (a, b, c, d, e, f))
        self.textstate.glyph_offset = (0, 0)

    def do_T_a(self) -> None:
        """Move to start of next text line"""
        (a, b, c, d, e, f) = self.textstate.line_matrix
        self.textstate.line_matrix = (
            a,
            b,
            c,
            d,
            -self.textstate.leading * c + e,
            -self.textstate.leading * d + f,
        )
        self.textstate.glyph_offset = (0, 0)

    def do_BI(self) -> None:
        """Begin inline image object"""

    def do_ID(self) -> None:
        """Begin inline image data"""

    def do_BMC(self, tag: PDFObject) -> None:
        """Begin marked-content sequence"""
        self.begin_tag(tag, {})

    def get_property(self, prop: PSLiteral) -> Union[Dict, None]:
        if "Properties" in self.resources:
            props = dict_value(self.resources["Properties"])
            return dict_value(props.get(prop.name))
        return None

    def do_BDC(self, tag: PDFObject, props: PDFObject) -> None:
        """Begin marked-content sequence with property list"""
        # PDF 1.7 sec 14.6.2: If any of the values are indirect
        # references to objects outside the content stream, the
        # property list dictionary shall be defined as a named
        # resource in the Properties subdictionary of the current
        # resource dictionary (see 7.8.3, “Resource Dictionaries”) and
        # referenced by name as the properties operand of the DP or
        # BDC operat

        if not isinstance(tag, PSLiteral):
            log.warning("Tag %r is not a name object, ignoring", tag)
            return
        if isinstance(props, PSLiteral):
            propdict = self.get_property(props)
            if propdict is None:
                log.warning("Missing property list in tag %r: %r", tag, props)
                propdict = {}
        else:
            propdict = dict_value(props)
        self.begin_tag(tag, propdict)

    def do_EMC(self) -> None:
        """End marked-content sequence"""
        self.mcs = None

    def begin_tag(self, tag: PDFObject, props: Dict[str, PDFObject]) -> None:
        """Handle beginning of tag, setting current MCID if any."""
        assert isinstance(tag, PSLiteral)
        tag = decode_text(tag.name)
        if "MCID" in props:
            mcid = int_value(props["MCID"])
        else:
            mcid = None
        self.mcs = MarkedContent(mcid=mcid, tag=tag, props=props)


class PageInterpreter(BaseInterpreter):
    """Processor for the content of a PDF page

    Reference: PDF Reference, Appendix A, Operator Summary
    """

    def __iter__(self) -> Iterator[LayoutDict]:
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

    def do_S(self) -> Iterator[LayoutDict]:
        """Stroke path"""
        yield from self.paint_path(
            stroke=True, fill=False, evenodd=False, path=self.curpath
        )
        self.curpath = []

    def do_s(self) -> Iterator[LayoutDict]:
        """Close and stroke path"""
        self.do_h()
        yield from self.do_S()

    def do_f(self) -> Iterator[LayoutDict]:
        """Fill path using nonzero winding number rule"""
        yield from self.paint_path(
            stroke=False, fill=True, evenodd=False, path=self.curpath
        )
        self.curpath = []

    def do_F(self) -> Iterator[LayoutDict]:
        """Fill path using nonzero winding number rule (obsolete)"""
        yield from self.do_f()

    def do_f_a(self) -> Iterator[LayoutDict]:
        """Fill path using even-odd rule"""
        yield from self.paint_path(
            stroke=False, fill=True, evenodd=True, path=self.curpath
        )
        self.curpath = []

    def do_B(self) -> Iterator[LayoutDict]:
        """Fill and stroke path using nonzero winding number rule"""
        yield from self.paint_path(
            stroke=True, fill=True, evenodd=False, path=self.curpath
        )
        self.curpath = []

    def do_B_a(self) -> Iterator[LayoutDict]:
        """Fill and stroke path using even-odd rule"""
        yield from self.paint_path(
            stroke=True, fill=True, evenodd=True, path=self.curpath
        )
        self.curpath = []

    def do_b(self) -> Iterator[LayoutDict]:
        """Close, fill, and stroke path using nonzero winding number rule"""
        self.do_h()
        yield from self.do_B()

    def do_b_a(self) -> Iterator[LayoutDict]:
        """Close, fill, and stroke path using even-odd rule"""
        self.do_h()
        yield from self.do_B_a()

    def do_TJ(self, seq: PDFObject) -> Iterator[LayoutDict]:
        """Show text, allowing individual glyph positioning"""
        if self.textstate.font is None:
            log.warning("No font specified in text state!")
            return
        yield from self.render_string(
            cast(TextSeq, seq),
        )

    def do_Tj(self, s: PDFObject) -> Iterator[LayoutDict]:
        """Show text"""
        yield from self.do_TJ([s])

    def do__q(self, s: PDFObject) -> Iterator[LayoutDict]:
        """Move to next line and show text

        The ' (single quote) operator.
        """
        self.do_T_a()
        yield from self.do_TJ([s])

    def do__w(self, aw: PDFObject, ac: PDFObject, s: PDFObject) -> Iterator[LayoutDict]:
        """Set word and character spacing, move to next line, and show text

        The " (double quote) operator.
        """
        self.do_Tw(aw)
        self.do_Tc(ac)
        yield from self.do_TJ([s])

    def do_EI(self, obj: PDFObject) -> Iterator[LayoutDict]:
        """End inline image object"""
        if isinstance(obj, InlineImage):
            # Inline images obviously are not indirect objects, so
            # have no object ID, so... make something up?
            iobjid = "inline_image_%d" % id(obj)
            yield self.render_image(iobjid, obj)
        else:
            # FIXME: Do... something?
            pass

    def do_Do(self, xobjid_arg: PDFObject) -> Iterator[LayoutDict]:
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
            for obj in interpreter:
                if obj.get("xobjid") is None:
                    obj["xobjid"] = xobjid
                yield obj
        elif subtype is LITERAL_IMAGE and "Width" in xobj and "Height" in xobj:
            yield self.render_image(xobjid, xobj)
        else:
            # unsupported xobject type.
            pass

    def do_MP(self, tag: PDFObject) -> None:
        """Define marked-content point"""
        pass

    def do_DP(self, tag: PDFObject, props: PDFObject) -> None:
        """Define marked-content point with property list"""
        pass

    def render_image(self, xobjid: str, stream: ContentStream) -> LayoutDict:
        # PDF 1.7 sec 8.6.3: Outside a content stream, certain
        # objects, such as image XObjects, shall specify a colour
        # space as an explicit parameter, often associated with the
        # key ColorSpace. In this case, the colour space array or name
        # shall always be defined directly as a PDF object.
        colorspace = stream.get_any(("CS", "ColorSpace"))
        colorspace = (
            None if colorspace is None else get_colorspace(resolve1(colorspace))
        )
        # PDF 1.7 sec 8.3.24: All images shall be 1 unit wide by 1
        # unit high in user space, regardless of the number of samples
        # in the image. To be painted, an image shall be mapped to a
        # region of the page by temporarily altering the CTM.
        x0, y0, x1, y1 = get_transformed_bound(self.ctm, (0, 0, 1, 1))
        if stream.objid is not None and stream.genno is not None:
            stream_id = (stream.objid, stream.genno)
        else:
            stream_id = None
        return LayoutDict(
            object_type="image",
            x0=x0,
            y0=y0,
            x1=x1,
            y1=y1,
            xobjid=xobjid,
            mcid=None if self.mcs is None else self.mcs.mcid,
            tag=None if self.mcs is None else self.mcs.tag,
            srcsize=(stream.get_any(("W", "Width")), stream.get_any(("H", "Height"))),
            imagemask=stream.get_any(("IM", "ImageMask")),
            bits=stream.get_any(("BPC", "BitsPerComponent"), 1),
            # PDF 1.7 Tabe 89: Required for images, except those that
            # use the JPXDecode filter; not allowed forbidden for
            # image masks.
            image_colorspace=colorspace,
            stream=stream_id,
        )

    def make_path(
        self,
        *,
        object_type: str,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        path_ops: str,
        pts: List[Point],
        stroke: bool,
        fill: bool,
        evenodd: bool,
    ) -> LayoutDict:
        """Make a `LayoutDict` for a path."""
        gstate = self.graphicstate
        return LayoutDict(
            object_type=object_type,
            x0=x0,
            y0=y0,
            x1=x1,
            y1=y1,
            mcid=None if self.mcs is None else self.mcs.mcid,
            tag=None if self.mcs is None else self.mcs.tag,
            path_ops=path_ops,
            pts_x=[x for x, y in pts],
            pts_y=[y for x, y in pts],
            stroke=stroke,
            fill=fill,
            evenodd=evenodd,
            linewidth=gstate.linewidth,
            dash_pattern=gstate.dash.dash,
            dash_phase=gstate.dash.phase,
            stroking_colorspace=str(gstate.scs),
            stroking_color=gstate.scolor.values,
            stroking_pattern=gstate.scolor.pattern,
            non_stroking_colorspace=str(gstate.ncs),
            non_stroking_color=gstate.ncolor.values,
            non_stroking_pattern=gstate.ncolor.pattern,
        )

    def paint_path(
        self,
        *,
        stroke: bool,
        fill: bool,
        evenodd: bool,
        path: Sequence[PathSegment],
    ) -> Iterator[LayoutDict]:
        """Paint paths described in section 4.4 of the PDF reference manual"""
        shape = "".join(x[0] for x in path)

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
                path[0].points[-1] if p[0] == "h" else p.points[-1] for p in path
            ]
            pts = [apply_matrix_pt(self.ctm, pt) for pt in raw_pts]

            # Drop a redundant "l" on a path closed with "h"
            if len(shape) > 3 and shape[-2:] == "lh" and pts[-2] == pts[0]:
                shape = shape[:-2] + "h"
                pts.pop()
            if shape in {"mlh", "ml"}:
                # single line segment ("ml" is a frequent anomaly)
                (x0, y0), (x1, y1) = pts[0:2]
                if x0 > x1:
                    (x1, x0) = (x0, x1)
                if y0 > y1:
                    (y1, y0) = (y0, y1)
                yield self.make_path(
                    object_type="line",
                    x0=x0,
                    y0=y0,
                    x1=x1,
                    y1=y1,
                    path_ops=shape,
                    pts=pts,
                    stroke=stroke,
                    fill=fill,
                    evenodd=evenodd,
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
                    yield self.make_path(
                        object_type="rect",
                        x0=x0,
                        y0=y0,
                        x1=x2,
                        y1=y2,
                        path_ops=shape,
                        pts=pts,
                        stroke=stroke,
                        fill=fill,
                        evenodd=evenodd,
                    )
                else:
                    x0, y0, x1, y1 = get_bound(pts)
                    yield self.make_path(
                        object_type="curve",
                        x0=x0,
                        y0=y0,
                        x1=x1,
                        y1=y1,
                        path_ops=shape,
                        pts=pts,
                        stroke=stroke,
                        fill=fill,
                        evenodd=evenodd,
                    )
            else:
                x0, y0, x1, y1 = get_bound(pts)
                yield self.make_path(
                    object_type="curve",
                    x0=x0,
                    y0=y0,
                    x1=x1,
                    y1=y1,
                    path_ops=shape,
                    pts=pts,
                    stroke=stroke,
                    fill=fill,
                    evenodd=evenodd,
                )

    def render_char(
        self,
        *,
        cid: int,
        matrix: Matrix,
        scaling: float,
    ) -> Tuple[LayoutDict, float]:
        font = self.textstate.font
        assert font is not None
        fontsize = self.textstate.fontsize
        rise = self.textstate.rise
        try:
            text = font.to_unichr(cid)
            assert isinstance(text, str), f"Text {text!r} is not a str"
        except PDFUnicodeNotDefined:
            log.debug("undefined char: %r, %r", font, cid)
            text = None
        textwidth = font.char_width(cid)
        adv = textwidth * fontsize * scaling
        if font.vertical:
            textdisp = font.char_disp(cid)
            assert isinstance(textdisp, tuple)
            (vx, vy) = textdisp
            if vx is None:
                vx = fontsize * 0.5
            else:
                vx = vx * fontsize * 0.001
            vy = (1000 - vy) * fontsize * 0.001
            x0, y0 = (-vx, vy + rise + adv)
            x1, y1 = (-vx + fontsize, vy + rise)
        else:
            descent = font.get_descent() * fontsize
            x0, y0 = (0, descent + rise)
            x1, y1 = (adv, descent + rise + fontsize)
        (a, b, c, d, e, f) = matrix
        upright = a * d * scaling > 0 and b * c <= 0
        x0, y0, x1, y1 = get_transformed_bound(matrix, (x0, y0, x1, y1))
        # NOTE: This is not right at all for rotated text, but we'll live with it
        if font.vertical:
            size = x1 - x0
        else:
            size = y1 - y0
        glyph_x, glyph_y = apply_matrix_norm(self.ctm, self.textstate.glyph_offset)
        item = LayoutDict(
            object_type="char",
            x0=x0,
            y0=y0,
            x1=x1,
            y1=y1,
            size=size,
            upright=upright,
            text=text,
            cid=cid,
            fontname=font.fontname,
            glyph_offset_x=glyph_x,
            glyph_offset_y=glyph_y,
            render_mode=self.textstate.render_mode,
            dash_pattern=self.graphicstate.dash.dash,
            dash_phase=self.graphicstate.dash.phase,
            stroking_colorspace=str(self.graphicstate.scs),
            stroking_color=self.graphicstate.scolor.values,
            stroking_pattern=self.graphicstate.scolor.pattern,
            non_stroking_colorspace=str(self.graphicstate.ncs),
            non_stroking_color=self.graphicstate.ncolor.values,
            non_stroking_pattern=self.graphicstate.ncolor.pattern,
            mcid=None if self.mcs is None else self.mcs.mcid,
            tag=None if self.mcs is None else self.mcs.tag,
        )
        return item, adv

    def render_string(
        self,
        seq: TextSeq,
    ) -> Iterator[LayoutDict]:
        assert self.textstate.font is not None
        vert = self.textstate.font.vertical
        assert self.ctm is not None
        matrix = mult_matrix(self.textstate.line_matrix, self.ctm)
        scaling = self.textstate.scaling * 0.01
        charspace = self.textstate.charspace * scaling
        wordspace = self.textstate.wordspace * scaling
        if self.textstate.font.multibyte:
            wordspace = 0
        (x, y) = self.textstate.glyph_offset
        pos = y if vert else x
        needcharspace = False
        dxscale = 0.001 * self.textstate.fontsize * scaling
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
                    self.textstate.glyph_offset = (x, pos) if vert else (pos, y)
                    item, adv = self.render_char(
                        cid=cid,
                        matrix=translate_matrix(matrix, self.textstate.glyph_offset),
                        scaling=scaling,
                    )
                    pos += adv
                    yield item
                    if cid == 32 and wordspace:
                        pos += wordspace
                    needcharspace = True
        self.textstate.glyph_offset = (x, pos) if vert else (pos, y)


@dataclass
class ContentObject:
    """Any sort of content object.

    Attributes:
      gstate: Graphics state.
      ctm: Coordinate transformation matrix (PDF 1.7 section 8.3.2).
      mcs: Marked content (point or section).
    """

    gstate: GraphicState
    ctm: Matrix
    mcs: Union[MarkedContent, None]

    def __iter__(self) -> Iterator["ContentObject"]:
        yield from ()

    @property
    def object_type(self):
        """Type of this object as a string, e.g. "text", "path", "image"."""
        name = self.__class__.__name__
        return name[: -len("Object")].lower()

    @property
    def bbox(self) -> Rect:
        points = itertools.chain.from_iterable(
            ((x0, y0), (x0, y1), (x1, y1), (x1, y0))
            for x0, y0, x1, y1 in (item.bbox for item in self)
        )
        return get_bound(points)


@dataclass
class TagObject(ContentObject):
    """A marked content point with no content."""


@dataclass
class ImageObject(ContentObject):
    """An image (either inline or XObject).

    Attributes:
      xobjid: Name of XObject (or None for inline images).
      srcsize: Size of source image in pixels.
      bits: Number of bits per component, if required (otherwise 1).
      imagemask: True if the image is a mask.
      stream: Content stream with image data.
      colorspace: Colour space for this image, if required (otherwise
        None).
    """

    xobjid: Union[str, None]
    srcsize: Tuple[int, int]
    bits: int
    imagemask: bool
    stream: ContentStream
    colorspace: Union[ColorSpace, None]

    def __contains__(self, name: object) -> bool:
        return name in self.stream

    def __getitem__(self, name: str) -> PDFObject:
        return self.stream[name]

    @property
    def buffer(self) -> bytes:
        """Binary stream content for this image"""
        return self.stream.buffer

    @property
    def bbox(self) -> Rect:
        # PDF 1.7 sec 8.3.24: All images shall be 1 unit wide by 1
        # unit high in user space, regardless of the number of samples
        # in the image. To be painted, an image shall be mapped to a
        # region of the page by temporarily altering the CTM.
        return get_transformed_bound(self.ctm, (0, 0, 1, 1))


@dataclass
class XObjectObject(ContentObject):
    """An eXternal Object, in the context of a page.

    There are a couple of kinds of XObjects.  Here we are only
    concerned with "Form XObjects" which, despite their name, have
    nothing at all to do with fillable forms.  Instead they are like
    little embeddable PDF pages, possibly with their own resources,
    definitely with their own definition of "user space".

    Image XObjects are handled by `ImageObject`.

    Attributes:
      xobjid: Name of this XObject (in the page resources).
      page: Weak reference to containing page.
      stream: Content stream with PDF operators.
      resources: Resources specific to this XObject, if any.
    """

    xobjid: str
    page: weakref.ReferenceType
    stream: ContentStream
    resources: Union[None, Dict[str, PDFObject]]

    def __contains__(self, name: object) -> bool:
        return name in self.stream

    def __getitem__(self, name: str) -> PDFObject:
        return self.stream[name]

    @property
    def bbox(self) -> Rect:
        """Get the bounding box of this XObject in device space."""
        # It is a required attribute!
        return get_transformed_bound(self.ctm, parse_rect(self.stream["BBox"]))

    @property
    def buffer(self) -> bytes:
        """Raw stream content for this XObject"""
        return self.stream.buffer

    @property
    def tokens(self) -> Iterator[Token]:
        """Iterate over tokens in the XObject's content stream."""
        parser = ContentParser([self.stream])
        while True:
            try:
                pos, tok = parser.nexttoken()
            except StopIteration:
                return
            yield tok

    @property
    def layout(self) -> Iterator["LayoutDict"]:
        """Iterator over eager layout object dictionaries."""
        page = self.page()
        if page is None:
            raise RuntimeError("Page no longer exists!")
        return iter(PageInterpreter(page, [self.stream], self.resources))

    @property
    def contents(self) -> Iterator[PDFObject]:
        """Iterator over PDF objects in the content stream."""
        page = self.page()
        if page is None:
            raise RuntimeError("Page no longer exists!")
        for pos, obj in ContentParser([self.stream]):
            yield obj

    def __iter__(self) -> Iterator["ContentObject"]:
        page = self.page()
        if page is None:
            raise RuntimeError("Page no longer exists!")
        return iter(LazyInterpreter(page, [self.stream], self.resources))


@dataclass
class PathObject(ContentObject):
    """A path object.

    Attributes:
      raw_segments: Segments in path (in user space).
      stroke: True if the outline of the path is stroked.
      fill: True if the path is filled.
      evenodd: True if the filling of complex paths uses the even-odd
        winding rule, False if the non-zero winding number rule is
        used (PDF 1.7 section 8.5.3.3)
    """

    raw_segments: List[PathSegment]
    stroke: bool
    fill: bool
    evenodd: bool

    def __len__(self):
        """Number of subpaths."""
        return min(1, sum(1 for seg in self.raw_segments if seg.operator == "m"))

    def __iter__(self):
        """Iterate over subpaths.

        Note: subpaths inherit the values of `fill` and `evenodd` from
        the parent path, but these values are no longer meaningful
        since the winding rules must be applied to the composite path
        as a whole (this is not a bug, just don't rely on them to know
        which regions are filled or not).
        """
        # FIXME: Is there an itertool or a more_itertool for this?
        segs = []
        for seg in self.raw_segments:
            if seg.operator == "m" and segs:
                yield PathObject(
                    self.gstate,
                    self.ctm,
                    self.mcs,
                    segs,
                    self.stroke,
                    self.fill,
                    self.evenodd,
                )
            segs.append(seg)
        if segs:
            yield PathObject(
                self.gstate,
                self.ctm,
                self.mcs,
                segs,
                self.stroke,
                self.fill,
                self.evenodd,
            )

    @property
    def segments(self) -> Iterator[PathSegment]:
        """Get path segments in device space."""
        return (
            PathSegment(
                p.operator,
                tuple(apply_matrix_pt(self.ctm, point) for point in p.points),
            )
            for p in self.raw_segments
        )

    @property
    def bbox(self) -> Rect:
        """Get bounding box of path in device space as defined by its
        points and control points."""
        # First get the bounding box in user space (fast)
        bbox = get_bound(
            itertools.chain.from_iterable(seg.points for seg in self.raw_segments)
        )
        # Transform it and get the new bounding box
        return get_transformed_bound(self.ctm, bbox)


class TextItem(NamedTuple):
    """Semi-parsed item in a text object.  Actual "rendering" is
    deferred, just like with paths.

    Attributes:
      operator: Text operator for this item. Many operators simply
        modify the `TextState` and do not actually output any text.
      args: Arguments for the operator.
    """

    operator: TextOperator
    args: Tuple[TextArgument, ...]


def make_txt(operator: TextOperator, *args: TextArgument) -> TextItem:
    return TextItem(operator, args)


@dataclass
class GlyphObject(ContentObject):
    """Individual glyph on the page.

    Attributes:
      textstate: Text state for this glyph.  This is a **mutable**
        object and you should not expect it to be valid outside the
        context of iteration over the parent `TextObject`.
      cid: Character ID for this glyph.
      text: Unicode mapping of this glyph, if any.
      adv: glyph displacement in user space units.
      bbox: glyph bounding box in device space.
    """

    textstate: TextState
    cid: int
    text: Union[str, None]
    adv: float
    _bbox: Rect

    @property
    def bbox(self) -> Rect:
        return self._bbox


@dataclass
class TextObject(ContentObject):
    """Text object (contains one or more glyphs).

    Attributes:
      textstate: Text state for this object.  This is a **mutable**
        object and you should not expect it to be valid outside the
        context of iteration over the parent `TextObject`.
      items: Raw text items (strings and operators) for this object.
    """

    textstate: TextState
    items: List[TextItem]
    _glyphs: Union[List[GlyphObject], None] = None
    _chars: Union[List[str], None] = None

    def _render_char(
        self,
        *,
        cid: int,
        matrix: Matrix,
        scaling: float,
    ) -> GlyphObject:
        font = self.textstate.font
        assert font is not None
        fontsize = self.textstate.fontsize
        rise = self.textstate.rise
        try:
            text = font.to_unichr(cid)
            assert isinstance(text, str), f"Text {text!r} is not a str"
        except PDFUnicodeNotDefined:
            log.debug("undefined char: %r, %r", font, cid)
            text = None
        textwidth = font.char_width(cid)
        adv = textwidth * fontsize * scaling
        if font.vertical:
            textdisp = font.char_disp(cid)
            assert isinstance(textdisp, tuple)
            (vx, vy) = textdisp
            if vx is None:
                vx = fontsize * 0.5
            else:
                vx = vx * fontsize * 0.001
            vy = (1000 - vy) * fontsize * 0.001
            x0, y0 = (-vx, vy + rise + adv)
            x1, y1 = (-vx + fontsize, vy + rise)
        else:
            descent = font.get_descent() * fontsize
            x0, y0 = (0, descent + rise)
            x1, y1 = (adv, descent + rise + fontsize)
        bbox = get_transformed_bound(matrix, (x0, y0, x1, y1))
        return GlyphObject(
            self.gstate,
            self.ctm,
            self.mcs,
            self.textstate,
            cid,
            text,
            adv,
            bbox
        )

    def _render_string(self, item: TextItem) -> Iterator[GlyphObject]:
        assert self.textstate.font is not None
        vert = self.textstate.font.vertical
        assert self.ctm is not None
        matrix = mult_matrix(self.textstate.line_matrix, self.ctm)
        scaling = self.textstate.scaling * 0.01
        charspace = self.textstate.charspace * scaling
        wordspace = self.textstate.wordspace * scaling
        if self.textstate.font.multibyte:
            wordspace = 0
        (x, y) = self.textstate.glyph_offset
        pos = y if vert else x
        needcharspace = False
        dxscale = 0.001 * self.textstate.fontsize * scaling
        for obj in item.args:
            if isinstance(obj, (int, float)):
                pos -= obj * dxscale
                needcharspace = True
            else:
                if not isinstance(obj, bytes):
                    log.warning("Found non-string %r in text object", obj)
                    continue
                for cid in self.textstate.font.decode(obj):
                    if needcharspace:
                        pos += charspace
                    self.textstate.glyph_offset = (x, pos) if vert else (pos, y)
                    glyph = self._render_char(
                        cid=cid,
                        matrix=translate_matrix(matrix, self.textstate.glyph_offset),
                        scaling=scaling,
                    )
                    pos += glyph.adv
                    yield glyph
                    if cid == 32 and wordspace:
                        pos += wordspace
                    needcharspace = True
        self.textstate.glyph_offset = (x, pos) if vert else (pos, y)

    @property
    def chars(self) -> str:
        """Get the Unicode characters (in stream order) for this object."""
        if self._chars is not None:
            return "".join(self._chars)
        self._chars = []
        for item in self.items:
            # Only TJ and Tf are relevant to Unicode output
            if item.operator == "TJ":
                font = self.textstate.font
                assert font is not None, "No font was selected"
                for obj in item.args:
                    if not isinstance(obj, bytes):
                        continue
                    for cid in font.decode(obj):
                        try:
                            text = font.to_unichr(cid)
                            assert isinstance(text, str), f"Text {text!r} is not a str"
                            self._chars.append(text)
                        except PDFUnicodeNotDefined:
                            log.debug("undefined char: %r, %r", font, cid)
            elif item.operator == "Tf":
                self.textstate.update(item.operator, *item.args)
        return "".join(self._chars)

    def __iter__(self) -> Iterator[GlyphObject]:
        """Generate glyphs for this text object"""
        for item in self.items:
            if item.operator == "TJ":
                for glyph in self._render_string(item):
                    yield glyph
            else:
                self.textstate.update(item.operator, *item.args)


class LazyInterpreter(BaseInterpreter):
    """Interpret the page yielding lazy objects."""

    textobj: List[TextItem] = []

    def __iter__(self) -> Iterator[ContentObject]:
        log.debug(
            "LazyInterpreter: resources=%r, streams=%r, ctm=%r",
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

    def create(self, object_class, **kwargs) -> ContentObject:
        return object_class(
            ctm=self.ctm,
            mcs=self.mcs,
            gstate=self.graphicstate,
            **kwargs,
        )

    def do_S(self) -> Iterator[ContentObject]:
        """Stroke path"""
        yield self.create(
            PathObject,
            stroke=True,
            fill=False,
            evenodd=False,
            raw_segments=self.curpath,
        )
        self.curpath = []

    def do_s(self) -> Iterator[ContentObject]:
        """Close and stroke path"""
        self.do_h()
        yield from self.do_S()

    def do_f(self) -> Iterator[ContentObject]:
        """Fill path using nonzero winding number rule"""
        yield self.create(
            PathObject,
            stroke=False,
            fill=True,
            evenodd=False,
            raw_segments=self.curpath,
        )
        self.curpath = []

    def do_F(self) -> Iterator[ContentObject]:
        """Fill path using nonzero winding number rule (obsolete)"""
        yield from self.do_f()

    def do_f_a(self) -> Iterator[ContentObject]:
        """Fill path using even-odd rule"""
        yield self.create(
            PathObject,
            stroke=False,
            fill=True,
            evenodd=True,
            raw_segments=self.curpath,
        )
        self.curpath = []

    def do_B(self) -> Iterator[ContentObject]:
        """Fill and stroke path using nonzero winding number rule"""
        yield self.create(
            PathObject,
            stroke=True,
            fill=True,
            evenodd=False,
            raw_segments=self.curpath,
        )
        self.curpath = []

    def do_B_a(self) -> Iterator[ContentObject]:
        """Fill and stroke path using even-odd rule"""
        yield self.create(
            PathObject,
            stroke=True,
            fill=True,
            evenodd=True,
            raw_segments=self.curpath,
        )
        self.curpath = []

    def do_b(self) -> Iterator[ContentObject]:
        """Close, fill, and stroke path using nonzero winding number rule"""
        self.do_h()
        yield from self.do_B()

    def do_b_a(self) -> Iterator[ContentObject]:
        """Close, fill, and stroke path using even-odd rule"""
        self.do_h()
        yield from self.do_B_a()

    # PDF 1.7 sec 9.3.1: The text state operators may appear outside
    # text objects, and the values they set are retained across text
    # objects in a single content stream. Like other graphics state
    # parameters, these parameters shall be initialized to their
    # default values at the beginning of each page.
    #
    # Concretely, this means that we simply have to execute anything
    # in self.textobj when we see BT.
    #
    # FIXME: It appears that we're supposed to reset it between content
    # streams?! That seems very bogus, pdfminer does not do it.
    def do_BT(self) -> None:
        """Update text state and begin text object.

        All operators until ET will be normalized, but executed lazily.
        """
        for item in self.textobj:
            self.textstate.update(item.operator, *item.args)
        self.textobj = []

    def do_ET(self) -> Iterator[ContentObject]:
        """End a text object"""
        # Only output text if... there is text to output (we rewrite all text operators to TJ)
        has_text = False
        for item in self.textobj:
            if item.operator == "TJ":
                has_text = True
        if has_text:
            yield self.create(TextObject, textstate=self.textstate, items=self.textobj)
        else:
            for item in self.textobj:
                self.textstate.update(item.operator, *item.args)

    def do_Tc(self, space: PDFObject) -> None:
        """Set character spacing.

        Character spacing is used by the Tj, TJ, and ' operators.

        :param space: a number expressed in unscaled text space units.
        """
        self.textobj.append(make_txt("Tc", num_value(space)))

    def do_Tw(self, space: PDFObject) -> None:
        """Set the word spacing.

        Word spacing is used by the Tj, TJ, and ' operators.

        :param space: a number expressed in unscaled text space units
        """
        self.textobj.append(make_txt("Tw", num_value(space)))

    def do_Tz(self, scale: PDFObject) -> None:
        """Set the horizontal scaling.

        :param scale: is a number specifying the percentage of the normal width
        """
        self.textobj.append(make_txt("Tz", num_value(scale)))

    def do_TL(self, leading: PDFObject) -> None:
        """Set the text leading.

        Text leading is used only by the T*, ', and " operators.

        :param leading: a number expressed in unscaled text space units
        """
        self.textobj.append(make_txt("TL", num_value(leading)))

    def do_Tf(self, fontid: PDFObject, fontsize: PDFObject) -> None:
        """Set the text font

        :param fontid: the name of a font resource in the Font subdictionary
            of the current resource dictionary
        :param fontsize: size is a number representing a scale factor.
        """
        try:
            font = self.fontmap[literal_name(fontid)]
        except KeyError:
            log.warning("Undefined Font id: %r", fontid)
            doc = self.page.doc()
            if doc is None:
                raise RuntimeError("Document no longer exists!")
            # FIXME: as in document.py, "this is so wrong!"
            font = doc.get_font(None, {})
        self.textobj.append(make_txt("Tf", font, num_value(fontsize)))

    def do_Tr(self, render: PDFObject) -> None:
        """Set the text rendering mode"""
        self.textobj.append(make_txt("Tr", int_value(render)))

    def do_Ts(self, rise: PDFObject) -> None:
        """Set the text rise

        :param rise: a number expressed in unscaled text space units
        """
        self.textobj.append(make_txt("Ts", num_value(rise)))

    def do_Td(self, tx: PDFObject, ty: PDFObject) -> None:
        """Move to the start of the next line

        Offset from the start of the current line by (tx , ty).
        """
        self.textobj.append(make_txt("Td", num_value(tx), num_value(ty)))

    def do_TD(self, tx: PDFObject, ty: PDFObject) -> None:
        """Move to the start of the next line.

        offset from the start of the current line by (tx , ty). As a side effect, this
        operator sets the leading parameter in the text state.

        (PDF 1.7 Table 108) This operator shall have the same effect as this code:
            −ty TL
            tx ty Td
        """
        self.textobj.append(make_txt("TL", -num_value(ty)))
        self.textobj.append(make_txt("Td", num_value(tx), num_value(ty)))

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
        self.textobj.append(
            make_txt(
                "Tm",
                num_value(a),
                num_value(b),
                num_value(c),
                num_value(d),
                num_value(e),
                num_value(f),
            )
        )

    def do_T_a(self) -> None:
        """Move to start of next text line"""
        self.textobj.append(make_txt("T*"))

    def do_TJ(self, strings: PDFObject) -> None:
        """Show one or more text strings, allowing individual glyph
        positioning"""
        args = list_value(strings)
        if not all(isinstance(s, (int, float, bytes)) for s in args):
            raise TypeError("TJ takes only strings and numbers, not %r" % args)
        self.textobj.append(make_txt("TJ", *args))

    def do_Tj(self, s: PDFObject) -> None:
        """Show a text string"""
        self.do_TJ([s])

    def do__q(self, s: PDFObject) -> None:
        """Move to next line and show text

        The ' (single quote) operator.
        """
        self.do_T_a()
        self.do_TJ([s])

    def do__w(self, aw: PDFObject, ac: PDFObject, s: PDFObject) -> None:
        """Set word and character spacing, move to next line, and show text

        The " (double quote) operator.
        """
        self.do_Tw(aw)
        self.do_Tc(ac)
        self.do_TJ([s])

    def do_EI(self, obj: PDFObject) -> Iterator[ContentObject]:
        """End inline image object"""
        if isinstance(obj, InlineImage):
            # Inline images are not XObjects, have no xobjid
            yield self.render_image(None, obj)
        else:
            # FIXME: Do... something?
            pass

    def do_Do(self, xobjid_arg: PDFObject) -> Iterator[ContentObject]:
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
            xobjobj = XObjectObject(
                ctm=mult_matrix(matrix, self.ctm),
                mcs=self.mcs,
                gstate=self.graphicstate,
                page=weakref.ref(self.page),
                xobjid=xobjid,
                stream=xobj,
                resources=resources,
            )
            # We are *lazy*, so just yield the XObject itself not its contents
            yield xobjobj
        elif subtype is LITERAL_IMAGE and "Width" in xobj and "Height" in xobj:
            yield self.render_image(xobjid, xobj)
        else:
            # unsupported xobject type.
            pass

    def render_image(
        self, xobjid: Union[str, None], stream: ContentStream
    ) -> ContentObject:
        colorspace = stream.get_any(("CS", "ColorSpace"))
        colorspace = (
            None if colorspace is None else get_colorspace(resolve1(colorspace))
        )
        return self.create(
            ImageObject,
            stream=stream,
            xobjid=xobjid,
            srcsize=(stream.get_any(("W", "Width")), stream.get_any(("H", "Height"))),
            imagemask=stream.get_any(("IM", "ImageMask")),
            bits=stream.get_any(("BPC", "BitsPerComponent"), 1),
            colorspace=colorspace,
        )

    def do_MP(self, tag: PDFObject) -> Iterator[ContentObject]:
        """Define marked-content point"""
        yield from self.do_DP(tag, None)

    def do_DP(self, tag: PDFObject, props: PDFObject = None) -> Iterator[ContentObject]:
        """Define marked-content point with property list"""
        # See above
        if isinstance(props, PSLiteral):
            props = self.get_property(props)
        rprops = {} if props is None else dict_value(props)
        yield TagObject(
            ctm=self.ctm,
            mcs=MarkedContent(mcid=None, tag=literal_name(tag), props=rprops),
            gstate=self.graphicstate,
        )
