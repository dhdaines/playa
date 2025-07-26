"""
Classes for looking at pages and their contents.
"""

import itertools
import logging
import operator
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
    Sequence,
    Tuple,
    Type,
    TypeVar,
    Union,
    overload,
)

from playa.content import (
    ContentObject,
    GlyphObject,
    ImageObject,
    PathObject,
    TextObject,
    XObjectObject,
    _extract_mcid_texts,
)
from playa.exceptions import PDFSyntaxError
from playa.font import Font
from playa.interp import LazyInterpreter, _make_fontmap
from playa.parser import ContentParser, PDFObject, Token
from playa.pdftypes import (
    MATRIX_IDENTITY,
    ContentStream,
    ObjRef,
    PSLiteral,
    Point,
    Rect,
    dict_value,
    int_value,
    list_value,
    literal_name,
    rect_value,
    resolve1,
    stream_value,
)
from playa.utils import decode_text, mult_matrix, normalize_rect, transform_bbox
from playa.worker import PageRef, _deref_document, _deref_page, _ref_document, _ref_page

if TYPE_CHECKING:
    from playa.document import Document
    from playa.structure import Element

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
    _structmap: Union[List[Union["Element", None]], None] = None

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
        for _, obj in ContentParser(self._contents, self.doc):
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

        This will also return Form XObjects within Form XObjects,
        except in the case of circular reference chains.
        """

        from typing import Set

        def xobjects_one(
            itor: Iterable["ContentObject"], parents: Set[int]
        ) -> Iterator["XObjectObject"]:
            for obj in itor:
                if isinstance(obj, XObjectObject):
                    stream_id = 0 if obj.stream.objid is None else obj.stream.objid
                    if stream_id not in parents:
                        yield obj
                        yield from xobjects_one(obj, parents | {stream_id})

        for obj in xobjects_one(self, set()):
            if isinstance(obj, XObjectObject):
                yield obj

    @property
    def tokens(self) -> Iterator[Token]:
        """Iterator over tokens in the content streams."""
        parser = ContentParser(self._contents, self.doc)
        while True:
            try:
                pos, tok = parser.nexttoken()
            except StopIteration:
                return
            yield tok

    @property
    def parent_key(self) -> Union[int, None]:
        """Parent tree key for this page, if any."""
        if "StructParents" in self.attrs:
            return int_value(self.attrs["StructParents"])
        return None

    @property
    def structure(self) -> Sequence[Union["Element", None]]:
        """Mapping of marked content IDs to logical structure elements.

        This is actually a list of logical structure elements
        corresponding to marked content IDs, or `None` for indices
        which do not correspond to a marked content ID.  Note that
        because structure elements may contain multiple marked content
        sections, the same element may occur multiple times in this
        list.

        Note: This is not the same as `playa.Document.structure`.
            PDF documents have logical structure, but PDF pages **do
            not**, and it is dishonest to pretend otherwise (as some
            code I once wrote unfortunately does).  What they do have
            is marked content sections which correspond to content
            items in the logical structure tree.

        Danger: Do not rely on this being a `list`.
            Currently this is implemented eagerly, but in the future it
            may return a lazy object.

        """
        from playa.structure import Element

        if self._structmap is not None:
            return self._structmap
        self._structmap = []
        if self.doc.structure is None:
            return self._structmap
        parent_key = self.parent_key
        if parent_key is None:
            return self._structmap
        try:
            parents = list_value(self.doc.structure.parent_tree[parent_key])
        except IndexError:
            return self._structmap
        # Elements can contain multiple marked content sections, so
        # don't create redundant Element objects for these
        elements: Dict[int, Element] = {}
        for obj in parents:
            objid = obj.objid if isinstance(obj, ObjRef) else id(obj)
            if objid not in elements:
                elements[objid] = Element.from_dict(self.doc, dict_value(obj))
            self._structmap.append(elements[objid])
        return self._structmap

    @property
    def fonts(self) -> Mapping[str, Font]:
        """Mapping of resource names to fonts for this page.

        Note: This is not the same as `playa.Document.fonts`.
            The resource names (e.g. `F1`, `F42`, `FooBar`) here are
            specific to a page (or Form XObject) resource dictionary
            and have no relation to the font name as commonly
            understood (e.g. `Helvetica`,
            `WQERQE+Arial-SuperBold-HJRE-UTF-8`).  Since font names are
            generally considered to be globally unique, it may be
            possible to access fonts by them in the future.

        Note: This does not include fonts specific to Form XObjects.
            Since it is possible for the resource names to collide,
            this will only return the fonts for a page and not for any
            Form XObjects invoked on it.  You may use
            `XObjectObject.fonts` to access these.

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
            itor: Iterable["ContentObject"], parents: Set[int]
        ) -> Iterator["ContentObject"]:
            for obj in itor:
                if isinstance(obj, XObjectObject):
                    stream_id = 0 if obj.stream.objid is None else obj.stream.objid
                    if stream_id not in parents:
                        yield from flatten_one(obj, parents | {stream_id})
                else:
                    yield obj

        if filter_class is None:
            yield from flatten_one(self, set())
        else:
            for obj in flatten_one(self, set()):
                if isinstance(obj, filter_class):
                    yield obj

    @property
    def mcid_texts(self) -> Mapping[int, List[str]]:
        """Mapping of marked content IDs to Unicode text strings.

        For use in text extraction from tagged PDFs.

        Danger: Do not rely on this being a `dict`.
            Currently this is implemented eagerly, but in the future it
            may return a lazy object.
        """
        if hasattr(self, "_textmap"):
            return self._textmap
        self._textmap: Mapping[int, List[str]] = _extract_mcid_texts(self)
        return self._textmap

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
                # 0.5 here is a heuristic!!!
                if prev_end and off - prev_end > 0.5:
                    if chars and chars[-1] != " ":
                        chars.append(" ")
                if glyph.text is not None:
                    chars.append(glyph.text)
                dx, dy = glyph.displacement
                prev_end = off + (dy if vertical else dx)
            return "".join(chars), prev_end

        prev_end = 0.0
        prev_origin: Union[Point, None] = None
        lines = []
        strings: List[str] = []
        for text in self.texts:
            if text.gstate.font is None:
                continue
            vertical = text.gstate.font.vertical
            # Track changes to the translation component of text
            # rendering matrix to (yes, heuristically) detect newlines
            # and spaces between text objects
            dx, dy = text.origin
            off = dy if vertical else dx
            if strings and self._next_line(text, prev_origin):
                lines.append("".join(strings))
                strings.clear()
            # 0.5 here is a heuristic!!!
            if strings and off - prev_end > 0.5 and not strings[-1].endswith(" "):
                strings.append(" ")
            textstr, prev_end = _extract_text_from_obj(text, vertical, off)
            strings.append(textstr)
            prev_origin = dx, dy
        if strings:
            lines.append("".join(strings))
        return "\n".join(lines)

    def _next_line(
        self, text: Union[TextObject, None], prev_offset: Union[Point, None]
    ) -> bool:
        if text is None:
            return False
        if text.gstate.font is None:
            return False
        if prev_offset is None:
            return False
        offset = text.origin

        # Vertical text (usually) means right-to-left lines
        if text.gstate.font.vertical:
            line_offset = offset[0] - prev_offset[0]
        else:
            # The CTM isn't useful here because we actually do care
            # about the final device space, and we just want to know
            # which way is up and which way is down.
            dy = offset[1] - prev_offset[1]
            if self.space == "screen":
                line_offset = -dy
            else:
                line_offset = dy
        return line_offset < 0

    def extract_text_tagged(self) -> str:
        """Get text from a page of a tagged PDF."""
        lines: List[str] = []
        strings: List[str] = []
        prev_mcid: Union[int, None] = None
        prev_origin: Union[Point, None] = None
        # TODO: Iteration over marked content sections and getting
        # their text, origin, and displacement, will be refactored
        for mcs, texts in itertools.groupby(self.texts, operator.attrgetter("mcs")):
            text: Union[TextObject, None] = None
            # TODO: Artifact can also be a structure element, but
            # also, any content outside the structure tree is
            # considered an artifact
            if mcs is None or mcs.tag == "Artifact":
                for text in texts:
                    prev_origin = text.origin
                continue
            actual_text = mcs.props.get("ActualText")
            if actual_text is None:
                reversed = mcs.tag == "ReversedChars"
                c = []
                for text in texts:  # noqa: B031
                    c.append(text.chars[::-1] if reversed else text.chars)
                chars = "".join(c)
            else:
                assert isinstance(actual_text, bytes)
                chars = actual_text.decode("UTF-16")
                # Consume all text objects to ensure correct graphicstate
                for _ in texts:  # noqa: B031
                    pass

            # Remove soft hyphens
            chars = chars.replace("\xad", "")
            # There *might* be a line break, determine based on origin
            if mcs.mcid != prev_mcid:
                if self._next_line(text, prev_origin):
                    lines.extend(textwrap.wrap("".join(strings)))
                    strings.clear()
                prev_mcid = mcs.mcid
            strings.append(chars)
            if text is not None:
                prev_origin = text.origin
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
    def bbox(self) -> Rect:
        """Bounding box for this annotation in device space."""
        return transform_bbox(self.page.ctm, self.rect)

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
