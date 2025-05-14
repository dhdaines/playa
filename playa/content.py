"""
PDF content objects created by the interpreter.
"""

import itertools
import logging
from dataclasses import dataclass
from typing import (
    TYPE_CHECKING,
    Dict,
    Iterator,
    List,
    Literal,
    NamedTuple,
    Tuple,
    Union,
)

from playa.color import (
    BASIC_BLACK,
    LITERAL_RELATIVE_COLORIMETRIC,
    PREDEFINED_COLORSPACE,
    Color,
    ColorSpace,
)
from playa.font import Font, CIDFont
from playa.parser import ContentParser, Token
from playa.pdftypes import (
    BBOX_NONE,
    ContentStream,
    Matrix,
    PDFObject,
    Point,
    PSLiteral,
    Rect,
    dict_value,
    matrix_value,
    rect_value,
)
from playa.utils import (
    apply_matrix_pt,
    get_bound,
    mult_matrix,
    transform_bbox,
    translate_matrix,
)
from playa.worker import PageRef, _deref_page

if TYPE_CHECKING:
    from playa.page import Page

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
    font: Union[Font, None] = None
    fontsize: float = 0
    charspace: float = 0
    wordspace: float = 0
    scaling: float = 100
    leading: float = 0
    render_mode: int = 0
    rise: float = 0


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
    def page(self) -> "Page":
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

    def __contains__(self, name: str) -> bool:
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
        return transform_bbox(self.ctm, (0, 0, 1, 1))


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

    def __contains__(self, name: str) -> bool:
        return name in self.stream

    def __getitem__(self, name: str) -> PDFObject:
        return self.stream[name]

    @property
    def page(self) -> "Page":
        """Get the page (if it exists, raising RuntimeError if not)."""
        return _deref_page(self._pageref)

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
        from playa.interp import LazyInterpreter

        interp = LazyInterpreter(
            self.page, [self.stream], self.resources, ctm=self.ctm, gstate=self.gstate
        )
        return iter(interp)

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
        if "Matrix" in stream:
            ctm = mult_matrix(matrix_value(stream["Matrix"]), ctm)
        # According to PDF reference 1.7 section 4.9.1, XObjects in
        # earlier PDFs (prior to v1.2) use the page's Resources entry
        # instead of having their own Resources entry.  So, this could
        # be None, in which case LazyInterpreter will fall back to
        # page.resources.
        xobjres = stream.get("Resources")
        resources = None if xobjres is None else dict_value(xobjres)
        return cls(
            _pageref=page.pageref,
            gstate=gstate,
            ctm=ctm,
            mcstack=mcstack,
            xobjid=xobjid,
            stream=stream,
            resources=resources,
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

    def __len__(self) -> int:
        """Number of segments (beware: not subpaths!)"""
        return len(self.raw_segments)

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


def _font_size(matrix: Matrix, vert: bool = False) -> float:
    if vert:
        # dx, dy = apply_matrix_norm(self.matrix, (1, 0))
        dx, dy, _, _, _, _ = matrix
    else:
        # dx, dy = apply_matrix_norm(self.matrix, (0, 1))
        _, _, dx, dy, _, _ = matrix
    if dx == 0:  # Nearly always true
        return abs(dy)
    elif dy == 0:
        return abs(dx)
    else:
        import math

        return math.sqrt(dx * dx + dy * dy)


@dataclass
class GlyphObject(ContentObject):
    """Individual glyph on the page.

    Attributes:
      font: Font for this glyph.
      size: Effective font size for this glyph.
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
    matrix: Matrix
    _displacement: float
    _corners: bool

    def __len__(self) -> int:
        """Fool! You cannot iterate over a GlyphObject!"""
        return 0

    @property
    def font(self) -> Font:
        font = self.gstate.font
        assert font is not None
        return font

    @property
    def size(self) -> float:
        vert = False if self.gstate.font is None else self.gstate.font.vertical
        return _font_size(self.matrix, vert)

    @property
    def origin(self) -> Point:
        _, _, _, _, dx, dy = self.matrix
        return dx, dy

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
class TextObject(ContentObject):
    """Text object (contains one or more glyphs).

    Attributes:

      matrix: Initial rendering matrix `T_rm` for this text object,
              which transforms text space coordinates to device space
              (PDF 2.0 section 9.4.4).
      origin: Origin of this text object in device space.
      size: Effective font size for this text object.
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
    _text_space_bbox: Union[Rect, None] = None
    _next_glyph_offset: Union[Point, None] = None

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
                pos -= obj * 0.001 * fontsize * horizontal_scaling
            else:
                for cid, text in font.decode(obj):
                    glyph_offset = (x, pos) if vert else (pos, y)
                    disp = font.vdisp(cid) if vert else font.char_width(cid)
                    disp += scaled_charspace
                    if cid == 32:
                        disp += scaled_wordspace
                    matrix = mult_matrix(
                        scaling_matrix, translate_matrix(tlm_ctm, glyph_offset)
                    )
                    glyph = GlyphObject(
                        _pageref=self._pageref,
                        gstate=self.gstate,
                        ctm=self.ctm,
                        mcstack=self.mcstack,
                        cid=cid,
                        text=text,
                        matrix=matrix,
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

    def _calculate_scaled_text_space_bbox(self):
        if self._text_space_bbox is not None:
            return self._text_space_bbox
        font = self.gstate.font
        fontsize = self.gstate.fontsize
        rise = self.gstate.rise
        if font is None:
            log.warning(
                "No font is set, will not update text state or output text: %r TJ",
                self.args,
            )
            self._text_space_bbox = BBOX_NONE
            self._next_glyph_offset = self._glyph_offset
            return self._text_space_bbox
        if len(self.args) == 0:
            self._text_space_bbox = BBOX_NONE
            self._next_glyph_offset = self._glyph_offset
            return self._text_space_bbox
        descent = font.get_descent() * fontsize
        ascent = font.get_ascent() * fontsize
        horizontal_scaling = self.gstate.scaling * 0.01
        charspace = self.gstate.charspace
        wordspace = self.gstate.wordspace
        vert = font.vertical
        if font.multibyte:
            wordspace = 0
        (x, y) = self._glyph_offset
        pos = y if vert else x
        if vert:
            # Because the position vector can be anything for vertical
            # writing, none of these can be fixed even if we ignore
            # glyph-specific width, ascent and descent.
            x0 = x1 = x
            y0 = y1 = y
        else:
            x0 = x1 = x
            # In horizontal writing by contrast the baseline never
            # changes, and by convention, even though it's quite
            # incorrect, we use the descent and rise for the text and
            # glyph bounding box.  This means y0 and y1 are fixed.
            y0 = y + descent + rise
            y1 = y + ascent + rise
            # Scale charspace and wordspace, PDF 2.0 section 9.3.2
            charspace *= horizontal_scaling
            wordspace *= horizontal_scaling
        for obj in self.args:
            if isinstance(obj, (int, float)):
                pos -= obj * 0.001 * fontsize * horizontal_scaling
            else:
                for cid, _ in font.decode(obj):
                    x, y = (x, pos) if vert else (pos, y)
                    width = font.char_width(cid)
                    if vert:
                        assert isinstance(font, CIDFont)
                        adv = font.vdisp(cid) * fontsize
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
                    else:
                        adv = width * fontsize * horizontal_scaling
                        x1 = x + adv
                    pos += adv
                    pos += charspace
                    if cid == 32:
                        pos += wordspace
        if self._next_glyph_offset is None:
            self._next_glyph_offset = (x, pos) if vert else (pos, y)
        self._text_space_bbox = (x0, y0, x1, y1)
        return self._text_space_bbox

    def _get_next_glyph_offset(self) -> Point:
        if self._next_glyph_offset is not None:
            return self._next_glyph_offset
        self._calculate_scaled_text_space_bbox()
        assert self._next_glyph_offset is not None
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
    def size(self) -> float:
        vert = False if self.gstate.font is None else self.gstate.font.vertical
        return _font_size(self.matrix, vert)

    @property
    def scaling_matrix(self):
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
    def origin(self) -> Point:
        _, _, _, _, dx, dy = self.matrix
        return dx, dy

    @property
    def bbox(self) -> Rect:
        # We specialize this to avoid it having side effects on the
        # text state (already it's a bit of a footgun that __iter__
        # does that...), but also because we know all glyphs have the
        # same text matrix and thus we can avoid a lot of multiply
        if self._bbox is not None:
            return self._bbox
        matrix = mult_matrix(self.line_matrix, self.ctm)
        self._bbox = transform_bbox(matrix, self._calculate_scaled_text_space_bbox())
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
