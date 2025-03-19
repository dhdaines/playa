"""
Classes for looking at pages and their contents.
"""

import itertools
import logging
import re
import textwrap
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
    Tuple,
    Type,
    TypeVar,
    Union,
    cast,
    overload,
)

from playa.color import (
    BASIC_BLACK,
    LITERAL_RELATIVE_COLORIMETRIC,
    PREDEFINED_COLORSPACE,
    Color,
    ColorSpace,
    get_colorspace,
)
from playa.exceptions import PDFSyntaxError
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
    decode_text,
    get_bound,
    get_transformed_bound,
    mult_matrix,
    normalize_rect,
)
from playa.worker import PageRef, _deref_document, _deref_page, _ref_document, _ref_page

if TYPE_CHECKING:
    from playa.document import Document

log = logging.getLogger(__name__)

# some predefined literals and keywords.
LITERAL_PAGE = LIT("Page")
LITERAL_PAGES = LIT("Pages")
LITERAL_FORM = LIT("Form")
LITERAL_IMAGE = LIT("Image")
TextSeq = Iterable[Union[int, float, bytes]]
DeviceSpace = Literal["page", "screen", "default", "user"]
CO = TypeVar("CO")


# FIXME: This should go in utils/pdftypes but there are circular imports
def parse_rect(o: PDFObject) -> Rect:
    try:
        (x0, y0, x1, y1) = (num_value(x) for x in list_value(o))
        return x0, y0, x1, y1
    except ValueError:
        raise ValueError("Could not parse rectangle %r" % (o,))
    except TypeError:
        raise PDFSyntaxError("Rectangle contains non-numeric values")


# FIXME: This should be a method of TextObject (soon)
def _extract_text_from_obj(obj: "TextObject", vertical: bool) -> Tuple[str, float]:
    """Try to get text from a text object."""
    chars = []
    prev_end = 0.0
    for glyph in obj:
        x, y = glyph.textstate.glyph_offset
        off = y if vertical else x
        # FIXME: This is a heuristic!!!
        if prev_end and off - prev_end > 0.5:
            chars.append(" ")
        if glyph.text is not None:
            chars.append(glyph.text)
        prev_end = off + glyph.adv
    return "".join(chars), prev_end


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
      page_idx: 0-based index of the page in the document.
      ctm: coordinate transformation matrix from default user space to
           page's device space
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
        self.docref = _ref_document(doc)
        self.pageid = pageid
        self.attrs = attrs
        self.label = label
        self.page_idx = page_idx
        self.space = space
        self.pageref = _ref_page(self)
        self.lastmod = resolve1(self.attrs.get("LastModified"))
        try:
            self.resources: Dict[str, PDFObject] = dict_value(
                self.attrs.get("Resources")
            )
        except TypeError:
            log.warning("Resources missing or invalid from Page id %d", pageid)
            self.resources = {}
        try:
            self.mediabox = normalize_rect(parse_rect(self.attrs["MediaBox"]))
        except KeyError:
            log.warning(
                "MediaBox missing from Page id %d (and not inherited),"
                " defaulting to US Letter (612x792)",
                pageid,
            )
            self.mediabox = (0, 0, 612, 792)
        except (ValueError, PDFSyntaxError):
            log.warning(
                "MediaBox %r invalid in Page id %d,"
                " defaulting to US Letter (612x792)",
                self.attrs["MediaBox"],
                pageid,
            )
            self.mediabox = (0, 0, 612, 792)
        self.cropbox = self.mediabox
        if "CropBox" in self.attrs:
            try:
                self.cropbox = normalize_rect(parse_rect(self.attrs["CropBox"]))
            except (ValueError, PDFSyntaxError):
                log.warning(
                    "Invalid CropBox %r in /Page, defaulting to MediaBox",
                    self.attrs["CropBox"],
                )

        self.rotate = (int_value(self.attrs.get("Rotate", 0)) + 360) % 360
        (x0, y0, x1, y1) = self.mediabox
        width = x1 - x0
        height = y1 - y0
        # PDF 1.7 section 8.4.1: Initial value: a matrix that
        # transforms default user coordinates to device coordinates.
        #
        # We keep this as `self.ctm` in order to transform layout
        # attributes in tagged PDFs which are specified in default
        # user space (PDF 1.7 section 14.8.5.4.3, table 344)
        #
        # "screen" device space: origin is top left of MediaBox
        if self.space == "screen":
            self.ctm = (1.0, 0.0, 0.0, -1.0, -x0, y1)
        # "page" device space: origin is bottom left of MediaBox
        elif self.space == "page":
            self.ctm = (1.0, 0.0, 0.0, 1.0, -x0, -y0)
        # "default" device space: no transformation or rotation
        else:
            if self.space != "default":
                log.warning("Unknown device space: %r", self.space)
            self.ctm = MATRIX_IDENTITY
            width = height = 0
        # If rotation is requested, apply rotation to the initial ctm
        if self.rotate == 90:
            # x' = y
            # y' = width - x
            self.ctm = mult_matrix((0, -1, 1, 0, 0, width), self.ctm)
        elif self.rotate == 180:
            # x' = width - x
            # y' = height - y
            self.ctm = mult_matrix((-1, 0, 0, -1, width, height), self.ctm)
        elif self.rotate == 270:
            # x' = height - y
            # y' = x
            self.ctm = mult_matrix((0, 1, -1, 0, height, 0), self.ctm)
        elif self.rotate != 0:
            log.warning("Invalid /Rotate: %r", self.rotate)

        contents = resolve1(self.attrs.get("Contents"))
        if contents is None:
            self._contents = []
        else:
            if isinstance(contents, list):
                self._contents = contents
            else:
                self._contents = [contents]

    @property
    def annotations(self) -> Iterator["Annotation"]:
        """Lazily iterate over page annotations."""
        alist = resolve1(self.attrs.get("Annots"))
        if alist is None:
            return
        for annot in alist:
            annot = resolve1(annot)
            if not isinstance(annot, dict):
                log.warning("Invalid object in Annots: %r", annot)
                continue
            subtype = annot.get("Subtype")
            if subtype is None or not isinstance(subtype, PSLiteral):
                log.warning("Invalid Subtype in annotation: %r", annot)
                continue
            try:
                rect = parse_rect(annot.get("Rect"))
            except (TypeError, ValueError, PDFSyntaxError):
                log.warning("Invalid Rect in annotation: %r", annot)
                continue
            yield Annotation(
                _pageref=self.pageref,
                subtype=literal_name(subtype),
                rect=rect,
                props=annot,
            )

    @property
    def doc(self) -> "Document":
        """Get associated document if it exists."""
        return _deref_document(self.docref)

    @property
    def streams(self) -> Iterator[ContentStream]:
        """Return resolved content streams."""
        for obj in self._contents:
            try:
                yield stream_value(obj)
            except TypeError:
                log.warning("Found non-stream in contents: %r", obj)

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
        return self.flatten(PathObject)

    @property
    def images(self) -> Iterator["ImageObject"]:
        """Iterator over lazy image objects."""
        return self.flatten(ImageObject)

    @property
    def texts(self) -> Iterator["TextObject"]:
        """Iterator over lazy text objects."""
        return self.flatten(TextObject)

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
        return cast(
            Iterator["XObjectObject"],
            iter(LazyInterpreter(self, self._contents, filter_class=XObjectObject)),
        )

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

    @overload
    def flatten(self) -> Iterator["ContentObject"]: ...

    @overload
    def flatten(self, filter_class: Type[CO]) -> Iterator[CO]: ...

    def flatten(
        self, filter_class: Union[None, Type[CO]] = None
    ) -> Iterator[Union[CO, "ContentObject"]]:
        """Iterate over content objects, recursing into form XObjects."""

        def flatten_one(itor: Iterable["ContentObject"]) -> Iterator["ContentObject"]:
            for obj in itor:
                if isinstance(obj, XObjectObject):
                    yield from flatten_one(obj)
                else:
                    yield obj

        if filter_class is None:
            yield from flatten_one(self)
        else:
            for obj in flatten_one(self):
                if isinstance(obj, filter_class):
                    yield obj

    def extract_text(self) -> str:
        """Do some best-effort text extraction.

        This necessarily involves a few heuristics, so don't get your
        hopes up.  It will attempt to use marked content information
        for a tagged PDF, otherwise it will fall back on the character
        displacement and line matrix to determine word and line breaks.
        """
        if self.doc.is_tagged:
            return self.extract_text_tagged()
        else:
            return self.extract_text_untagged()

    def extract_text_untagged(self) -> str:
        """Get text from a page of an untagged PDF."""
        prev_line_matrix = None
        prev_end = 0.0
        lines = []
        strings = []
        for text in self.flatten(TextObject):
            line_matrix = text.textstate.line_matrix
            vertical = (
                False if text.textstate.font is None else text.textstate.font.vertical
            )
            lpos = -2 if vertical else -1
            if (
                prev_line_matrix is not None
                and line_matrix[lpos] < prev_line_matrix[lpos]
            ):
                lines.append("".join(strings))
                strings.clear()
            wpos = -1 if vertical else -2
            if (
                prev_line_matrix is not None
                and prev_end + prev_line_matrix[wpos] < line_matrix[wpos]
            ):
                strings.append(" ")
            textstr, end = _extract_text_from_obj(text, vertical)
            strings.append(textstr)
            prev_line_matrix = line_matrix
            prev_end = end
        if strings:
            lines.append("".join(strings))
        return "\n".join(lines)

    def extract_text_tagged(self) -> str:
        """Get text from a page of a tagged PDF."""
        lines: List[str] = []
        strings: List[str] = []
        at_mcs: Union[MarkedContent, None] = None
        prev_mcid: Union[int, None] = None
        for text in self.flatten(TextObject):
            in_artifact = same_actual_text = reversed_chars = False
            actual_text = None
            for mcs in reversed(text.mcstack):
                if mcs.tag == "Artifact":
                    in_artifact = True
                    break
                actual_text = mcs.props.get("ActualText")
                if actual_text is not None:
                    if mcs is at_mcs:
                        same_actual_text = True
                    at_mcs = mcs
                    break
                if mcs.tag == "ReversedChars":
                    reversed_chars = True
                    break
            if in_artifact or same_actual_text:
                continue
            if actual_text is None:
                chars = text.chars
                if reversed_chars:
                    chars = chars[::-1]
            else:
                assert isinstance(actual_text, bytes)
                chars = actual_text.decode("UTF-16")
            # Remove soft hyphens
            chars = chars.replace("\xad", "")
            # Insert a line break (FIXME: not really correct)
            if text.mcid != prev_mcid:
                lines.extend(textwrap.wrap("".join(strings)))
                strings.clear()
                prev_mcid = text.mcid
            strings.append(chars)
        if strings:
            lines.extend(textwrap.wrap("".join(strings)))
        return "\n".join(lines)


@dataclass
class Annotation:
    """PDF annotation (PDF 1.7 section 12.5).

    Attributes:
      subtype: Type of annotation.
      rect: Annotation rectangle (location on page) in *default user space*
      bbox: Annotation rectangle in *device space*
      props: Annotation dictionary containing all other properties
             (PDF 1.7 sec. 12.5.2).
    """

    _pageref: PageRef
    subtype: str
    rect: Rect
    props: Dict[str, PDFObject]

    @property
    def page(self) -> Page:
        """Containing page for this annotation."""
        return _deref_page(self._pageref)

    @property
    def contents(self) -> Union[str, None]:
        """Text contents of annotation."""
        contents = resolve1(self.props.get("Contents"))
        if contents is None:
            return None
        try:
            return decode_text(contents)
        except TypeError:
            log.warning("Invalid annotation contents: %r", contents)
            return None

    @property
    def name(self) -> Union[str, None]:
        """Annotation name, uniquely identifying this annotation."""
        name = resolve1(self.props.get("NM"))
        if name is None:
            return None
        return decode_text(name)

    @property
    def mtime(self) -> Union[str, None]:
        """String describing date and time when annotation was most recently
        modified.

        The date *should* be in the format `D:YYYYMMDDHHmmSSOHH'mm`
        but this is in no way required (and unlikely to be implemented
        consistently, if history is any guide).
        """
        mtime = resolve1(self.props.get("M"))
        if mtime is None:
            return None
        return decode_text(mtime)


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
        the line matrix, in text space units.
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
      descent: The font's descent (scaled by the font size), in text
        space units (this is not really part of the text state but is
        kept here to avoid recomputing it on every glyph)
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
    descent: float = 0

    def reset(self) -> None:
        """Reset the text state"""
        self.line_matrix = MATRIX_IDENTITY
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


SOLID_LINE = DashPattern((), 0)


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
      ncs: Colour space used for non-stroking operations
    """

    linewidth: float = 1
    linecap: int = 0
    linejoin: int = 0
    miterlimit: float = 10
    dash: DashPattern = SOLID_LINE
    intent: PSLiteral = LITERAL_RELATIVE_COLORIMETRIC
    flatness: float = 1
    scolor: Color = BASIC_BLACK
    scs: ColorSpace = PREDEFINED_COLORSPACE["DeviceGray"]
    ncolor: Color = BASIC_BLACK
    ncs: ColorSpace = PREDEFINED_COLORSPACE["DeviceGray"]


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
            super().__init__(stream.buffer)
        except StopIteration:
            super().__init__(b"")
        except TypeError:
            log.warning("Found non-stream in contents: %r", streams)
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
                try:
                    ref = next(self.streamiter)
                    stream = stream_value(ref)
                    self.newstream(stream.buffer)
                except TypeError:
                    log.warning("Found non-stream in contents: %r", ref)


BBOX_NONE = (-1, -1, -1, -1)


class MarkedContent(NamedTuple):
    """
    Marked content information for a point or section in a PDF page.

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


@dataclass
class ContentObject:
    """Any sort of content object.

    Attributes:
      gstate: Graphics state.
      ctm: Coordinate transformation matrix (PDF 1.7 section 8.3.2).
      mcstack: Stack of enclosing marked content sections.
    """

    _pageref: PageRef
    gstate: GraphicState
    ctm: Matrix
    mcstack: Tuple[MarkedContent, ...]

    def __iter__(self) -> Iterator["ContentObject"]:
        yield from ()

    def __len__(self) -> int:
        """Return the number of children of this object (generic implementation)."""
        return sum(1 for _ in self)

    @property
    def object_type(self):
        """Type of this object as a string, e.g. "text", "path", "image"."""
        name = self.__class__.__name__
        return name[: -len("Object")].lower()

    @property
    def bbox(self) -> Rect:
        """The bounding box in device space of this object."""
        # These bboxes have already been computed in device space so
        # we don't need all 4 corners!
        points = itertools.chain.from_iterable(
            ((x0, y0), (x1, y1)) for x0, y0, x1, y1 in (item.bbox for item in self)
        )
        return get_bound(points)

    @property
    def mcs(self) -> Union[MarkedContent, None]:
        """The immediately enclosing marked content section."""
        return self.mcstack[-1] if self.mcstack else None

    @property
    def mcid(self) -> Union[int, None]:
        """The marked content ID of the nearest enclosing marked
        content section with an ID."""
        for mcs in self.mcstack[::-1]:
            if mcs.mcid is not None:
                return mcs.mcid
        return None

    @property
    def page(self) -> Page:
        """The page containing this content object."""
        return _deref_page(self._pageref)


@dataclass
class TagObject(ContentObject):
    """A marked content tag.."""

    _mcs: MarkedContent

    def __len__(self) -> int:
        """A tag has no contents, iterating over it returns nothing."""
        return 0

    @property
    def mcs(self) -> MarkedContent:
        """The marked content tag for this object."""
        return self._mcs

    @property
    def mcid(self) -> Union[int, None]:
        """The marked content ID of the nearest enclosing marked
        content section with an ID."""
        if self._mcs.mcid is not None:
            return self._mcs.mcid
        return super().mcid

    @property
    def bbox(self) -> Rect:
        """A tag has no content and thus no bounding box.

        To avoid needlessly complicating user code this returns
        `BBOX_NONE` instead of `None` or throwing a exception.
        Because that is a specific object, you can reliably check for
        it with:

            if obj.bbox is BBOX_NONE:
                ...
        """
        return BBOX_NONE


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

    def __len__(self) -> int:
        """Even though you can __getitem__ from an image you cannot iterate
        over its keys, sorry about that.  Returns zero."""
        return 0

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
    stream: ContentStream
    resources: Union[None, Dict[str, PDFObject]]

    def __contains__(self, name: object) -> bool:
        return name in self.stream

    def __getitem__(self, name: str) -> PDFObject:
        return self.stream[name]

    @property
    def page(self) -> Page:
        """Get the page (if it exists, raising RuntimeError if not)."""
        return _deref_page(self._pageref)

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
    def contents(self) -> Iterator[PDFObject]:
        """Iterator over PDF objects in the content stream."""
        for pos, obj in ContentParser([self.stream]):
            yield obj

    def __iter__(self) -> Iterator["ContentObject"]:
        interp = LazyInterpreter(self.page, [self.stream], self.resources)
        interp.ctm = self.ctm
        return iter(interp)


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

        If there is only a single subpath, it will still be iterated
        over.  This means that some care must be taken (for example,
        checking if `len(path) == 1`) to avoid endless recursion.

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
                    _pageref=self._pageref,
                    gstate=self.gstate,
                    ctm=self.ctm,
                    mcstack=self.mcstack,
                    raw_segments=segs,
                    stroke=self.stroke,
                    fill=self.fill,
                    evenodd=self.evenodd,
                )
                segs = []
            segs.append(seg)
        if segs:
            yield PathObject(
                _pageref=self._pageref,
                gstate=self.gstate,
                ctm=self.ctm,
                mcstack=self.mcstack,
                raw_segments=segs,
                stroke=self.stroke,
                fill=self.fill,
                evenodd=self.evenodd,
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


@dataclass
class GlyphObject(ContentObject):
    """Individual glyph on the page.

    Attributes:
      textstate: Text state for this glyph.  This is a **mutable**
        object and you should not expect it to be valid outside the
        context of iteration over the parent `TextObject`.
      cid: Character ID for this glyph.
      text: Unicode mapping of this glyph, if any.
      adv: glyph displacement in text space units (horizontal or vertical,
           depending on the writing direction).
      matrix: rendering matrix for this glyph, which transforms text
              space (*not glyph space!*) coordinates to device space.
      bbox: glyph bounding box in device space.
      text_space_bbox: glyph bounding box in text space (i.e. before
                       any possible coordinate transformation)
      corners: Is the transformed bounding box rotated or skewed such
               that all four corners need to be calculated (derived
               from matrix but precomputed for speed)

    """

    textstate: TextState
    cid: int
    text: Union[str, None]
    matrix: Matrix
    adv: float
    corners: bool

    def __len__(self) -> int:
        """Fool! You cannot iterate over a GlyphObject!"""
        return 0

    @property
    def bbox(self) -> Rect:
        x0, y0, x1, y1 = self.text_space_bbox
        if self.corners:
            return get_bound(
                (
                    apply_matrix_pt(self.matrix, (x0, y0)),
                    apply_matrix_pt(self.matrix, (x0, y1)),
                    apply_matrix_pt(self.matrix, (x1, y1)),
                    apply_matrix_pt(self.matrix, (x1, y0)),
                )
            )
        else:
            x0, y0 = apply_matrix_pt(self.matrix, (x0, y0))
            x1, y1 = apply_matrix_pt(self.matrix, (x1, y1))
            if x1 < x0:
                x0, x1 = x1, x0
            if y1 < y0:
                y0, y1 = y1, y0
            return (x0, y0, x1, y1)

    @property
    def text_space_bbox(self):
        tstate = self.textstate
        font = tstate.font
        assert font is not None
        if font.vertical:
            textdisp = font.char_disp(self.cid)
            assert isinstance(textdisp, tuple)
            (vx, vy) = textdisp
            if vx is None:
                vx = tstate.fontsize * 0.5
            else:
                vx = vx * tstate.fontsize * 0.001
            vy = (1000 - vy) * tstate.fontsize * 0.001
            x0, y0 = (-vx, vy + tstate.rise + self.adv)
            x1, y1 = (-vx + tstate.fontsize, vy + tstate.rise)
        else:
            x0, y0 = (0, tstate.descent + tstate.rise)
            x1, y1 = (self.adv, tstate.descent + tstate.rise + tstate.fontsize)
        return (x0, y0, x1, y1)


@dataclass
class TextObject(ContentObject):
    """Text object (contains one or more glyphs).

    Attributes:
      textstate: Text state for this object.
      args: Strings or position adjustments
      bbox: Text bounding box in device space.
      text_space_bbox: Text bounding box in text space (i.e. before
                       any possible coordinate transformation)
    """

    textstate: TextState
    args: List[Union[bytes, float]]
    _chars: Union[List[str], None] = None
    _bbox: Union[Rect, None] = None
    _text_space_bbox: Union[Rect, None] = None
    _next_tstate: Union[TextState, None] = None

    def __iter__(self) -> Iterator[GlyphObject]:
        """Generate glyphs for this text object"""
        tstate = copy(self.textstate)
        font = tstate.font
        # If no font is set, we cannot do anything, since even calling
        # TJ with a displacement and no text effects requires us at
        # least to know the fontsize.
        if font is None:
            log.warning(
                "No font is set, will not update text state or output text: %r TJ",
                self.args,
            )
            self._next_tstate = tstate
            return
        assert self.ctm is not None
        # Extract all the elements so we can translate efficiently
        a, b, c, d, e, f = mult_matrix(tstate.line_matrix, self.ctm)
        # Pre-determine if we need to recompute the bound for rotated glyphs
        corners = b * d < 0 or a * c < 0
        # Apply horizontal scaling
        scaling = tstate.scaling * 0.01
        charspace = tstate.charspace * scaling
        wordspace = tstate.wordspace * scaling
        vert = font.vertical
        if font.multibyte:
            wordspace = 0
        (x, y) = tstate.glyph_offset
        pos = y if vert else x
        needcharspace = False  # Only for first glyph
        for obj in self.args:
            if isinstance(obj, (int, float)):
                dxscale = 0.001 * tstate.fontsize * scaling
                pos -= obj * dxscale
                needcharspace = True
            else:
                for cid, text in font.decode(obj):
                    if needcharspace:
                        pos += charspace
                    textwidth = font.char_width(cid)
                    adv = textwidth * tstate.fontsize * scaling
                    x, y = tstate.glyph_offset = (x, pos) if vert else (pos, y)
                    glyph = GlyphObject(
                        _pageref=self._pageref,
                        gstate=self.gstate,
                        ctm=self.ctm,
                        mcstack=self.mcstack,
                        textstate=tstate,
                        cid=cid,
                        text=text,
                        # Do pre-translation internally (taking rotation into account)
                        matrix=(a, b, c, d, x * a + y * c + e, x * b + y * d + f),
                        adv=adv,
                        corners=corners,
                    )
                    yield glyph
                    pos += adv
                    if cid == 32 and wordspace:
                        pos += wordspace
                    needcharspace = True
        tstate.glyph_offset = (x, pos) if vert else (pos, y)
        if self._next_tstate is None:
            self._next_tstate = tstate

    @property
    def text_space_bbox(self):
        if self._text_space_bbox is not None:
            return self._text_space_bbox
        # No need to save tstate as we do not update it below
        tstate = self.textstate
        font = tstate.font
        if font is None:
            log.warning(
                "No font is set, will not update text state or output text: %r TJ",
                self.args,
            )
            self._text_space_bbox = BBOX_NONE
            self._next_tstate = tstate
            return self._text_space_bbox
        if len(self.args) == 0:
            self._text_space_bbox = BBOX_NONE
            self._next_tstate = tstate
            return self._text_space_bbox
        scaling = tstate.scaling * 0.01
        charspace = tstate.charspace * scaling
        wordspace = tstate.wordspace * scaling
        vert = font.vertical
        if font.multibyte:
            wordspace = 0
        (x, y) = tstate.glyph_offset
        pos = y if vert else x
        needcharspace = False  # Only for first glyph
        if vert:
            x0 = x1 = x
            y0 = y1 = y
        else:
            # These do not change!
            x0 = x1 = x
            y0 = y + tstate.descent + tstate.rise
            y1 = y0 + tstate.fontsize
        for obj in self.args:
            if isinstance(obj, (int, float)):
                dxscale = 0.001 * tstate.fontsize * scaling
                pos -= obj * dxscale
                needcharspace = True
            else:
                for cid, _ in font.decode(obj):
                    if needcharspace:
                        pos += charspace
                    textwidth = font.char_width(cid)
                    adv = textwidth * tstate.fontsize * scaling
                    x, y = (x, pos) if vert else (pos, y)
                    if vert:
                        textdisp = font.char_disp(cid)
                        assert isinstance(textdisp, tuple)
                        (vx, vy) = textdisp
                        if vx is None:
                            vx = tstate.fontsize * 0.5
                        else:
                            vx = vx * tstate.fontsize * 0.001
                        vy = (1000 - vy) * tstate.fontsize * 0.001
                        x0 = min(x0, x - vx)
                        y0 = min(y0, y + vy + tstate.rise + adv)
                        x1 = max(x1, x - vx + tstate.fontsize)
                        y1 = max(y1, y + vy + tstate.rise)
                    else:
                        x1 = x + adv
                    pos += adv
                    if cid == 32 and wordspace:
                        pos += wordspace
                    needcharspace = True
        if self._next_tstate is None:
            self._next_tstate = copy(tstate)
            self._next_tstate.glyph_offset = (x, pos) if vert else (pos, y)
        self._text_space_bbox = (x0, y0, x1, y1)
        return self._text_space_bbox

    @property
    def next_textstate(self) -> TextState:
        if self._next_tstate is not None:
            return self._next_tstate
        _ = self.text_space_bbox
        assert self._next_tstate is not None
        return self._next_tstate

    @property
    def bbox(self) -> Rect:
        # We specialize this to avoid it having side effects on the
        # text state (already it's a bit of a footgun that __iter__
        # does that...), but also because we know all glyphs have the
        # same text matrix and thus we can avoid a lot of multiply
        if self._bbox is not None:
            return self._bbox
        matrix = mult_matrix(self.textstate.line_matrix, self.ctm)
        self._bbox = get_transformed_bound(matrix, self.text_space_bbox)
        return self._bbox

    @property
    def chars(self) -> str:
        """Get the Unicode characters (in stream order) for this object."""
        if self._chars is not None:
            return "".join(self._chars)
        self._chars = []
        font = self.textstate.font
        assert font is not None, "No font was selected"
        for obj in self.args:
            if not isinstance(obj, bytes):
                continue
            for _, text in font.decode(obj):
                self._chars.append(text)
        return "".join(self._chars)

    def __len__(self) -> int:
        """Return the number of glyphs that would result from iterating over
        this object.

        Important: this is the number of glyphs, *not* the number of
        Unicode characters.
        """
        nglyphs = 0
        font = self.textstate.font
        assert font is not None, "No font was selected"
        for obj in self.args:
            if not isinstance(obj, bytes):
                continue
            nglyphs += sum(1 for _ in font.decode(obj))
        return nglyphs


def make_seg(operator: PathOperator, *points: Point):
    return PathSegment(operator, points)


def point_value(x: PDFObject, y: PDFObject) -> Point:
    return (num_value(x), num_value(y))


class LazyInterpreter:
    """Interpret the page yielding lazy objects."""

    ctm: Matrix

    def __init__(
        self,
        page: Page,
        contents: Iterable[PDFObject],
        resources: Union[Dict, None] = None,
        filter_class: Union[Type[ContentObject], None] = None,
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
        self.filter_class = filter_class
        self.init_resources(page, page.resources if resources is None else resources)
        self.init_state(page.ctm)

    def init_resources(self, page: Page, resources: Dict) -> None:
        """Prepare the fonts and XObjects listed in the Resource attribute."""
        self.resources = resources
        self.fontmap: Dict[object, Font] = {}
        self.xobjmap = {}
        self.csmap: Dict[str, ColorSpace] = copy(PREDEFINED_COLORSPACE)
        if not self.resources:
            return
        doc = _deref_document(page.docref)

        for k, v in dict_value(self.resources).items():
            mapping = resolve1(v)
            if mapping is None:
                log.warning("Missing %s mapping", k)
                continue
            if k == "Font":
                if not isinstance(mapping, dict):
                    log.warning("Font mapping not a dict: %r", mapping)
                    continue
                for fontid, spec in mapping.items():
                    objid = None
                    if isinstance(spec, ObjRef):
                        objid = spec.objid
                    try:
                        spec = dict_value(spec)
                        self.fontmap[fontid] = doc.get_font(objid, spec)
                    except TypeError:
                        log.warning(
                            "Broken/missing font spec for Font ID %r: %r", fontid, spec
                        )
                        self.fontmap[fontid] = doc.get_font(objid, {})
            elif k == "ColorSpace":
                if not isinstance(mapping, dict):
                    log.warning("ColorSpace mapping not a dict: %r", mapping)
                    continue
                for csid, spec in mapping.items():
                    colorspace = get_colorspace(resolve1(spec), csid)
                    if colorspace is not None:
                        self.csmap[csid] = colorspace
            elif k == "ProcSet":
                pass  # called get_procset which did exactly
                # nothing. perhaps we want to do something?
            elif k == "XObject":
                if not isinstance(mapping, dict):
                    log.warning("XObject mapping not a dict: %r", mapping)
                    continue
                for xobjid, xobjstrm in mapping.items():
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
        # mcstack: stack for marked content sections.
        self.mcstack: Tuple[MarkedContent, ...] = ()

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

    def __iter__(self) -> Iterator[ContentObject]:
        parser = ContentParser(self.contents)
        for _, obj in parser:
            # These are handled inside the parser as they don't obey
            # the normal syntax rules (PDF 1.7 sec 8.9.7)
            if isinstance(obj, InlineImage):
                co = self.do_EI(obj)
                if co is not None:
                    yield co
            elif isinstance(obj, PSKeyword):
                if obj in self._dispatch:
                    method, nargs = self._dispatch[obj]
                    if nargs:
                        args = self.pop(nargs)
                        if len(args) != nargs:
                            log.warning(
                                "Insufficient arguments (%d) for operator: %r",
                                len(args),
                                obj,
                            )
                        else:
                            try:
                                co = method(*args)
                            except TypeError as e:
                                log.warning(
                                    "Incorrect type of arguments(%r) for operator %r: %s",
                                    args,
                                    obj,
                                    e,
                                )
                    else:
                        co = method()
                    if co is not None:
                        yield co
                    if isinstance(co, TextObject):
                        self.textstate = co.next_textstate
                else:
                    # TODO: This can get very verbose
                    log.warning("Unknown operator: %r", obj)
            else:
                self.push(obj)

    def create(self, object_class, **kwargs) -> Union[ContentObject, None]:
        if self.filter_class is not None and object_class is not self.filter_class:
            return None
        return object_class(
            _pageref=self.page.pageref,
            ctm=self.ctm,
            mcstack=self.mcstack,
            gstate=self.graphicstate,
            **kwargs,
        )

    def do_S(self) -> Union[ContentObject, None]:
        """Stroke path"""
        if not self.curpath:
            return None
        curpath = self.curpath
        self.curpath = []
        return self.create(
            PathObject,
            stroke=True,
            fill=False,
            evenodd=False,
            raw_segments=curpath,
        )

    def do_s(self) -> Union[ContentObject, None]:
        """Close and stroke path"""
        self.do_h()
        return self.do_S()

    def do_f(self) -> Union[ContentObject, None]:
        """Fill path using nonzero winding number rule"""
        if not self.curpath:
            return None
        curpath = self.curpath
        self.curpath = []
        return self.create(
            PathObject,
            stroke=False,
            fill=True,
            evenodd=False,
            raw_segments=curpath,
        )

    def do_F(self) -> Union[ContentObject, None]:
        """Fill path using nonzero winding number rule (obsolete)"""
        return self.do_f()

    def do_f_a(self) -> Union[ContentObject, None]:
        """Fill path using even-odd rule"""
        if not self.curpath:
            return None
        curpath = self.curpath
        self.curpath = []
        return self.create(
            PathObject,
            stroke=False,
            fill=True,
            evenodd=True,
            raw_segments=curpath,
        )

    def do_B(self) -> Union[ContentObject, None]:
        """Fill and stroke path using nonzero winding number rule"""
        if not self.curpath:
            return None
        curpath = self.curpath
        self.curpath = []
        return self.create(
            PathObject,
            stroke=True,
            fill=True,
            evenodd=False,
            raw_segments=curpath,
        )

    def do_B_a(self) -> Union[ContentObject, None]:
        """Fill and stroke path using even-odd rule"""
        if not self.curpath:
            return None
        curpath = self.curpath
        self.curpath = []
        return self.create(
            PathObject,
            stroke=True,
            fill=True,
            evenodd=True,
            raw_segments=curpath,
        )

    def do_b(self) -> Union[ContentObject, None]:
        """Close, fill, and stroke path using nonzero winding number rule"""
        self.do_h()
        return self.do_B()

    def do_b_a(self) -> Union[ContentObject, None]:
        """Close, fill, and stroke path using even-odd rule"""
        self.do_h()
        return self.do_B_a()

    def do_TJ(self, strings: PDFObject) -> Union[ContentObject, None]:
        """Show one or more text strings, allowing individual glyph
        positioning"""
        args: List[Union[bytes, float]] = []
        has_text = False
        for s in list_value(strings):
            if isinstance(s, (int, float)):
                args.append(s)
            elif isinstance(s, bytes):
                if s:
                    has_text = True
                args.append(s)
            else:
                log.warning(
                    "Ignoring non-string/number %r in text object %r", s, strings
                )
        obj = self.create(TextObject, textstate=self.textstate, args=args)
        if obj is not None:
            if has_text:
                return obj
            # Even without text, TJ can still update the line matrix (ugh!)
            assert isinstance(obj, TextObject)
            self.textstate = obj.next_textstate
        return None

    def do_Tj(self, s: PDFObject) -> Union[ContentObject, None]:
        """Show a text string"""
        return self.do_TJ([s])

    def do__q(self, s: PDFObject) -> Union[ContentObject, None]:
        """Move to next line and show text

        The ' (single quote) operator.
        """
        self.do_T_a()
        return self.do_TJ([s])

    def do__w(
        self, aw: PDFObject, ac: PDFObject, s: PDFObject
    ) -> Union[ContentObject, None]:
        """Set word and character spacing, move to next line, and show text

        The " (double quote) operator.
        """
        self.do_Tw(aw)
        self.do_Tc(ac)
        return self.do_TJ([s])

    def do_EI(self, obj: PDFObject) -> Union[ContentObject, None]:
        """End inline image object"""
        if isinstance(obj, InlineImage):
            # Inline images are not XObjects, have no xobjid
            return self.render_image(None, obj)
        else:
            # FIXME: Do... something?
            return None

    def do_Do(self, xobjid_arg: PDFObject) -> Union[ContentObject, None]:
        """Invoke named XObject"""
        xobjid = literal_name(xobjid_arg)
        try:
            xobj = stream_value(self.xobjmap[xobjid])
        except KeyError:
            log.debug("Undefined xobject id: %r", xobjid)
            return None
        except TypeError as e:
            log.debug("Empty or invalid xobject with id %r: %s", xobjid, e)
            return None
        subtype = xobj.get("Subtype")
        if subtype is LITERAL_FORM and "BBox" in xobj:
            matrix = cast(Matrix, list_value(xobj.get("Matrix", MATRIX_IDENTITY)))
            # According to PDF reference 1.7 section 4.9.1, XObjects in
            # earlier PDFs (prior to v1.2) use the page's Resources entry
            # instead of having their own Resources entry.
            xobjres = xobj.get("Resources")
            resources = None if xobjres is None else dict_value(xobjres)
            if self.filter_class is None or self.filter_class is XObjectObject:
                return XObjectObject(
                    _pageref=self.page.pageref,
                    ctm=mult_matrix(matrix, self.ctm),
                    mcstack=self.mcstack,
                    gstate=self.graphicstate,
                    xobjid=xobjid,
                    stream=xobj,
                    resources=resources,
                )
        elif subtype is LITERAL_IMAGE and "Width" in xobj and "Height" in xobj:
            return self.render_image(xobjid, xobj)
        # unsupported xobject type.
        return None

    def render_image(
        self, xobjid: Union[str, None], stream: ContentStream
    ) -> Union[ContentObject, None]:
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
        """Begin text object.

        Initializing the text matrix, Tm, and the text line matrix, Tlm, to
        the identity matrix. Text objects cannot be nested; a second BT cannot
        appear before an ET.
        """
        self.textstate.reset()

    def do_ET(self) -> None:
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
            doc = _deref_document(self.page.docref)
            self.textstate.font = doc.get_font(None, {})
        self.textstate.fontsize = num_value(fontsize)
        self.textstate.descent = (
            self.textstate.font.get_descent() * self.textstate.fontsize
        )

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

        (PDF 1.7 Table 108) This operator shall have the same effect as this code:
            −ty TL
            tx ty Td
        """
        self.do_TL(-num_value(ty))
        self.do_Td(tx, ty)

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
        self.textstate.line_matrix = (
            num_value(a),
            num_value(b),
            num_value(c),
            num_value(d),
            num_value(e),
            num_value(f),
        )
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

    def get_property(self, prop: PSLiteral) -> Union[Dict, None]:
        if "Properties" in self.resources:
            props = dict_value(self.resources["Properties"])
            return dict_value(props.get(prop.name))
        return None

    def do_MP(self, tag: PDFObject) -> Union[ContentObject, None]:
        """Define marked-content point"""
        return self.do_DP(tag, None)

    def do_DP(
        self, tag: PDFObject, props: PDFObject = None
    ) -> Union[ContentObject, None]:
        """Define marked-content point with property list"""
        # See above
        if isinstance(props, PSLiteral):
            props = self.get_property(props)
        rprops = {} if props is None else dict_value(props)
        if self.filter_class is None or self.filter_class is TagObject:
            return TagObject(
                _pageref=self.page.pageref,
                ctm=self.ctm,
                mcstack=self.mcstack,
                gstate=self.graphicstate,
                _mcs=MarkedContent(mcid=None, tag=literal_name(tag), props=rprops),
            )
        return None

    def begin_tag(self, tag: PDFObject, props: Dict[str, PDFObject]) -> None:
        """Handle beginning of tag, setting current MCID if any."""
        assert isinstance(tag, PSLiteral)
        tag = decode_text(tag.name)
        if "MCID" in props:
            mcid = int_value(props["MCID"])
        else:
            mcid = None
        self.mcstack = (*self.mcstack, MarkedContent(mcid=mcid, tag=tag, props=props))

    def do_BMC(self, tag: PDFObject) -> None:
        """Begin marked-content sequence"""
        self.begin_tag(tag, {})

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
            return None
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
        if self.mcstack:
            self.mcstack = self.mcstack[:-1]
