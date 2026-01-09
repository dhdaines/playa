import logging
import zlib
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    Generic,
    Iterable,
    List,
    Optional,
    Protocol,
    Tuple,
    Type,
    TypeVar,
    Union,
)

from playa.worker import DocumentRef, _deref_document

if TYPE_CHECKING:
    from playa.color import ColorSpace

logger = logging.getLogger(__name__)
PDFObject = Union[
    int,
    float,
    bool,
    "PSLiteral",
    bytes,
    List,
    Dict,
    "ObjRef",
    "PSKeyword",
    "InlineImage",
    "ContentStream",
    None,
]
Point = Tuple[float, float]
Rect = Tuple[float, float, float, float]
Matrix = Tuple[float, float, float, float, float, float]
BBOX_NONE = (-1, -1, -1, -1)
MATRIX_IDENTITY: Matrix = (1, 0, 0, 1, 0, 0)


class PSLiteral:
    """A class that represents a PostScript literal.

    Postscript literals are used as identifiers, such as
    variable names, property names and dictionary keys.
    Literals are case sensitive and denoted by a preceding
    slash sign (e.g. "/Name")

    Note: Do not create an instance of PSLiteral directly.
    Always use PSLiteralTable.intern().
    """

    def __init__(self, name: str) -> None:
        self.name = name

    def __repr__(self) -> str:
        return "/%r" % self.name


class PSKeyword:
    """A class that represents a PostScript keyword.

    PostScript keywords are a dozen of predefined words.
    Commands and directives in PostScript are expressed by keywords.
    They are also used to denote the content boundaries.

    Note: Do not create an instance of PSKeyword directly.
    Always use PSKeywordTable.intern().
    """

    def __init__(self, name: bytes) -> None:
        self.name = name

    def __repr__(self) -> str:
        return "/%r" % self.name


_SymbolT = TypeVar("_SymbolT", PSLiteral, PSKeyword)
_NameT = TypeVar("_NameT", str, bytes)


class PSSymbolTable(Generic[_SymbolT, _NameT]):
    """Store globally unique name objects or language keywords."""

    def __init__(self, table_type: Type[_SymbolT], name_type: Type[_NameT]) -> None:
        self.dict: Dict[_NameT, _SymbolT] = {}
        self.table_type: Type[_SymbolT] = table_type
        self.name_type: Type[_NameT] = name_type

    def intern(self, name: _NameT) -> _SymbolT:
        if not isinstance(name, self.name_type):
            raise ValueError(f"{self.table_type} can only store {self.name_type}")
        if name in self.dict:
            lit = self.dict[name]
        else:
            lit = self.table_type(name)  # type: ignore
        self.dict[name] = lit
        return lit


PSLiteralTable = PSSymbolTable(PSLiteral, str)
PSKeywordTable = PSSymbolTable(PSKeyword, bytes)
LIT = PSLiteralTable.intern
KWD = PSKeywordTable.intern

# Intern a bunch of important literals
LITERAL_CRYPT = LIT("Crypt")
LITERAL_IMAGE = LIT("Image")
# Abbreviation of Filter names in PDF 4.8.6. "Inline Images"
LITERALS_FLATE_DECODE = (LIT("FlateDecode"), LIT("Fl"))
LITERALS_LZW_DECODE = (LIT("LZWDecode"), LIT("LZW"))
LITERALS_ASCII85_DECODE = (LIT("ASCII85Decode"), LIT("A85"))
LITERALS_ASCIIHEX_DECODE = (LIT("ASCIIHexDecode"), LIT("AHx"))
LITERALS_RUNLENGTH_DECODE = (LIT("RunLengthDecode"), LIT("RL"))
LITERALS_CCITTFAX_DECODE = (LIT("CCITTFaxDecode"), LIT("CCF"))
LITERALS_DCT_DECODE = (LIT("DCTDecode"), LIT("DCT"))
LITERALS_JBIG2_DECODE = (LIT("JBIG2Decode"),)
LITERALS_JPX_DECODE = (LIT("JPXDecode"),)


def name_str(x: bytes) -> str:
    """Get the string representation for a name object.

    According to the PDF 1.7 spec (p.18):

    > Ordinarily, the bytes making up the name are never treated as
    > text to be presented to a human user or to an application
    > external to a conforming reader. However, occasionally the need
    > arises to treat a name object as text... In such situations, the
    > sequence of bytes (after expansion of NUMBER SIGN sequences, if
    > any) should be interpreted according to UTF-8.

    Accordingly, if they *can* be decoded to UTF-8, then they *will*
    be, and if not, we will just decode them as ISO-8859-1 since that
    gives a unique (if possibly nonsensical) value for an 8-bit string.
    """
    try:
        return x.decode("utf-8")
    except UnicodeDecodeError:
        return x.decode("iso-8859-1")


def literal_name(x: Any) -> str:
    if not isinstance(x, PSLiteral):
        raise TypeError(f"Literal required: {x!r}")
    else:
        return x.name


def keyword_name(x: Any) -> str:
    if not isinstance(x, PSKeyword):
        raise TypeError("Keyword required: %r" % x)
    else:
        # PDF keywords are *not* UTF-8 (they aren't ISO-8859-1 either,
        # but this isn't very important, we just want some
        # unique representation of 8-bit characters, as above)
        name = x.name.decode("iso-8859-1")
    return name


class DecipherCallable(Protocol):
    """Fully typed a decipher callback, with optional parameter."""

    def __call__(
        self,
        objid: int,
        genno: int,
        data: bytes,
        attrs: Optional[Dict[str, Any]] = None,
    ) -> bytes:
        raise NotImplementedError


class ObjRef:
    def __init__(
        self,
        doc: Union[DocumentRef, None],
        objid: int,
    ) -> None:
        """Reference to a PDF object.

        :param doc: The PDF document.
        :param objid: The object number.
        """
        if objid == 0:
            raise ValueError("PDF object id cannot be 0.")

        self.doc = doc
        self.objid = objid

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, ObjRef):
            raise NotImplementedError("Unimplemented comparison with non-ObjRef")
        if self.doc is None and other.doc is None:
            return self.objid == other.objid
        elif self.doc is None or other.doc is None:
            return False
        else:
            selfdoc = _deref_document(self.doc)
            otherdoc = _deref_document(other.doc)
            return selfdoc is otherdoc and self.objid == other.objid

    def __hash__(self) -> int:
        return self.objid

    def __repr__(self) -> str:
        return "<ObjRef:%d>" % (self.objid)

    def resolve(self, default: Any = None) -> Any:
        if self.doc is None:
            return default
        doc = _deref_document(self.doc)
        try:
            return doc[self.objid]
        except IndexError:
            return default


def resolve1(x: PDFObject, default: PDFObject = None) -> PDFObject:
    """Resolves an object.

    If this is an array or dictionary, it may still contains
    some indirect objects inside.
    """
    while isinstance(x, ObjRef):
        x = x.resolve(default=default)
    return x


def resolve_all(x: PDFObject, default: PDFObject = None) -> PDFObject:
    """Resolves all indirect object references inside the given object.

    This creates new copies of any lists or dictionaries, so the
    original object is not modified.  However, it will ultimately
    create circular references if they exist, so beware.
    """

    def resolver(
        x: PDFObject, default: PDFObject, seen: Dict[int, PDFObject]
    ) -> PDFObject:
        if isinstance(x, ObjRef):
            ref = x
            while isinstance(x, ObjRef):
                if x.objid in seen:
                    return seen[x.objid]
                x = x.resolve(default=default)
            seen[ref.objid] = x
        if isinstance(x, list):
            return [resolver(v, default, seen) for v in x]
        elif isinstance(x, dict):
            return {k: resolver(v, default, seen) for k, v in x.items()}
        return x

    return resolver(x, default, {})


def decipher_all(
    decipher: DecipherCallable, objid: int, genno: int, x: PDFObject
) -> PDFObject:
    """Recursively deciphers the given object."""
    if isinstance(x, bytes):
        if len(x) == 0:
            return x
        return decipher(objid, genno, x)
    if isinstance(x, list):
        x = [decipher_all(decipher, objid, genno, v) for v in x]
    elif isinstance(x, dict):
        return {k: decipher_all(decipher, objid, genno, v) for k, v in x.items()}
    return x


def bool_value(x: PDFObject) -> bool:
    x = resolve1(x)
    if not isinstance(x, bool):
        raise TypeError("Boolean required: %r" % (x,))
    return x


def int_value(x: PDFObject) -> int:
    x = resolve1(x)
    if not isinstance(x, int):
        raise TypeError("Integer required: %r" % (x,))
    return x


def float_value(x: PDFObject) -> float:
    x = resolve1(x)
    if not isinstance(x, float):
        raise TypeError("Float required: %r" % (x,))
    return x


def num_value(x: PDFObject) -> float:
    x = resolve1(x)
    if not isinstance(x, (int, float)):
        raise TypeError("Int or Float required: %r" % x)
    return x


def uint_value(x: PDFObject, n_bits: int) -> int:
    """Resolve number and interpret it as a two's-complement unsigned number"""
    xi = int_value(x)
    if xi > 0:
        return xi
    else:
        return xi + (1 << n_bits)


def str_value(x: PDFObject) -> bytes:
    x = resolve1(x)
    if not isinstance(x, bytes):
        raise TypeError("String required: %r" % x)
    return x


def list_value(x: PDFObject) -> Union[List[Any], Tuple[Any, ...]]:
    x = resolve1(x)
    if not isinstance(x, (list, tuple)):
        raise TypeError("List required: %r" % x)
    return x


def dict_value(x: PDFObject) -> Dict[Any, Any]:
    x = resolve1(x)
    if not isinstance(x, dict):
        raise TypeError("Dict required: %r" % x)
    return x


def stream_value(x: PDFObject) -> "ContentStream":
    x = resolve1(x)
    if not isinstance(x, ContentStream):
        raise TypeError("ContentStream required: %r" % x)
    return x


def point_value(o: PDFObject) -> Point:
    try:
        (x, y) = (num_value(x) for x in list_value(o))
        return x, y
    except ValueError:
        raise ValueError("Could not parse point %r" % (o,))
    except TypeError:
        raise TypeError("Point contains non-numeric values")


def rect_value(o: PDFObject) -> Rect:
    try:
        (x0, y0, x1, y1) = (num_value(x) for x in list_value(o))
        return x0, y0, x1, y1
    except ValueError:
        raise ValueError("Could not parse rectangle %r" % (o,))
    except TypeError:
        raise TypeError("Rectangle contains non-numeric values")


def matrix_value(o: PDFObject) -> Matrix:
    try:
        (a, b, c, d, e, f) = (num_value(x) for x in list_value(o))
        return a, b, c, d, e, f
    except ValueError:
        raise ValueError("Could not parse matrix %r" % (o,))
    except TypeError:
        raise TypeError("Matrix contains non-numeric values")


def decompress_corrupted(data: bytes, bufsiz: int = 4096) -> bytes:
    """Decompress (possibly with data loss) a corrupted FlateDecode stream."""
    d = zlib.decompressobj()
    size = len(data)
    result_str = b""
    pos = end = 0
    try:
        while pos < size:
            # Skip the CRC checksum unless it's the only thing left
            end = min(size - 3, pos + bufsiz)
            if end == pos:
                end = size
            result_str += d.decompress(data[pos:end])
            pos = end
            logger.debug(
                "decompress_corrupted: %d bytes in, %d bytes out", pos, len(result_str)
            )
    except zlib.error as e:
        # Let the error propagates if we're not yet in the CRC checksum
        if pos != size - 3:
            logger.warning(
                "Data loss in decompress_corrupted: %s: bytes %d:%d", e, pos, end
            )
    return result_str


class ContentStream:
    def __init__(
        self,
        attrs: Dict[str, Any],
        rawdata: bytes,
        decipher: Optional[DecipherCallable] = None,
    ) -> None:
        assert isinstance(attrs, dict), str(type(attrs))
        self.attrs = attrs
        self.rawdata: Optional[bytes] = rawdata
        self.decipher = decipher
        self._data: Optional[bytes] = None
        self.objid: Optional[int] = None
        self.genno: Optional[int] = None

    def __repr__(self) -> str:
        if self._data is None:
            assert self.rawdata is not None
            return "<ContentStream(%r): raw=%d, %r>" % (
                self.objid,
                len(self.rawdata),
                self.attrs,
            )
        else:
            assert self._data is not None
            return "<ContentStream(%r): len=%d, %r>" % (
                self.objid,
                len(self._data),
                self.attrs,
            )

    def __contains__(self, name: str) -> bool:
        return name in self.attrs

    def __getitem__(self, name: str) -> Any:
        return self.attrs[name]

    def get(self, name: str, default: PDFObject = None) -> PDFObject:
        return self.attrs.get(name, default)

    def get_any(self, names: Iterable[str], default: PDFObject = None) -> PDFObject:
        for name in names:
            if name in self.attrs:
                return self.attrs[name]
        return default

    @property
    def filters(self) -> List[PSLiteral]:
        filters = resolve1(self.get_any(("F", "Filter")))
        if not filters:
            return []
        if not isinstance(filters, list):
            filters = [filters]
        return [f for f in filters if isinstance(f, PSLiteral)]

    def get_filters(self) -> List[Tuple[PSLiteral, Dict[str, PDFObject]]]:
        filters = self.filters
        params = resolve1(self.get_any(("DP", "DecodeParms", "FDecodeParms")))
        if not params:
            params = {}
        if not isinstance(params, list):
            params = [params] * len(filters)
        resolved_params = []
        for p in params:
            rp = resolve1(p)
            if isinstance(rp, dict):
                resolved_params.append(rp)
            else:
                resolved_params.append({})
        return list(zip(filters, resolved_params))

    def decode(self, strict: bool = False) -> None:
        assert self._data is None and self.rawdata is not None, str(
            (self._data, self.rawdata),
        )
        data = self.rawdata
        if self.decipher:
            # Handle encryption
            assert self.objid is not None
            assert self.genno is not None
            data = self.decipher(self.objid, self.genno, data, self.attrs)
        filters = self.get_filters()
        if not filters:
            self._data = data
            self.rawdata = None
            return
        for f, params in filters:
            if f in LITERALS_FLATE_DECODE:
                # will get errors if the document is encrypted.
                try:
                    data = zlib.decompress(data)
                except zlib.error as e:
                    if strict:
                        error_msg = f"Invalid zlib bytes: {e!r}, {data!r}"
                        raise ValueError(error_msg)
                    else:
                        logger.warning("%s: %r", e, self)
                    data = decompress_corrupted(data)

            elif f in LITERALS_LZW_DECODE:
                from playa.lzw import lzwdecode

                data = lzwdecode(data)
            elif f in LITERALS_ASCII85_DECODE:
                from playa.ascii85 import ascii85decode

                data = ascii85decode(data)
            elif f in LITERALS_ASCIIHEX_DECODE:
                from playa.ascii85 import asciihexdecode

                data = asciihexdecode(data)
            elif f in LITERALS_RUNLENGTH_DECODE:
                from playa.runlength import rldecode

                data = rldecode(data)
            elif f in LITERALS_CCITTFAX_DECODE:
                from playa.ccitt import ccittfaxdecode

                data = ccittfaxdecode(data, params)
            elif f in LITERALS_DCT_DECODE:
                # This is probably a JPG stream
                # it does not need to be decoded twice.
                # Just return the stream to the user.
                pass
            elif f in LITERALS_JBIG2_DECODE or f in LITERALS_JPX_DECODE:
                pass
            elif f == LITERAL_CRYPT:
                # not yet..
                raise NotImplementedError("/Crypt filter is unsupported")
            else:
                raise NotImplementedError("Unsupported filter: %r" % f)
            # apply predictors
            if params and "Predictor" in params:
                pred = int_value(params["Predictor"])
                if pred == 1:
                    # no predictor
                    pass
                elif pred == 2:
                    # TIFF predictor 2
                    from playa.utils import apply_tiff_predictor

                    colors = int_value(params.get("Colors", 1))
                    columns = int_value(params.get("Columns", 1))
                    raw_bits_per_component = params.get("BitsPerComponent", 8)
                    bitspercomponent = int_value(raw_bits_per_component)
                    data = apply_tiff_predictor(
                        colors,
                        columns,
                        bitspercomponent,
                        data,
                    )
                elif pred >= 10:
                    # PNG predictor
                    from playa.utils import apply_png_predictor

                    colors = int_value(params.get("Colors", 1))
                    columns = int_value(params.get("Columns", 1))
                    raw_bits_per_component = params.get("BitsPerComponent", 8)
                    bitspercomponent = int_value(raw_bits_per_component)
                    data = apply_png_predictor(
                        pred,
                        colors,
                        columns,
                        bitspercomponent,
                        data,
                    )
                else:
                    error_msg = "Unsupported predictor: %r" % pred
                    raise NotImplementedError(error_msg)
        self._data = data
        self.rawdata = None

    @property
    def bits(self) -> int:
        """Bits per component for an image stream.

        Default is 1."""
        return int_value(self.get_any(("BPC", "BitsPerComponent"), 1))

    @property
    def width(self) -> int:
        """Width in pixels of an image stream.

        It may be the case that a stream has no inherent width, in
        which case the default width is 1.
        """
        return int_value(self.get_any(("W", "Width"), 1))

    @property
    def height(self) -> int:
        """Height in pixels for an image stream.

        It may be the case that a stream has no inherent height, in
        which case the default height is 1."""
        return int_value(self.get_any(("H", "Height"), 1))

    @property
    def colorspace(self) -> "ColorSpace":
        """Colorspace for an image stream.

        Default is DeviceGray (1 component).

        Raises: ValueError if the colorspace is invalid, or
                unfortunately also in the case where it is a named
                resource in the containing page (or Form XObject, in
                the case of an inline image) and the stream is
                accessed from outside an interpreter for that
                page/object.
        """
        from playa.color import get_colorspace, LITERAL_DEVICE_GRAY

        if hasattr(self, "_colorspace"):
            return self._colorspace
        spec = resolve1(self.get_any(("CS", "ColorSpace"), LITERAL_DEVICE_GRAY))
        cs = get_colorspace(spec)
        if cs is None:
            raise ValueError("Unknown or undefined colour space: %r" % (spec,))
        self._colorspace: "ColorSpace" = cs
        return self._colorspace

    @colorspace.setter
    def colorspace(self, cs: "ColorSpace") -> None:
        self._colorspace = cs

    @property
    def buffer(self) -> bytes:
        """The decoded contents of the stream."""
        if self._data is None:
            self.decode()
            assert self._data is not None
        return self._data


class InlineImage(ContentStream):
    """Specific class for inline images so the interpreter can
    recognize them (they are otherwise the same thing as content
    streams)."""
