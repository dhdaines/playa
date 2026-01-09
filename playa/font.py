"""Font metrics and descriptors

Danger: API subject to change.
    These APIs are unstable and subject to revision before PLAYA 1.0.
"""

import logging
import re
import struct
from io import BytesIO
from pathlib import Path
from typing import (
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Tuple,
    Union,
)

from playa.cmapdb import (
    CMap,
    CMapBase,
    CMapDB,
    ToUnicodeMap,
    UnicodeMap,
    parse_encoding,
    parse_tounicode,
)
from playa.encodingdb import (
    EncodingDB,
    cid2unicode_from_encoding,
)
from playa.encodings import (
    SYMBOL_BUILTIN_ENCODING,
    ZAPFDINGBATS_BUILTIN_ENCODING,
    LITERAL_STANDARD_CID2UNICODE,
)
from playa.fontmetrics import FONT_METRICS
from playa.fontprogram import CFFFontProgram, TrueTypeFontProgram, Type1FontHeaderParser
from playa.parser import (
    LIT,
    PDFObject,
    PSLiteral,
    literal_name,
)
from playa.pdftypes import (
    ContentStream,
    Matrix,
    Rect,
    dict_value,
    int_value,
    list_value,
    matrix_value,
    num_value,
    point_value,
    rect_value,
    resolve1,
    stream_value,
)
from playa.utils import (
    Point,
    choplist,
    decode_text,
    transform_bbox,
    IDENTITY_MAPPING,
)

log = logging.getLogger(__name__)
LITERAL_STANDARD_ENCODING = LIT("StandardEncoding")
LITERAL_CIDFONT_TYPE0 = LIT("CIDFontType0")


class Font:
    vertical: bool = False
    multibyte: bool = False
    encoding: Dict[int, str]

    def __init__(
        self,
        descriptor: Dict[str, PDFObject],
        widths: Dict[int, float],
        default_width: Optional[float] = None,
    ) -> None:
        self.descriptor = descriptor
        self.widths = widths
        fontname = resolve1(descriptor.get("FontName"))
        if isinstance(fontname, PSLiteral):
            self.fontname = literal_name(fontname)
        elif isinstance(fontname, bytes):
            self.fontname = decode_text(fontname)
        else:
            self.fontname = "unknown"
        self.basefont = self.fontname
        self.flags = int_value(descriptor.get("Flags", 0))
        # Default values based on default DW2 metrics
        self.ascent = num_value(descriptor.get("Ascent", 880))
        self.descent = num_value(descriptor.get("Descent", -120))
        self.italic_angle = num_value(descriptor.get("ItalicAngle", 0))
        if default_width is None:
            self.default_width = num_value(descriptor.get("MissingWidth", 1000))
        else:
            self.default_width = default_width
        self.leading = num_value(descriptor.get("Leading", 0))
        if "FontBBox" in descriptor:
            self.bbox = rect_value(descriptor["FontBBox"])
        else:
            self.bbox = (0, 0, 0, 0)
        self.matrix: Matrix = (0.001, 0, 0, 0.001, 0, 0)

        # PDF RM 9.8.1 specifies /Descent should always be a negative number.
        # PScript5.dll seems to produce Descent with a positive number, but
        # text analysis will be wrong if this is taken as correct. So force
        # descent to negative.
        if self.descent > 0:
            self.descent = -self.descent
        # NOTE: A Type3 font *can* have positive descent because the
        # FontMatrix might be flipped, this is handled in the subclass
        # (but also, we ignore ascent and descent on Type3 fonts)

        # For some unknown reason sometimes Ascent and Descent are
        # both zero, in which case set them from the bbox.
        if self.ascent == 0 and self.descent == 0:
            _, self.descent, _, self.ascent = self.bbox

    def __repr__(self) -> str:
        return "<Font>"

    def decode(self, data: bytes) -> Iterable[Tuple[int, str]]:
        # Default to an Identity map
        log.debug("decode with identity: %r", data)
        return ((cid, chr(cid)) for cid in data)

    def hdisp(self, cid: int) -> float:
        """Get the horizontal displacement (so-called "width") of a character
        from its CID."""
        width = self.widths.get(cid, self.default_width)
        return self.matrix[0] * width

    def vdisp(self, cid: int) -> float:
        """Get vertical displacement for vertical writing mode, in
        text space units.

        This is always 0 for simple fonts as they have no vertical
        writing mode.

        """
        return 0

    def position(self, cid: int) -> Tuple[float, float]:
        """Get position vector for vertical writing mode, in text
        space units.

        This is always `[0 0]` for simple fonts as they have no
        vertical writing mode.
        """
        return (0, 0)

    def char_bbox(self, cid: int) -> Rect:
        """Get the standard bounding box for a character from its CID.

        This is, very specifically, `[0 descent width ascent]` in text
        space units.

        Danger: Not the actual bounding box of the glyph.
            This is a standardized bounding box for use in text
            extraction and layout analysis.  It does not correspond to
            the actual bounding box of an individual glyph as
            specified by the font program.
        """
        width = self.widths.get(cid, self.default_width)
        # We know the matrix is diagonal
        a, _, _, d, _, _ = self.matrix
        return (0, d * self.descent, a * width, d * self.ascent)

    def write_fontfile(self, outdir: Path) -> Optional[Path]:
        for suffix, key in (
            (".pfa", "FontFile"),
            (".ttf", "FontFile2"),
            (".cff", "FontFile3"),
        ):
            if key in self.descriptor:
                fontfile = resolve1(self.descriptor[key])
                if not isinstance(fontfile, ContentStream):
                    log.warning("%s is not a content stream", key)
                    continue
                fontname = re.sub(r"[^\w\+]", "", self.fontname)
                outpath = outdir / (fontname + suffix)
                outpath.write_bytes(fontfile.buffer)
                return outpath
        return None


class SimpleFont(Font):
    def __init__(
        self,
        descriptor: Dict[str, PDFObject],
        widths: Dict[int, float],
        spec: Dict[str, PDFObject],
    ) -> None:
        # Font encoding is specified either by a name of
        # built-in encoding or a dictionary that describes
        # the differences.
        base = None
        diff = None
        if "Encoding" in spec:
            encoding = resolve1(spec["Encoding"])
            if isinstance(encoding, dict):
                base = encoding.get("BaseEncoding")
                diff = list_value(encoding.get("Differences", []))
            elif isinstance(encoding, PSLiteral):
                base = encoding
            else:
                log.warning("Encoding is neither a dictionary nor a name: %r", encoding)
        if base is None:
            base = self.get_implicit_encoding(descriptor)
        self.encoding = EncodingDB.get_encoding(base, diff)
        self._cid2unicode = cid2unicode_from_encoding(self.encoding)
        self.tounicode: Optional[ToUnicodeMap] = None
        if "ToUnicode" in spec:
            strm = resolve1(spec["ToUnicode"])
            if isinstance(strm, ContentStream):
                self.tounicode = parse_tounicode(strm.buffer)
                if self.tounicode.code_lengths != [1]:
                    log.debug(
                        "Technical Note #5144 Considered Harmful: A simple font's "
                        "code space must be single-byte, not %r",
                        self.tounicode.code_space,
                    )
                    self.tounicode.code_lengths = [1]
                    self.tounicode.code_space = [(b"\x00", b"\xff")]
                log.debug("ToUnicode: %r", vars(self.tounicode))
            else:
                log.warning("ToUnicode is not a content stream: %r", strm)
        # Make sure we have some way to extract text
        if self._cid2unicode == {} and self.tounicode is None:
            log.warning(
                "Using StandardEncoding for cid2unicode as "
                "Encoding has no meaningful glyphs: %r",
                self.encoding,
            )
            self._cid2unicode = LITERAL_STANDARD_CID2UNICODE
        Font.__init__(self, descriptor, widths)

    def get_implicit_encoding(
        self, descriptor: Dict[str, PDFObject]
    ) -> Union[PSLiteral, Dict[int, str], None]:
        raise NotImplementedError()

    def decode(self, data: bytes) -> Iterable[Tuple[int, str]]:
        if self.tounicode is not None:
            log.debug("decode with ToUnicodeMap: %r", data)
            return zip(data, self.tounicode.decode(data))
        else:
            log.debug("decode with Encoding: %r", data)
            return ((cid, self._cid2unicode.get(cid, "")) for cid in data)


def get_basefont(spec: Dict[str, PDFObject]) -> str:
    if "BaseFont" in spec:
        basefont = resolve1(spec["BaseFont"])
        if isinstance(basefont, PSLiteral):
            return basefont.name
        elif isinstance(basefont, bytes):
            return decode_text(basefont)
    log.warning("Missing or unrecognized BaseFont: %r", spec)
    return "unknown"


class Type1Font(SimpleFont):
    char_widths: Union[Dict[str, int], None] = None

    def __init__(self, spec: Dict[str, PDFObject]) -> None:
        self.basefont = get_basefont(spec)
        widths: Dict[int, float]
        if self.basefont in FONT_METRICS:
            (descriptor, self.char_widths) = FONT_METRICS[self.basefont]
            widths = {}
        else:
            descriptor = dict_value(spec.get("FontDescriptor", {}))
            firstchar = int_value(spec.get("FirstChar", 0))
            # lastchar = int_value(spec.get('LastChar', 255))
            width_list = list_value(spec.get("Widths", [0] * 256))
            widths = {i + firstchar: num_value(w) for (i, w) in enumerate(width_list)}
        SimpleFont.__init__(self, descriptor, widths, spec)

    def get_implicit_encoding(
        self, descriptor: Dict[str, PDFObject]
    ) -> Union[PSLiteral, Dict[int, str], None]:
        # PDF 1.7 Table 114: For a font program that is embedded in
        # the PDF file, the implicit base encoding shall be the font
        # program’s built-in encoding.
        if "FontFile" in descriptor:
            self.fontfile = stream_value(descriptor.get("FontFile"))
            length1 = int_value(self.fontfile["Length1"])
            data = self.fontfile.buffer[:length1]
            parser = Type1FontHeaderParser(data)
            return parser.get_encoding()
        elif "FontFile3" in descriptor:
            self.fontfile3 = stream_value(descriptor.get("FontFile3"))
            try:
                cfffont = CFFFontProgram(self.basefont, BytesIO(self.fontfile3.buffer))
                assert not cfffont.is_cidfont
                return cfffont.code2name
            except AssertionError:
                log.warning(
                    "Embedded CFFFont %r for Type1 font is a CIDFont", self.fontfile3
                )
                return LITERAL_STANDARD_ENCODING
            except Exception:
                log.debug("Failed to parse CFFFont %r", self.fontfile3, exc_info=True)
                return LITERAL_STANDARD_ENCODING
        elif self.basefont == "Symbol":
            # FIXME: This (and zapf) can be obtained from the AFM files
            return SYMBOL_BUILTIN_ENCODING
        elif self.basefont == "ZapfDingbats":
            return ZAPFDINGBATS_BUILTIN_ENCODING
        else:
            # PDF 1.7 Table 114: Otherwise, for a nonsymbolic font, it
            # shall be StandardEncoding, and for a symbolic font, it
            # shall be the font's built-in encoding (see FIXME above)
            return LITERAL_STANDARD_ENCODING

    def _glyph_space_width(self, cid: int) -> float:
        # Commit 6e4f36d <- what's the purpose of this? seems very cursed
        # reverting this would make #76 easy to fix since cid2unicode would only be
        # needed when ToUnicode is absent
        #
        # Answer: It exists entirely to support core fonts with a
        # custom Encoding defined over them (accented characters for
        # example).  The correct fix is to redo the AFM parsing to:
        #
        # - Get the implicit encoding (it's usually LITERAL_STANDARD_ENCODING)
        # - Index the widths by glyph names, not encoding values
        # - As a treat, we can also get the encodings for Symbol and ZapfDingbats
        #
        # Then we can construct `self.widths` directly using `self.encoding`.
        if self.char_widths is not None:
            if cid not in self._cid2unicode:
                return self.default_width
            return self.char_widths.get(self._cid2unicode[cid], self.default_width)
        return self.widths.get(cid, self.default_width)

    def hdisp(self, cid: int) -> float:
        """Get the horizontal displacement (so-called "width") of a character
        from its CID."""
        return self.matrix[0] * self._glyph_space_width(cid)

    def char_bbox(self, cid: int) -> Rect:
        """Get the standard bounding box for a character from its CID.

        This is, very specifically, `[0 descent width ascent]` in text
        space units.

        Danger: Not the actual bounding box of the glyph.
            This is a standardized bounding box for use in text
            extraction and layout analysis.  It does not correspond to
            the actual bounding box of an individual glyph as
            specified by the font program.
        """
        width = self._glyph_space_width(cid)
        # We know the matrix is diagonal
        a, _, _, d, _, _ = self.matrix
        return (0, d * self.descent, a * width, d * self.ascent)

    def __repr__(self) -> str:
        return "<Type1Font: basefont=%r>" % self.basefont


class TrueTypeFont(SimpleFont):
    def __init__(self, spec: Dict[str, PDFObject]) -> None:
        self.basefont = get_basefont(spec)
        widths: Dict[int, float]
        descriptor = dict_value(spec.get("FontDescriptor", {}))
        firstchar = int_value(spec.get("FirstChar", 0))
        # lastchar = int_value(spec.get('LastChar', 255))
        width_list = list_value(spec.get("Widths", [0] * 256))
        widths = {i + firstchar: num_value(w) for (i, w) in enumerate(width_list)}
        SimpleFont.__init__(self, descriptor, widths, spec)

    def get_implicit_encoding(
        self, descriptor: Dict[str, PDFObject]
    ) -> Union[PSLiteral, Dict[int, str], None]:
        is_non_symbolic = 32 & int_value(descriptor.get("Flags", 0))
        # For symbolic TrueTypeFont, the map cid -> glyph does not actually go through glyph name
        # making extracting unicode impossible??
        return LITERAL_STANDARD_ENCODING if is_non_symbolic else None

    def __repr__(self) -> str:
        return "<TrueTypeFont: basefont=%r>" % self.basefont


class Type3Font(SimpleFont):
    def __init__(self, spec: Dict[str, PDFObject]) -> None:
        firstchar = int_value(spec.get("FirstChar", 0))
        # lastchar = int_value(spec.get('LastChar', 0))
        width_list = list_value(spec.get("Widths", [0] * 256))
        widths = {i + firstchar: num_value(w) for (i, w) in enumerate(width_list)}
        descriptor = dict_value(spec.get("FontDescriptor", {}))
        SimpleFont.__init__(self, descriptor, widths, spec)
        # Type 3 fonts don't have a BaseFont in their font dictionary
        # and generally don't have a FontName in their descriptor
        # (https://github.com/pdf-association/pdf-issues/issues/11) as
        # they aren't considered to be subsettable, so we should just
        # look at Name to get their name and ignore whatever
        # SimpleFont.__init__ tells us
        fontname = resolve1(descriptor.get("FontName", spec.get("Name")))
        if isinstance(fontname, PSLiteral):
            self.fontname = fontname.name
        elif isinstance(fontname, bytes):
            self.fontname = decode_text(fontname)
        else:
            self.fontname = "unknown"
        self.basefont = self.fontname
        # Get the character definitions so we can interpret them
        self.charprocs = dict_value(spec.get("CharProcs", {}))
        # Get font-specific resources (FIXME: There is a huge amount
        # of ambiguity surrounding resources in Type3 fonts, see
        # https://github.com/pdf-association/pdf-issues/issues/128)
        resources = resolve1(spec.get("Resources"))
        self.resources: Union[None, Dict[str, PDFObject]] = (
            None if resources is None else dict_value(resources)
        )
        if "FontMatrix" in spec:  # it is actually required though
            self.matrix = matrix_value(spec["FontMatrix"])
        else:
            self.matrix = (0.001, 0, 0, 0.001, 0, 0)
        # FontBBox is in the font dictionary for Type 3 fonts
        if "FontBBox" in spec:  # it is also required though
            self.bbox = rect_value(spec["FontBBox"])
            # otherwise it was set in SimpleFont.__init__

        # Set ascent/descent from the bbox (they *could* be in the
        # descriptor but this is very unlikely, and then, they might
        # also both be zero, which is bad)
        _, self.descent, _, self.ascent = self.bbox

    def get_implicit_encoding(
        self, descriptor: Dict[str, PDFObject]
    ) -> Union[PSLiteral, Dict[int, str], None]:
        # PDF 1.7 sec 9.6.6.3: A Type 3 font’s mapping from character
        # codes to glyph names shall be entirely defined by its
        # Encoding entry, which is required in this case.
        return {}

    def char_bbox(self, cid: int) -> Rect:
        """Get the standard bounding box for a character from its CID.

        This is the smallest rectangle enclosing [0 descent width
        ascent] after the font matrix has been applied.

        Danger: Not the actual bounding box of the glyph (but almost).
            The descent and ascent here are from the **font** and not
            from the individual **glyph** so this will be somewhat
            larger than the actual bounding box.
        """
        width = self.widths.get(cid, self.default_width)
        return transform_bbox(self.matrix, (0, self.descent, width, self.ascent))

    def __repr__(self) -> str:
        return "<Type3Font>"


# Mapping of cmap names. Original cmap name is kept if not in the mapping.
# (missing reference for why DLIdent is mapped to Identity)
IDENTITY_ENCODER = {
    "DLIdent-H": "Identity-H",
    "DLIdent-V": "Identity-V",
}


def _get_widths(seq: Iterable[PDFObject]) -> Dict[int, float]:
    """Build a mapping of character widths for horizontal writing."""
    widths: Dict[int, float] = {}
    r: List[float] = []
    for v in seq:
        if isinstance(v, list):
            if r:
                char1 = r[-1]
                for i, w in enumerate(v):
                    widths[int_value(char1) + i] = num_value(w)
                r = []
        elif isinstance(v, (int, float)):
            r.append(v)
            if len(r) == 3:
                (char1, char2, w) = r
                for i in range(int_value(char1), int_value(char2) + 1):
                    widths[i] = num_value(w)
                r = []
    return widths


def _get_widths2(seq: Iterable[PDFObject]) -> Dict[int, Tuple[float, Point]]:
    """Build a mapping of character widths for vertical writing."""
    widths: Dict[int, Tuple[float, Point]] = {}
    r: List[float] = []
    for v in seq:
        if isinstance(v, list):
            if r:
                char1 = r[-1]
                for i, (w, vx, vy) in enumerate(choplist(3, v)):
                    widths[int(char1) + i] = (
                        num_value(w),
                        (num_value(vx), num_value(vy)),
                    )
                r = []
        elif isinstance(v, (int, float)):
            r.append(v)
            if len(r) == 5:
                (char1, char2, w, vx, vy) = r
                for i in range(int(char1), int(char2) + 1):
                    widths[i] = (
                        num_value(w),
                        (num_value(vx), num_value(vy)),
                    )
                r = []
    return widths


class CIDFont(Font):
    default_vdisp: float

    def __init__(
        self,
        spec: Dict[str, PDFObject],
    ) -> None:
        self.spec = spec
        self.subtype = resolve1(spec.get("Subtype"))
        self.basefont = get_basefont(spec)
        self.cidsysteminfo = dict_value(spec.get("CIDSystemInfo", {}))
        # These are *supposed* to be ASCII (PDF 1.7 section 9.7.3),
        # but for whatever reason they are sometimes UTF-16BE
        cid_registry = resolve1(self.cidsysteminfo.get("Registry"))
        if isinstance(cid_registry, bytes):
            regstr = decode_text(cid_registry).strip()
        else:
            regstr = "unknown"
        cid_ordering = resolve1(self.cidsysteminfo.get("Ordering"))
        if isinstance(cid_ordering, bytes):
            ordstr = decode_text(cid_ordering).strip()
        else:
            ordstr = "unknown"
        self.cidcoding = f"{regstr}-{ordstr}"
        self.cmap: CMapBase = self.get_cmap_from_spec(spec)

        try:
            descriptor = dict_value(spec["FontDescriptor"])
        except KeyError:
            log.warning("Font spec is missing FontDescriptor: %r", spec)
            descriptor = {}
        self.tounicode: Optional[ToUnicodeMap] = None
        self.unicode_map: Optional[UnicodeMap] = None
        # Since None is equivalent to an identity map, avoid warning
        # in the case where there was some kind of explicit Identity
        # mapping (even though this is absolutely not standards compliant)
        identity_map = False
        # First try to use an explicit ToUnicode Map
        if "ToUnicode" in spec:
            if "Encoding" in spec and spec["ToUnicode"] == spec["Encoding"]:
                log.debug(
                    "ToUnicode and Encoding point to the same object, using an "
                    "identity mapping for Unicode instead of this nonsense: %r",
                    spec["ToUnicode"],
                )
                identity_map = True
            elif isinstance(spec["ToUnicode"], ContentStream):
                strm = stream_value(spec["ToUnicode"])
                log.debug("Parsing ToUnicode from stream %r", strm)
                self.tounicode = parse_tounicode(strm.buffer)
            # If there is no stream, consider it an Identity mapping
            elif (
                isinstance(spec["ToUnicode"], PSLiteral)
                and "Identity" in spec["ToUnicode"].name
            ):
                log.debug("Using identity mapping for ToUnicode %r", spec["ToUnicode"])
                identity_map = True
            else:
                log.warning("Unparseable ToUnicode in %r", spec)
        # If there is no ToUnicode, then try TrueType font tables
        elif "FontFile2" in descriptor:
            self.fontfile = stream_value(descriptor.get("FontFile2"))
            log.debug("Parsing ToUnicode from TrueType font %r", self.fontfile)
            # FIXME: Utterly gratuitous use of BytesIO
            ttf = TrueTypeFontProgram(self.basefont, BytesIO(self.fontfile.buffer))
            self.tounicode = ttf.create_tounicode()
        # Or try to get a predefined UnicodeMap (not to be confused
        # with a ToUnicodeMap)
        if self.tounicode is None:
            try:
                self.unicode_map = CMapDB.get_unicode_map(
                    self.cidcoding,
                    self.cmap.is_vertical(),
                )
            except KeyError:
                pass
        if self.unicode_map is None and self.tounicode is None and not identity_map:
            log.debug(
                "Unable to find/create/guess unicode mapping for CIDFont, "
                "using identity mapping: %r",
                spec,
            )
        # FIXME: Verify that self.tounicode's code space corresponds
        # to self.cmap (this is actually quite hard because the code
        # spaces have been lost in the precompiled CMaps...)

        widths = _get_widths(list_value(spec.get("W", [])))
        if "DW" in spec:
            default_width = num_value(spec["DW"])
        else:
            default_width = 1000
        self.vertical = self.cmap.is_vertical()
        if self.vertical:
            if "DW2" in spec:
                (vy, w1) = point_value(spec["DW2"])
            else:
                # seemingly arbitrary values, but found in PDF 2.0 Table 115
                vy = 880  # vertical component of position vector
                w1 = -1000  # default vertical displacement
            self.default_position = (default_width / 2, vy)
            # The horizontal displacement is *always* zero (PDF 2.0
            # sec 9.7.4.3) so we only store the vertical.
            self.default_vdisp = w1
            # Glyph-specific vertical displacement and position vectors if any
            self.positions = {}
            self.vdisps = {}
            if "W2" in spec:
                for cid, (w1, (vx, vy)) in _get_widths2(list_value(spec["W2"])).items():
                    self.positions[cid] = (vx, vy)
                    self.vdisps[cid] = w1
        else:
            self.default_position = (0, 0)
            self.default_vdisp = 0
            self.positions = {}
            self.vdisps = {}

        Font.__init__(self, descriptor, widths, default_width=default_width)

    @property
    def cid2gid(self) -> Optional[Mapping[int, int]]:
        """According to PDF 2.0 Sec 9.7.4.2 Glyph selection in CIDFonts:
        The CID to glyph id mapping, or None in the case of external TrueType
        font program (Type2 CIDFont), because "...In this case, CIDs shall not
        participate in glyph selection..."
        Note that this is not exactly equivalent to the CIDToGIDMap entry,
        despite what the name might suggest.
        """
        if "FontFile2" in self.descriptor:
            # Type 2, embedded
            cid2gidmap = resolve1(self.spec.get("CIDToGIDMap"))
            if isinstance(cid2gidmap, ContentStream):
                buffer = cid2gidmap.buffer
                return dict(
                    enumerate(struct.unpack(">" + "H" * (len(buffer) // 2), buffer))
                )
            else:
                return IDENTITY_MAPPING
        elif "FontFile3" in self.descriptor:
            # Type 0, embedded
            try:
                fontfile3 = stream_value(self.descriptor.get("FontFile3"))
                cfffont = CFFFontProgram(self.basefont, BytesIO(fontfile3.buffer))
                return cfffont.cid2gid if cfffont.is_cidfont else IDENTITY_MAPPING
            except Exception:
                log.debug("Failed to parse CFFFont %r", fontfile3, exc_info=True)
                return IDENTITY_MAPPING
        elif self.subtype == LITERAL_CIDFONT_TYPE0:
            # Type 0, external
            return IDENTITY_MAPPING
        else:
            # Type 2, external
            return None

    def get_cmap_from_spec(self, spec: Dict[str, PDFObject]) -> CMapBase:
        """Get cmap from font specification

        For certain PDFs, Encoding Type isn't mentioned as an attribute of
        Encoding but as an attribute of CMapName, where CMapName is an
        attribute of spec['Encoding'].
        The horizontal/vertical modes are mentioned with different name
        such as 'DLIdent-H/V','OneByteIdentityH/V','Identity-H/V'.
        """
        cmap_name = self._get_cmap_name(spec)

        try:
            return CMapDB.get_cmap(cmap_name)
        except KeyError as e:
            # Parse an embedded CMap if necessary
            if isinstance(spec["Encoding"], ContentStream):
                strm = stream_value(spec["Encoding"])
                return parse_encoding(strm.buffer)
            else:
                log.warning("Failed to get cmap %s: %s", cmap_name, e)
                return CMap()

    @staticmethod
    def _get_cmap_name(spec: Dict[str, PDFObject]) -> str:
        """Get cmap name from font specification"""
        cmap_name = "unknown"  # default value
        try:
            spec_encoding = resolve1(spec["Encoding"])
            if spec_encoding is not None:
                cmap_name = literal_name(spec_encoding)
            else:
                spec_encoding = resolve1(spec["CMapName"])
                if spec_encoding is not None:
                    cmap_name = literal_name(spec_encoding)
        except KeyError:
            log.warning("Font spec is missing Encoding: %r", spec)
        except TypeError:
            log.warning("Font spec has invalid Encoding: %r", spec)
        return IDENTITY_ENCODER.get(cmap_name, cmap_name)

    def decode(self, data: bytes) -> Iterable[Tuple[int, str]]:
        if self.tounicode is not None:
            log.debug("decode with ToUnicodeMap: %r", data)
            # FIXME: Should verify that the codes are actually the
            # same (or just trust the codes that come from the cmap)
            return zip(
                (cid for _, cid in self.cmap.decode(data)), self.tounicode.decode(data)
            )
        elif self.unicode_map is not None:
            log.debug("decode with UnicodeMap: %r", data)
            return (
                (cid, self.unicode_map.get_unichr(cid))
                for (_, cid) in self.cmap.decode(data)
            )
        else:
            log.debug("decode with identity unicode map: %r", data)
            return (
                (cid, chr(int.from_bytes(substr, "big")))
                for substr, cid in self.cmap.decode(data)
            )

    def __repr__(self) -> str:
        return f"<CIDFont: basefont={self.basefont!r}, cidcoding={self.cidcoding!r}>"

    def vdisp(self, cid: int) -> float:
        """Get vertical displacement for vertical writing mode, in
        text space units.

        Returns 0 for horizontal writing, for obvious reasons.
        """
        return self.matrix[3] * self.vdisps.get(cid, self.default_vdisp)

    def position(self, cid: int) -> Tuple[float, float]:
        """Get position vector for vertical writing mode, in text
        space units.

        This is quite ill-defined in the PDF standard (PDF 2.0 Figure
        55), but basically it specifies a translation of the glyph
        with respect to the origin.  It is *subtracted* from that
        origin to give the glyph position.  So if your text matrix is
        `[1 0 0 1 100 100]`, and your font size is `10`, a position
        vector of `[500 200]` will place the origin of the glyph in
        glyph space at `[-500 -200]`, which becomes `[-.5 -.2]` in
        text space, then `[-5 -2]` after applying the font size, thus
        the glyph is painted with its origin at `[95 98]`.

        Yes, the horizontal scaling factor **does** apply to the
        horizontal component of the position vector, even if some PDF
        viewers don't think so.

        For horizontal writing, it is obviously (0, 0).

        """
        vx, vy = self.positions.get(cid, self.default_position)
        # We know that the matrix is diagonal here
        a, _, _, d, _, _ = self.matrix
        return a * vx, d * vy

    def char_bbox(self, cid: int) -> Rect:
        """Get the standard bounding box for a character from its CID.

        This is the standard bounding box in text space units based on
        width, descent and ascent, translated by the position vector.

        Danger: Not the actual bounding box of the glyph.
            This is a standardized bounding box for use in text
            extraction and layout analysis.  It does not correspond to
            the actual bounding box of an individual glyph as
            specified by the font program.

        """
        width = self.widths.get(cid, self.default_width)
        # We know that the matrix is diagonal here
        a, _, _, d, _, _ = self.matrix
        if self.vertical:
            vx, vy = self.positions.get(cid, self.default_position)
            # Horizontal offset for glyph origin vs. text
            # space origin.
            vx = -vx
            # Vertical offset for glyph origin
            vy = -vy
            # Find glyph bbox
            return (
                a * vx,
                d * (vy + self.descent),
                a * (vx + width),
                d * (vy + self.ascent),
            )
        return (0, d * self.descent, a * width, d * self.ascent)
