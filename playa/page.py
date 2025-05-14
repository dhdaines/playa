"""
Classes for looking at pages and their contents.
"""

import logging
import textwrap
from dataclasses import dataclass
from typing import (
    TYPE_CHECKING,
    Dict,
    Iterable,
    Iterator,
    List,
    Literal,
    Mapping,
    Optional,
    Tuple,
    Type,
    TypeVar,
    Union,
    cast,
    overload,
)

from playa.content import (
    ContentObject,
    GlyphObject,
    ImageObject,
    MarkedContent,
    PathObject,
    TextObject,
    XObjectObject,
)
from playa.exceptions import PDFSyntaxError
from playa.font import Font
from playa.interp import LazyInterpreter, _make_fontmap
from playa.parser import ContentParser, PDFObject, Token
from playa.pdftypes import (
    MATRIX_IDENTITY,
    ContentStream,
    PSLiteral,
    Rect,
    dict_value,
    int_value,
    literal_name,
    rect_value,
    resolve1,
    stream_value,
)
from playa.utils import decode_text, mult_matrix, normalize_rect
from playa.worker import PageRef, _deref_document, _deref_page, _ref_document, _ref_page

if TYPE_CHECKING:
    from playa.document import Document

log = logging.getLogger(__name__)

# some predefined literals and keywords.
DeviceSpace = Literal["page", "screen", "default", "user"]
CO = TypeVar("CO")


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

    _fontmap: Union[Dict[str, Font], None] = None

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
            self.mediabox = normalize_rect(rect_value(self.attrs["MediaBox"]))
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
                self.cropbox = normalize_rect(rect_value(self.attrs["CropBox"]))
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
        if not isinstance(alist, list):
            log.warning("Invalid Annots list: %r", alist)
            return
        for obj in alist:
            try:
                yield Annotation.from_dict(obj, self)
            except (TypeError, ValueError, PDFSyntaxError) as e:
                log.warning("Invalid object %r in Annots: %s", obj, e)
                continue

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
    def glyphs(self) -> Iterator["GlyphObject"]:
        """Iterator over lazy glyph objects."""
        for text in self.flatten(TextObject):
            yield from text

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

    @property
    def fonts(self) -> Mapping[str, Font]:
        """Get the mapping of resource names to fonts for this page.

        Note: Resource names are not font names.
            The resource names (e.g. `F1`, `F42`, `FooBar`) here are
            specific to a page (or Form XObject) resource dictionary `
            and have no relation to the font name as commonly
            understood (e.g. `Helvetica`,
            `WQERQE+Arial-SuperBold-HJRE-UTF-8`).  Since font names are
            generally considered to be globally unique, it may be
            possible to access fonts by them in the future.

        Danger: Do not rely on this being a `dict`.
            Currently this is implemented eagerly, but in the future it
            may return a lazy object which only loads fonts on demand.

        """
        if self._fontmap is not None:
            return self._fontmap
        self._fontmap = _make_fontmap(self.resources.get("Font"), self.doc)
        return self._fontmap

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

        from typing import Set

        def flatten_one(
            itor: Iterable["ContentObject"], parents: Set[str]
        ) -> Iterator["ContentObject"]:
            for obj in itor:
                if isinstance(obj, XObjectObject) and obj.xobjid not in parents:
                    yield from flatten_one(obj, parents | {obj.xobjid})
                else:
                    yield obj

        if filter_class is None:
            yield from flatten_one(self, set())
        else:
            for obj in flatten_one(self, set()):
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

        def _extract_text_from_obj(
            obj: "TextObject", vertical: bool, prev_end: float
        ) -> Tuple[str, float]:
            """Try to get text from a text object."""
            chars: List[str] = []
            for glyph in obj:
                x, y = glyph.origin
                off = y if vertical else x
                # FIXME: The 0.5 is a heuristic!!!
                if prev_end and off - prev_end > 0.5:
                    chars.append(" ")
                if glyph.text is not None:
                    chars.append(glyph.text)
                dx, dy = glyph.displacement
                prev_end = off + (dy if vertical else dx)
            return "".join(chars), prev_end

        prev_end = prev_line_offset = prev_word_offset = 0.0
        lines = []
        strings: List[str] = []
        for text in self.texts:
            if text.gstate.font is None:
                continue
            vertical = text.gstate.font.vertical
            # Track changes to the translation component of text
            # rendering matrix to (yes, heuristically) detect newlines
            # and spaces between text objects
            _, _, _, _, dx, dy = text.matrix
            line_offset = dx if vertical else dy
            word_offset = dy if vertical else dx
            # Vertical text (usually) means right-to-left lines
            if vertical:
                line_feed = line_offset < prev_line_offset
            elif self.space in ("page", "default"):
                line_feed = line_offset < prev_line_offset
            else:
                line_feed = line_offset > prev_line_offset
            if strings and line_feed:
                lines.append("".join(strings))
                strings.clear()
            # FIXME: the 0.5 is a heuristic!!!
            if strings and word_offset > prev_end + prev_word_offset + 0.5:
                strings.append(" ")
            textstr, end = _extract_text_from_obj(text, vertical, prev_end)
            strings.append(textstr)
            prev_line_offset = line_offset
            prev_word_offset = word_offset
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
        for text in self.texts:
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

    @classmethod
    def from_dict(cls, obj: PDFObject, page: Page) -> "Annotation":
        annot = dict_value(obj)
        subtype = annot.get("Subtype")
        if subtype is None or not isinstance(subtype, PSLiteral):
            raise PDFSyntaxError("Invalid annotation Subtype %r" % (subtype,))
        rect = rect_value(annot.get("Rect"))
        return Annotation(
            _pageref=page.pageref,
            subtype=literal_name(subtype),
            rect=rect,
            props=annot,
        )

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
        if not isinstance(contents, (bytes, str)):
            log.warning("Invalid annotation contents: %r", contents)
            return None
        return decode_text(contents)

    @property
    def name(self) -> Union[str, None]:
        """Annotation name, uniquely identifying this annotation."""
        name = resolve1(self.props.get("NM"))
        if name is None:
            return None
        if not isinstance(name, (bytes, str)):
            log.warning("Invalid annotation name: %r", name)
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
        if not isinstance(mtime, (bytes, str)):
            log.warning("Invalid annotation modification date: %r", mtime)
            return None
        return decode_text(mtime)
