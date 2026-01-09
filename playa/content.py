"""
PDF content objects created by the interpreter.
"""

import itertools
import logging
from abc import abstractmethod
from copy import copy
from dataclasses import dataclass
from typing import (
    TYPE_CHECKING,
    Dict,
    Iterable,
    Iterator,
    List,
    Literal,
    Mapping,
    NamedTuple,
    Sequence,
    Tuple,
    Union,
)

from playa.color import (
    BASIC_BLACK,
    LITERAL_DEFAULT,
    LITERAL_NORMAL,
    LITERAL_RELATIVE_COLORIMETRIC,
    PREDEFINED_COLORSPACE,
    Color,
    ColorSpace,
)
from playa.font import CIDFont, Font, Type3Font
from playa.parser import LIT, ContentParser, Token
from playa.pdftypes import (
    BBOX_NONE,
    ContentStream,
    Matrix,
    PDFObject,
    Point,
    PSLiteral,
    Rect,
    dict_value,
    int_value,
    list_value,
    matrix_value,
    rect_value,
    resolve1,
)
from playa.utils import (
    apply_matrix_pt,
    decode_text,
    get_bound,
    mult_matrix,
    transform_bbox,
    translate_matrix,
    update_glyph_offset,
)
from playa.worker import PageRef, _deref_document, _deref_page

if TYPE_CHECKING:
    from playa.document import Document
    from playa.page import Page
    from playa.structure import Element, PageStructure

log = logging.getLogger(__name__)


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
    """PDF graphics state (PDF 1.7 section 8.4) including text state
    (PDF 1.7 section 9.3.1), but excluding coordinate transformations.

    Contrary to the pretensions of pdfminer.six, the text state is for
    the most part not at all separate from the graphics state, and can
    be updated outside the confines of `BT` and `ET` operators, thus
    there is no advantage and only confusion that comes from treating
    it separately.

    The only state that does not persist outside `BT` / `ET` pairs is
    the text coordinate space (line matrix and text rendering matrix),
    and it is also the only part that is updated during iteration over
    a `TextObject`.

    For historical reasons the main coordinate transformation matrix,
    though it is also part of the graphics state, is also stored
    separately.

    Attributes:
      clipping_path: The current clipping path (sec. 8.5.4)
      linewidth: Line width in user space units (sec. 8.4.3.2)
      linecap: Line cap style (sec. 8.4.3.3)
      linejoin: Line join style (sec. 8.4.3.4)
      miterlimit: Maximum length of mitered line joins (sec. 8.4.3.5)
      dash: Dash pattern for stroking (sec 8.4.3.6)
      intent: Rendering intent (sec. 8.6.5.8)
      stroke_adjustment: A flag specifying whether to compensate for
        possible rasterization effects when stroking a path with a line
        width that is small relative to the pixel resolution of the output
        device (sec. 10.7.5)
      blend_mode: The current blend mode that shall be used in the
        transparent imaging model (sec. 11.3.5)
      smask: A soft-mask dictionary (sec. 11.6.5.1) or None
      salpha: The constant shape or constant opacity value used for
        stroking operations (sec. 11.3.7.2 & 11.6.4.4)
      nalpha: The constant shape or constant opacity value used for
        non-stroking operations
      alpha_source: A flag specifying whether the current soft mask and
        alpha constant parameters shall be interpreted as shape values
        (true) or opacity values (false). This flag also governs the
        interpretation of the SMask entry, if any, in an image dictionary
      black_pt_comp: The black point compensation algorithm that shall be
        used when converting CIE-based colours (sec. 8.6.5.9)
      flatness: The precision with which curves shall be rendered on
        the output device (sec. 10.6.2)
      scolor: Colour used for stroking operations
      scs: Colour space used for stroking operations
      ncolor: Colour used for non-stroking operations
      ncs: Colour space used for non-stroking operations
      font: The current font.
      fontsize: The "font size" parameter, which is **not** the font
        size in points as you might understand it, but rather a
        scaling factor applied to text space (so, it affects not only
        text size but position as well).  Since most reasonable people
        find that behaviour rather confusing, this is often just 1.0,
        and PDFs rely on the text matrix to set the size of text.
      charspace: Extra spacing to add after each glyph, expressed in
        unscaled text space units, meaning it is not affected by
        `fontsize`.  **BUT** it will be modified by `scaling` for
        horizontal writing mode (so, most of the time).
      wordspace: Extra spacing to add after a space glyph, defined
        very specifically as the glyph encoded by the single-byte
        character code 32 (SPOILER: it is probably a space).  Also
        expressed in unscaled text space units, but modified by
        `scaling`.
      scaling: The horizontal scaling factor as defined by the PDF
        standard (that is, divided by 100).
      leading: The leading as defined by the PDF standard, in unscaled
        text space units.
      render_mode: The PDF rendering mode.  The really important one
        here is 3, which means "don't render the text".  You might
        want to use this to detect invisible text.
      rise: The text rise (superscript or subscript position), in
        unscaled text space units.
      knockout: The text knockout flag, shall determine the behaviour of
        overlapping glyphs within a text object in the transparent imaging
        model (sec. 9.3.8)

    """

    clipping_path: None = None  # TODO
    linewidth: float = 1
    linecap: int = 0
    linejoin: int = 0
    miterlimit: float = 10
    dash: DashPattern = SOLID_LINE
    intent: PSLiteral = LITERAL_RELATIVE_COLORIMETRIC
    stroke_adjustment: bool = False
    blend_mode: Union[PSLiteral, List[PSLiteral]] = LITERAL_NORMAL
    smask: Union[None, Dict[str, PDFObject]] = None
    salpha: float = 1
    nalpha: float = 1
    alpha_source: bool = False
    black_pt_comp: PSLiteral = LITERAL_DEFAULT
    flatness: float = 1
    scolor: Color = BASIC_BLACK
    scs: ColorSpace = PREDEFINED_COLORSPACE["DeviceGray"]
    ncolor: Color = BASIC_BLACK
    ncs: ColorSpace = PREDEFINED_COLORSPACE["DeviceGray"]
    font: Union[Font, None] = None
    fontsize: float = 0
    charspace: float = 0
    wordspace: float = 0
    scaling: float = 100
    leading: float = 0
    render_mode: int = 0
    rise: float = 0
    knockout: bool = True


class MarkedContent(NamedTuple):
    """Marked content point or section in a PDF page or Form XObject.

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
    _parentkey: Union[int, None]
    gstate: GraphicState
    ctm: Matrix
    mcstack: Tuple[MarkedContent, ...]

    def __iter__(self) -> Iterator["ContentObject"]:
        yield from ()

    def __len__(self) -> int:
        """Return the number of children of this object (generic implementation)."""
        return sum(1 for _ in self)

    def finalize(self) -> "ContentObject":
        """Finalize this content object so it can be reused.

        Because certain elements (specifically the graphics state) are
        references to mutable objects that are updated during content
        parsing, reusing ContentObjects is fraught with peril.  This
        was a conscious design choice to save time and memory, but
        perhaps not a good one.

        If you want to reuse a ContentObject, thus, you must call this
        method on it.  For convenience, it returns the same
        ContentObject, allowing you to do, for instance:

            objs = [x.finalize() for x in page]
        """
        self.gstate = copy(self.gstate)
        return self

    @property
    def object_type(self) -> str:
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
        content section with an ID.

        This is notably what you should use (and what `parent` uses)
        to find the parent logical structure element, because (PDF
        14.7.5.1.1):

        > A marked-content sequence corresponding to a structure
        content item shall not have another marked-content sequence
        for a structure content item nested within it though
        non-structural marked-content shall be allowed.
        """
        if hasattr(self, "_mcid"):
            return self._mcid
        for mcs in self.mcstack[::-1]:
            if mcs.mcid is not None:
                self._mcid: Union[int, None] = mcs.mcid
                break
        else:
            self._mcid = None
        return self._mcid

    @property
    def parent(self) -> Union["Element", None]:
        """The enclosing logical structure element, if any."""
        from playa.structure import Element

        # Use `mcid` and not `mcs` here (see docs for `mcid`)
        if hasattr(self, "_parent"):
            return self._parent
        self._parent: Union["Element", None] = None
        parent_key = self._parentkey
        if parent_key is None:
            return self._parent
        structure = self.doc.structure
        if structure is None:
            return self._parent
        mcid = self.mcid
        if mcid is None:
            return self._parent
        parents = list_value(structure.parent_tree[parent_key])
        if mcid >= len(parents):
            log.warning(
                "Invalid marked content ID: %d (page has %d MCIDs)", mcid, len(parents)
            )
            return self._parent
        if parents[mcid] is None:  # This might mean we have the wrong StructParents
            log.warning(
                "Marked content ID %d on page_idx %d has no parent element",
                mcid,
                self.page.page_idx,
            )
            return self._parent
        self._parent = Element.from_dict(self.doc, dict_value(parents[mcid]))
        return self._parent

    @property
    def page(self) -> "Page":
        """The page containing this content object."""
        return _deref_page(self._pageref)

    @property
    def doc(self) -> "Document":
        """The document containing this content object."""
        docref, _ = self._pageref
        return _deref_document(docref)


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

    def __contains__(self, name: str) -> bool:
        return name in self.stream

    def __getitem__(self, name: str) -> PDFObject:
        return self.stream[name]

    def get(self, name: str, default: PDFObject = None) -> PDFObject:
        return self.stream.get(name, default)

    def __len__(self) -> int:
        """Even though you can __getitem__ from an image you cannot iterate
        over its keys, sorry about that.  Returns zero."""
        return 0

    @property
    def parent(self) -> Union["Element", None]:
        """The enclosing logical structure element, if any."""
        from playa.structure import Element

        if hasattr(self, "_parent"):
            return self._parent
        self._parent = None
        if self._parentkey is None:
            return self._parent
        # No structure, no parent!
        if self.doc.structure is None:
            return self._parent
        try:
            parent = resolve1(self.doc.structure.parent_tree[self._parentkey])
            if isinstance(parent, dict):
                self._parent = Element.from_dict(self.doc, parent)
            else:
                del self._parent
                return super().parent
        except IndexError:
            pass
        return self._parent

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
        return transform_bbox(self.ctm, (0, 0, 1, 1))


# Group XObject subtypes. As of PDF 2.0 Transparency is the only defined subtype
LITERAL_TRANSPARENCY = LIT("Transparency")


def _extract_mcid_texts(itor: Iterable[ContentObject]) -> Dict[int, List[str]]:
    """Get text for all MCIDs on a page or in a Form XObject"""
    mctext: Dict[int, List[str]] = {}
    for obj in itor:
        if not isinstance(obj, TextObject):
            continue
        mcs = obj.mcs
        if mcs is None or mcs.mcid is None:
            continue
        if "ActualText" in mcs.props:
            assert isinstance(mcs.props["ActualText"], bytes)
            chars = decode_text(mcs.props["ActualText"])
        else:
            chars = obj.chars
        # Remove soft hyphens
        chars = chars.replace("\xad", "")
        mctext.setdefault(mcs.mcid, []).append(chars)
    return mctext


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
      stream: Content stream with PDF operators.
      resources: Resources specific to this XObject, if any.
      group: Transparency group, if any.
    """

    xobjid: str
    stream: ContentStream
    resources: Union[None, Dict[str, PDFObject]]
    group: Union[None, Dict[str, PDFObject]]

    def __contains__(self, name: str) -> bool:
        return name in self.stream

    def __getitem__(self, name: str) -> PDFObject:
        return self.stream[name]

    @property
    def bbox(self) -> Rect:
        """Get the bounding box of this XObject in device space."""
        # It is a required attribute!
        if "BBox" not in self.stream:
            log.debug("XObject %r has no BBox: %r", self.xobjid, self.stream)
            return self.page.cropbox
        return transform_bbox(self.ctm, rect_value(self.stream["BBox"]))

    @property
    def buffer(self) -> bytes:
        """Raw stream content for this XObject"""
        return self.stream.buffer

    @property
    def tokens(self) -> Iterator[Token]:
        """Iterate over tokens in the XObject's content stream."""
        parser = ContentParser([self.stream], self.doc)
        while True:
            try:
                pos, tok = parser.nexttoken()
            except StopIteration:
                return
            yield tok

    @property
    def contents(self) -> Iterator[PDFObject]:
        """Iterator over PDF objects in the content stream."""
        for pos, obj in ContentParser([self.stream], self.doc):
            yield obj

    def __iter__(self) -> Iterator["ContentObject"]:
        from playa.interp import LazyInterpreter

        interp = LazyInterpreter(
            self.page,
            [self.stream],
            self.resources,
            ctm=self.ctm,
            gstate=self.gstate,
            # This is not really correct if this XObject has a
            # StructParent, *but* in that case the standard forbids
            # there to be any marked content sections inside it so
            # this should never get accessed anyway.
            parent_key=self._parentkey,
        )
        return iter(interp)

    @property
    def parent(self) -> Union["Element", None]:
        """The enclosing logical structure element, if any."""
        from playa.structure import Element

        if hasattr(self, "_parent"):
            return self._parent
        self._parent = None
        if self._parentkey is None:
            return self._parent
        # No structure, no parent!
        if self.doc.structure is None:
            return self._parent
        try:
            parent = resolve1(self.doc.structure.parent_tree[self._parentkey])
            if isinstance(parent, dict):
                self._parent = Element.from_dict(self.doc, parent)
            else:
                del self._parent
                return super().parent
        except IndexError:
            pass
        return self._parent

    @property
    def structure(self) -> "PageStructure":
        """Mapping of marked content IDs to logical structure elements.

        As with pages, Form XObjects can also contain their own
        mapping of marked content IDs to structure elements.
        """
        from playa.structure import PageStructure

        if hasattr(self, "_structmap"):
            return self._structmap
        self._structmap: PageStructure = PageStructure(self._pageref, [])
        if self.doc.structure is None:
            return self._structmap
        if self._parentkey is None:
            return self._structmap
        try:
            self._structmap = PageStructure(
                self._pageref, self.doc.structure.parent_tree[self._parentkey]
            )
        except IndexError as e:
            log.warning("Invalid StructParents: %r (%s)", self._parentkey, e)
        except TypeError:
            # This means that there is a single StructParent, and thus
            # no internal structure to this Form XObject
            pass
        return self._structmap

    @property
    def marked_content(self) -> Sequence[Union[None, Iterable["ContentObject"]]]:
        """Mapping of marked content IDs to iterators over content objects.

        These are the content objects associated with the structural
        elements in `XObjectObject.structure`.  So, for instance, you can do:

            for element, contents in zip(xobj.structure,
                                         xobj.marked_content):
                if element is not None:
                    if contents is not None:
                        for obj in contents:
                            ...  # do something with it

        Or you can also access the contents of a single element:

            if xobj.marked_content[mcid] is not None:
                for obj in xobj.marked_content[mcid]:
                    ... # do something with it

        Why do you have to check if it's `None`?  Because the values
        are not necessarily sequences (they may just be positions in
        the content stream), it isn't possible to know if they are
        empty without iterating over them, which you may or may not
        want to do, because you are Lazy.
        """
        from playa.interp import _make_contentmap

        if hasattr(self, "_marked_contents"):
            return self._marked_contents
        self._marked_contents: Sequence[Union[None, Iterable["ContentObject"]]] = (
            _make_contentmap(self)
        )
        return self._marked_contents

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

    @property
    def fonts(self) -> Mapping[str, Font]:
        """Mapping of resource names to fonts for this Form XObject.

        Note: This is not the same as `playa.Document.fonts`.
            The resource names (e.g. `F1`, `F42`, `FooBar`) here are
            specific to a page (or Form XObject) resource dictionary
            and have no relation to the font name as commonly
            understood (e.g. `Helvetica`,
            `WQERQE+Arial-SuperBold-HJRE-UTF-8`).  Since font names are
            generally considered to be globally unique, it may be
            possible to access fonts by them in the future.

        Danger: Do not rely on this being a `dict`.
            Currently this is implemented eagerly, but in the future it
            may return a lazy object which only loads fonts on demand.

        """
        from playa.interp import _make_fontmap

        if hasattr(self, "_fontmap"):
            return self._fontmap
        if self.resources is None or "Font" not in self.resources:
            self._fontmap: Dict[str, Font] = {}
        else:
            self._fontmap = _make_fontmap(self.resources["Font"], self.doc)
        return self._fontmap

    @classmethod
    def from_stream(
        cls,
        stream: ContentStream,
        page: "Page",
        xobjid: str,
        gstate: GraphicState,
        ctm: Matrix,
        mcstack: Tuple[MarkedContent, ...],
    ) -> "XObjectObject":
        """Create a new XObjectObject from a content stream."""
        if "Matrix" in stream:
            ctm = mult_matrix(matrix_value(stream["Matrix"]), ctm)
        # According to PDF reference 1.7 section 4.9.1, XObjects in
        # earlier PDFs (prior to v1.2) use the page's Resources entry
        # instead of having their own Resources entry.  So, this could
        # be None, in which case LazyInterpreter will fall back to
        # page.resources.
        xobjres = stream.get("Resources")
        resources = None if xobjres is None else dict_value(xobjres)
        xobjgrp = stream.get("Group")
        group = None if xobjgrp is None else dict_value(xobjgrp)
        # PDF 2.0, sec 11.6.6
        # Initial blend mode: Before execution of the transparency group
        # XObject’s content stream, the current blend mode in the graphics
        # state shall be initialised to Normal, the current stroking and
        # nonstroking alpha constants to 1.0, and the current soft mask to None
        if group and group.get("S") == LITERAL_TRANSPARENCY:
            # Need to copy here so as not to modify existing gstate,
            # unfortunately it will get copied again later...
            gstate = copy(gstate)
            gstate.blend_mode = LITERAL_NORMAL
            gstate.salpha = gstate.nalpha = 1
            gstate.smask = None
        # PDF 2.0, Table 359
        # At most one of [StructParent and StructParents] shall be
        # present in a given object. An object may be either a content
        # item in its entirety or a container for marked-content
        # sequences that are content items, but not both.
        if "StructParent" in stream:
            parent_key = int_value(stream["StructParent"])
        elif "StructParents" in stream:
            parent_key = int_value(stream["StructParents"])
        else:
            parent_key = None
        return cls(
            _pageref=page.pageref,
            _parentkey=parent_key,
            gstate=gstate,
            ctm=ctm,
            mcstack=mcstack,
            xobjid=xobjid,
            stream=stream,
            resources=resources,
            group=group,
        )


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
        return transform_bbox(self.ctm, bbox)


class TextBase(ContentObject):
    """Common properties for text and glyph objects."""

    @property
    @abstractmethod
    def matrix(self) -> Matrix: ...

    @property
    def font(self) -> Font:
        """Font for this text object."""
        font = self.gstate.font
        assert font is not None
        return font

    @property
    def size(self) -> float:
        """Font size for this text object.

        This is the actual font size in device space, which is **not**
        the same as `GraphicState.fontsize`.  That's the font size in
        text space which is not a very useful number (it's usually 1).
        """
        vert = False if self.gstate.font is None else self.gstate.font.vertical
        if vert:
            # dx, dy = apply_matrix_norm(self.matrix, (1, 0))
            dx, dy, _, _, _, _ = self.matrix
        else:
            # dx, dy = apply_matrix_norm(self.matrix, (0, 1))
            _, _, dx, dy, _, _ = self.matrix
        if dx == 0:  # Nearly always true
            return abs(dy)
        elif dy == 0:
            return abs(dx)
        else:
            import math

            return math.sqrt(dx * dx + dy * dy)

    @property
    def fontname(self) -> str:
        """Font name for this text object"""
        return self.font.fontname

    @property
    def fontbase(self) -> str:
        """Original font name for this text object.

        Fonts in PDF files are usually "subsetted", meaning only the
        glyphs actually used in the document are included.  In this
        case the font's `fontname` property usually consists of an
        arbitrary "tag", plus (literally, a `+`) and the original
        name.  This is a convenience property to get that original
        name.

        This is not the same as `GraphicState.font.basefont` which
        usually also includes the subset tag.

        """
        fontname = self.fontname
        subset, _, base = fontname.partition("+")
        if base:
            return base
        return fontname

    @property
    def textfont(self) -> str:
        """Convenient short form of the font name and size.

        For example, "Helvetica 12".
        """
        return f"{self.fontbase} {round(self.size)}"

    @property
    def origin(self) -> Point:
        """Origin of this text object in device space."""
        _, _, _, _, dx, dy = self.matrix
        return dx, dy


@dataclass
class GlyphObject(TextBase):
    """Individual glyph on the page.

    Attributes:
      font: Font for this glyph.
      size: Effective font size for this glyph.
      fontname: Font name.
      fontbase: Short (non-subset) font name.
      textfont: Combined short name and size for the font.
      cid: Character ID for this glyph.
      text: Unicode mapping of this glyph, if any.
      matrix: Rendering matrix `T_rm` for this glyph, which transforms
              text space coordinates to device space (PDF 2.0 section
              9.4.4).
      origin: Origin of this glyph in device space.
      displacement: Vector to the origin of the next glyph in device space.
      bbox: glyph bounding box in device space.

    """

    cid: int
    text: Union[str, None]
    _matrix: Matrix
    _displacement: float
    _corners: bool

    def __iter__(self) -> Iterator[ContentObject]:
        """Possibly iterate over paths in a glyph.

        For Type3 fonts, you can iterate over paths (or anything
        else) inside a glyph, in the coordinate space defined by the
        text rendering matrix.

        Otherwise, you can't do that, and you get nothing.
        """
        from playa.interp import Type3Interpreter

        font = self.font
        itor: Iterator[ContentObject] = iter(())
        if not isinstance(font, Type3Font):
            return itor
        gid = font.encoding.get(self.cid)
        if gid is None:
            log.warning("Unknown CID %d in Type3 font %r", self.cid, font)
            return itor
        charproc = resolve1(font.charprocs.get(gid))
        if not isinstance(charproc, ContentStream):
            log.warning("CharProc %s not found in font %r ", gid, font)
            return itor

        interp = Type3Interpreter(
            self.page,
            [charproc],
            font.resources,
            ctm=mult_matrix(font.matrix, self.matrix),
            # NOTE: no copy here because an interpreter always creates
            # a new graphics state.
            gstate=self.gstate,
        )
        itor = iter(interp)
        # TODO: We *could* try to get and use the d1 information here
        # but if we do that, we need to do it everywhere the glyph is
        # used so that the bbox will be consistent
        return itor

    @property
    def matrix(self) -> Matrix:
        return self._matrix

    @property
    def chars(self) -> str:
        return self.text or ""

    @property
    def displacement(self) -> Point:
        # Equivalent to:
        # apply_matrix_norm(self.matrix,
        #                   (0, self._displacement)
        #                   if font.vertical else
        #                   (self._displacement, 0))
        a, b, c, d, _, _ = self.matrix
        if self.font.vertical:
            return c * self._displacement, d * self._displacement
        else:
            return a * self._displacement, b * self._displacement

    @property
    def bbox(self) -> Rect:
        x0, y0, x1, y1 = self.font.char_bbox(self.cid)
        if self._corners:
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


@dataclass
class TextObject(TextBase):
    """Text object (contains one or more glyphs).

    Attributes:

      matrix: Initial rendering matrix `T_rm` for this text object,
              which transforms text space coordinates to device space
              (PDF 2.0 section 9.4.4).
      origin: Origin of this text object in device space.
      displacement: Vector to the origin of the next text object in
                    device space.
      font: Font for this text object.
      size: Effective font size for this text object.
      fontname: Font name.
      fontbase: Short (non-subset) font name.
      textfont: Combined short name and size for the font.
      text_matrix: Text matrix `T_m` for this text object, which
                   transforms text space coordinates to user space.
      line_matrix: Text line matrix `T_lm` for this text object, which
                   is the text matrix at the beginning of the "current
                   line" (PDF 2.0 section 9.4.1).  Note that this is
                   **not** reliable for detecting line breaks.
      scaling_matrix: The anonymous but rather important matrix which
                      applies font size, horizontal scaling and rise to
                      obtain the rendering matrix (PDF 2.0 sec 9.4.4).
      args: Strings or position adjustments.
      bbox: Text bounding box in device space.

    """

    args: List[Union[bytes, float]]
    line_matrix: Matrix
    _glyph_offset: Point

    _matrix: Union[Matrix, None] = None
    _chars: Union[List[str], None] = None
    _bbox: Union[Rect, None] = None
    _next_glyph_offset: Union[Point, None] = None
    _displacement: Union[Point, None] = None

    def __iter__(self) -> Iterator[GlyphObject]:
        """Generate glyphs for this text object"""
        glyph_offset = self._glyph_offset
        font = self.gstate.font
        # If no font is set, we cannot do anything, since even calling
        # TJ with a displacement and no text effects requires us at
        # least to know the fontsize.
        if font is None:
            log.warning(
                "No font is set, will not update text state or output text: %r TJ",
                self.args,
            )
            self._next_glyph_offset = glyph_offset
            return
        assert self.ctm is not None

        tlm_ctm = mult_matrix(self.line_matrix, self.ctm)
        # Pre-determine if we need to recompute the bound for rotated glyphs
        a, b, c, d, _, _ = tlm_ctm
        corners = b * d < 0 or a * c < 0
        fontsize = self.gstate.fontsize
        horizontal_scaling = self.gstate.scaling * 0.01
        # PDF 2.0 section 9.3.2: The character-spacing parameter, Tc,
        # shall be a number specified in unscaled text space units
        # (although it shall be subject to scaling by the Th parameter
        # if the writing mode is horizontal).
        if fontsize == 0.0:
            # A particular way of "hiding" text...
            scaled_charspace = scaled_wordspace = 0.0
        else:
            scaled_charspace = self.gstate.charspace / fontsize
            # Section 9.3.3: Word spacing "works the same way"
            scaled_wordspace = self.gstate.wordspace / fontsize

        # PDF 2.0 section 9.4.4: Conceptually, the entire
        # transformation from text space to device space can be
        # represented by a text rendering matrix, T_rm:
        #
        # (scaling_matrix @ text_matrix @ glyph.ctm)
        #
        # Note that scaling_matrix and text_matrix are constant across
        # glyphs in a TextObject, and scaling_matrix is always
        # diagonal (thus the mult_matrix call below can be optimized)
        scaling_matrix = (
            fontsize * horizontal_scaling,
            0,
            0,
            fontsize,
            0,
            self.gstate.rise,
        )
        vert = font.vertical
        # FIXME: THIS IS NOT TRUE!!!  We need a test for it though.
        if font.multibyte:
            scaled_wordspace = 0
        (x, y) = glyph_offset
        pos = y if vert else x
        for obj in self.args:
            if isinstance(obj, (int, float)):
                if vert:
                    pos -= obj * 0.001 * fontsize
                else:
                    pos -= obj * 0.001 * fontsize * horizontal_scaling
            else:
                for cid, text in font.decode(obj):
                    glyph_offset = (x, pos) if vert else (pos, y)
                    disp = font.vdisp(cid) if vert else font.hdisp(cid)
                    disp += scaled_charspace
                    if cid == 32:
                        disp += scaled_wordspace
                    matrix = mult_matrix(
                        scaling_matrix, translate_matrix(tlm_ctm, glyph_offset)
                    )
                    glyph = GlyphObject(
                        _pageref=self._pageref,
                        _parentkey=self._parentkey,
                        gstate=self.gstate,
                        ctm=self.ctm,
                        mcstack=self.mcstack,
                        cid=cid,
                        text=text,
                        _matrix=matrix,
                        _displacement=disp,
                        _corners=corners,
                    )
                    yield glyph
                    # This implements the proper scaling of charspace/wordspace
                    if vert:
                        pos += disp * fontsize
                    else:
                        pos += disp * fontsize * horizontal_scaling
        glyph_offset = (x, pos) if vert else (pos, y)
        if self._next_glyph_offset is None:
            self._next_glyph_offset = glyph_offset

    def _get_next_glyph_offset(self) -> Point:
        """Update only the glyph offset without calculating anything else."""
        if self._next_glyph_offset is not None:
            return self._next_glyph_offset
        self._next_glyph_offset = self._glyph_offset
        font = self.gstate.font
        if font is None:
            log.warning(
                "No font is set, will not update text state or output text: %r TJ",
                self.args,
            )
            return self._next_glyph_offset
        if len(self.args) == 0:
            return self._next_glyph_offset

        self._next_glyph_offset = update_glyph_offset(
            self._glyph_offset, font, self.gstate, self.args
        )
        return self._next_glyph_offset

    @property
    def matrix(self) -> Matrix:
        if self._matrix is not None:
            return self._matrix
        self._matrix = mult_matrix(
            self.scaling_matrix, mult_matrix(self.text_matrix, self.ctm)
        )
        return self._matrix

    @property
    def scaling_matrix(self) -> Matrix:
        horizontal_scaling = self.gstate.scaling * 0.01
        fontsize = self.gstate.fontsize
        return (
            fontsize * horizontal_scaling,
            0,
            0,
            fontsize,
            0,
            self.gstate.rise,
        )

    @property
    def text_matrix(self) -> Matrix:
        return translate_matrix(self.line_matrix, self._glyph_offset)

    @property
    def displacement(self) -> Point:
        if self._displacement is not None:
            return self._displacement
        matrix = self.matrix
        next_matrix = mult_matrix(
            self.scaling_matrix,
            mult_matrix(
                translate_matrix(self.line_matrix, self._get_next_glyph_offset()),
                self.ctm,
            ),
        )
        self._displacement = next_matrix[-2] - matrix[-2], next_matrix[-1] - matrix[-1]
        return self._displacement

    @property
    def bbox(self) -> Rect:
        # We specialize this to avoid it having side effects on the
        # text state (already it's a bit of a footgun that __iter__
        # does that...), but also because we know all glyphs have the
        # same text matrix and thus we can avoid a lot of multiply
        if self._bbox is not None:
            return self._bbox
        matrix = mult_matrix(self.line_matrix, self.ctm)
        font = self.gstate.font
        fontsize = self.gstate.fontsize
        rise = self.gstate.rise
        if font is None:
            log.warning(
                "No font is set, will not update text state or output text: %r TJ",
                self.args,
            )
            self._bbox = BBOX_NONE
            self._next_glyph_offset = self._glyph_offset
            return self._bbox
        if len(self.args) == 0:
            self._bbox = BBOX_NONE
            self._next_glyph_offset = self._glyph_offset
            return self._bbox

        horizontal_scaling = self.gstate.scaling * 0.01
        charspace = self.gstate.charspace
        wordspace = self.gstate.wordspace
        vert = font.vertical
        if font.multibyte:
            wordspace = 0
        (x, y) = self._glyph_offset
        pos = y if vert else x
        x0 = x1 = x
        y0 = y1 = y + rise
        fast_path = False
        if not vert:
            # Scale charspace and wordspace, PDF 2.0 section 9.3.2
            charspace *= horizontal_scaling
            wordspace *= horizontal_scaling
            # Detect the most frequent case, horizontal writing with
            # diagonal font.matrix
            a, b, c, d, e, f = font.matrix
            if b == 0 and c == 0:
                fast_path = True
                y0 += d * font.descent * fontsize
                y1 += d * font.ascent * fontsize
        for obj in self.args:
            if isinstance(obj, (int, float)):
                pos -= obj * 0.001 * fontsize * horizontal_scaling
            else:
                for cid, _ in font.decode(obj):
                    x, y = (x, pos) if vert else (pos, y)
                    if vert:
                        assert isinstance(font, CIDFont)
                        pos += font.vdisp(cid) * fontsize
                    else:
                        hdisp = font.hdisp(cid)
                        pos += hdisp * fontsize * horizontal_scaling
                    if fast_path:
                        x1 = pos
                    else:
                        gx0, gy0, gx1, gy1 = font.char_bbox(cid)
                        gx0 *= fontsize * horizontal_scaling
                        gx1 *= fontsize * horizontal_scaling
                        gy0 *= fontsize
                        gy0 += rise
                        gy1 *= fontsize
                        gy1 += rise
                        x0 = min(x0, x + gx0)
                        y0 = min(y0, y + gy0)
                        x1 = max(x1, x + gx1)
                        y1 = max(y1, y + gy1)
                    pos += charspace
                    if cid == 32:
                        pos += wordspace
        # Update this because we can!
        if self._next_glyph_offset is None:
            self._next_glyph_offset = (x, pos) if vert else (pos, y)
        self._bbox = transform_bbox(matrix, (x0, y0, x1, y1))
        return self._bbox

    @property
    def chars(self) -> str:
        """Get the Unicode characters (in stream order) for this object."""
        if self._chars is not None:
            return "".join(self._chars)
        self._chars = []
        font = self.gstate.font
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
        font = self.gstate.font
        assert font is not None, "No font was selected"
        for obj in self.args:
            if not isinstance(obj, bytes):
                continue
            nglyphs += sum(1 for _ in font.decode(obj))
        return nglyphs
