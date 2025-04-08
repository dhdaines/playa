import logging
from io import BytesIO
from typing import (
    Dict,
    Iterable,
    List,
    Optional,
    Tuple,
    Union,
    cast,
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
    dict_value,
    int_value,
    list_value,
    num_value,
    resolve1,
    resolve_all,
    stream_value,
)
from playa.utils import (
    Matrix,
    Point,
    Rect,
    apply_matrix_norm,
    choplist,
    decode_text,
)

log = logging.getLogger(__name__)


def get_widths(seq: Iterable[PDFObject]) -> Dict[int, float]:
    """Build a mapping of character widths for horizontal writing."""
    widths: Dict[int, float] = {}
    r: List[float] = []
    for v in seq:
        if isinstance(v, list):
            if r:
                char1 = r[-1]
                for i, w in enumerate(v):
                    widths[int_value(char1) + i] = w
                r = []
        elif isinstance(v, (int, float)):  # == utils.isnumber(v)
            r.append(v)
            if len(r) == 3:
                (char1, char2, w) = r
                for i in range(int_value(char1), int_value(char2) + 1):
                    widths[i] = w
                r = []
    return widths


def get_widths2(seq: Iterable[PDFObject]) -> Dict[int, Tuple[float, Point]]:
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
                        (int_value(vx), int_value(vy)),
                    )
                r = []
        elif isinstance(v, (int, float)):  # == utils.isnumber(v)
            r.append(v)
            if len(r) == 5:
                (char1, char2, w, vx, vy) = r
                for i in range(int(char1), int(char2) + 1):
                    widths[i] = (w, (vx, vy))
                r = []
    return widths


LITERAL_STANDARD_ENCODING = LIT("StandardEncoding")


class Font:
    vertical = False
    multibyte = False
    encoding: Dict[int, str]

    def __init__(
        self,
        descriptor: Dict[str, PDFObject],
        widths: Dict[int, float],
        default_width: Optional[float] = None,
    ) -> None:
        self.descriptor = descriptor
        self.widths = resolve_all(widths)
        self.fontname = resolve1(descriptor.get("FontName", "unknown"))
        if isinstance(self.fontname, PSLiteral):
            self.fontname = literal_name(self.fontname)
        self.flags = int_value(descriptor.get("Flags", 0))
        self.ascent = num_value(descriptor.get("Ascent", 0))
        self.descent = num_value(descriptor.get("Descent", 0))
        self.italic_angle = num_value(descriptor.get("ItalicAngle", 0))
        if default_width is None:
            self.default_width = num_value(descriptor.get("MissingWidth", 0))
        else:
            self.default_width = default_width
        self.default_width = resolve1(self.default_width)
        self.leading = num_value(descriptor.get("Leading", 0))
        self.bbox = cast(
            Rect,
            list_value(resolve_all(descriptor.get("FontBBox", (0, 0, 0, 0)))),
        )
        self.hscale = self.vscale = 0.001

        # PDF RM 9.8.1 specifies /Descent should always be a negative number.
        # PScript5.dll seems to produce Descent with a positive number, but
        # text analysis will be wrong if this is taken as correct. So force
        # descent to negative.
        if self.descent > 0:
            self.descent = -self.descent

    def __repr__(self) -> str:
        return "<Font>"

    def decode(self, data: bytes) -> Iterable[Tuple[int, str]]:
        # Default to an Identity map
        log.debug("decode with identity: %r", data)
        return ((cid, chr(cid)) for cid in data)

    def get_ascent(self) -> float:
        """Ascent above the baseline, in text space units"""
        return self.ascent * self.vscale

    def get_descent(self) -> float:
        """Descent below the baseline, in text space units; always negative"""
        return self.descent * self.vscale

    def get_width(self) -> float:
        w = self.bbox[2] - self.bbox[0]
        if w == 0:
            w = -self.default_width
        return w * self.hscale

    def get_height(self) -> float:
        h = self.bbox[3] - self.bbox[1]
        if h == 0:
            h = self.ascent - self.descent
        return h * self.vscale

    def char_width(self, cid: int) -> float:
        """Get the width of a character from its CID."""
        if cid not in self.widths:
            return self.default_width * self.hscale
        return self.widths[cid] * self.hscale

    def char_disp(self, cid: int) -> Union[float, Tuple[Optional[float], float]]:
        """Returns an integer for horizontal fonts, a tuple for vertical fonts."""
        return 0

    def string_width(self, s: bytes) -> float:
        return sum(self.char_width(cid) for cid, _ in self.decode(s))


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
        self.cid2unicode = cid2unicode_from_encoding(self.encoding)
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
            return ((cid, self.cid2unicode.get(cid, "")) for cid in data)


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
            widths = {i + firstchar: resolve1(w) for (i, w) in enumerate(width_list)}
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
                self.cfffont = cfffont
                return {
                    cid: cfffont.gid2name[gid]
                    for cid, gid in cfffont.code2gid.items()
                    if gid in cfffont.gid2name
                }
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

    def char_width(self, cid: int) -> float:
        """Get the width of a character from its CID."""
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
            if cid not in self.cid2unicode:
                width = self.default_width
            else:
                width = self.char_widths.get(self.cid2unicode[cid], self.default_width)
        else:
            width = self.widths.get(cid, self.default_width)
        return width * self.hscale

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
        widths = {i + firstchar: resolve1(w) for (i, w) in enumerate(width_list)}
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
        widths = {i + firstchar: w for (i, w) in enumerate(width_list)}
        if "FontDescriptor" in spec:
            descriptor = dict_value(spec["FontDescriptor"])
        else:
            descriptor = {"Ascent": 0, "Descent": 0, "FontBBox": spec["FontBBox"]}
        SimpleFont.__init__(self, descriptor, widths, spec)
        self.matrix = cast(Matrix, tuple(list_value(spec.get("FontMatrix"))))
        (_, self.descent, _, self.ascent) = self.bbox
        (self.hscale, self.vscale) = apply_matrix_norm(self.matrix, (1, 1))

    def get_implicit_encoding(
        self, descriptor: Dict[str, PDFObject]
    ) -> Union[PSLiteral, Dict[int, str], None]:
        # PDF 1.7 sec 9.6.6.3: A Type 3 font’s mapping from character
        # codes to glyph names shall be entirely defined by its
        # Encoding entry, which is required in this case.
        return {}

    def __repr__(self) -> str:
        return "<Type3Font>"


# Mapping of cmap names. Original cmap name is kept if not in the mapping.
# (missing reference for why DLIdent is mapped to Identity)
IDENTITY_ENCODER = {
    "DLIdent-H": "Identity-H",
    "DLIdent-V": "Identity-V",
}


class CIDFont(Font):
    default_disp: Union[float, Tuple[Optional[float], float]]

    def __init__(
        self,
        spec: Dict[str, PDFObject],
    ) -> None:
        self.basefont = get_basefont(spec)
        self.cidsysteminfo = dict_value(spec.get("CIDSystemInfo", {}))
        # These are *supposed* to be ASCII (PDF 1.7 section 9.7.3),
        # but for whatever reason they are sometimes UTF-16BE
        cid_registry = decode_text(
            resolve1(self.cidsysteminfo.get("Registry", b"unknown"))
        )
        cid_ordering = decode_text(
            resolve1(self.cidsysteminfo.get("Ordering", b"unknown"))
        )
        self.cidcoding = f"{cid_registry.strip()}-{cid_ordering.strip()}"
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

        self.multibyte = True
        self.vertical = self.cmap.is_vertical()
        if self.vertical:
            # writing mode: vertical
            widths2 = get_widths2(list_value(spec.get("W2", [])))
            self.disps = {cid: (vx, vy) for (cid, (_, (vx, vy))) in widths2.items()}
            (vy, w) = resolve1(spec.get("DW2", [880, -1000]))
            self.default_disp = (None, vy)
            widths = {cid: w for (cid, (w, _)) in widths2.items()}
            default_width = w
        else:
            # writing mode: horizontal
            self.disps = {}
            self.default_disp = 0
            widths = get_widths(list_value(spec.get("W", [])))
            default_width = spec.get("DW", 1000)
        Font.__init__(self, descriptor, widths, default_width=default_width)

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
            if isinstance(spec_encoding, PSLiteral):
                cmap_name = spec_encoding.name
            else:
                cmap_name = literal_name(spec_encoding["CMapName"])
        except KeyError:
            log.warning("Font spec is missing Encoding: %r", spec)
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

    def char_disp(self, cid: int) -> Union[float, Tuple[Optional[float], float]]:
        """Returns 0 for horizontal fonts, a tuple for vertical fonts."""
        return self.disps.get(cid, self.default_disp)
