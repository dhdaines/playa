import logging
import zlib
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    Final,
    Iterable,
    Iterator,
    List,
    Mapping,
    Protocol,
    Tuple,
    Union,
)

from playa.worker import DocumentRef, _deref_document

if TYPE_CHECKING:
    from playa.color import ColorSpace

logger: Final = logging.getLogger(__name__)
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
# Cannot be final because of https://github.com/mypyc/mypyc/issues/1183
MATRIX_IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


class PSLiteral:
    """A class that represents a PostScript literal.

    Postscript literals are used as identifiers, such as variable
    names, property names and dictionary keys.  Literals are case
    sensitive and denoted by a preceding slash sign (e.g. "/Name").
    They are globally unique objects stored in PSLiteralTable.
    """

    name: str

    def __new__(cls, name: str) -> "PSLiteral":
        if name not in PSLiteralTable:
            PSLiteralTable[name] = object.__new__(cls)
            PSLiteralTable[name].name = name
        return PSLiteralTable[name]

    def __getnewargs__(self) -> Tuple:
        return (self.name,)

    def __repr__(self) -> str:
        return "/%r" % self.name


class PSKeyword:
    """A class that represents a PostScript keyword.

    PostScript keywords are a dozen of predefined words.  Commands and
    directives in PostScript are expressed by keywords.  They are also
    used to denote the content boundaries.  They are globally unique
    objects stored in PSKeywordTable.
    """

    name: bytes

    def __new__(cls, name: bytes) -> "PSKeyword":
        if name not in PSKeywordTable:
            PSKeywordTable[name] = object.__new__(cls)
            PSKeywordTable[name].name = name
        return PSKeywordTable[name]

    def __getnewargs__(self) -> Tuple:
        return (self.name,)

    def __repr__(self) -> str:
        return "/%r" % self.name


# Do not make these generic as they are performance-critical
PSLiteralTable: Final[Dict[str, PSLiteral]] = {}
PSKeywordTable: Final[Dict[bytes, PSKeyword]] = {}

# Compatibility aliases
LIT: Final = PSLiteral
KWD: Final = PSKeyword

# Intern a bunch of important literals
LITERAL_CRYPT: Final = LIT("Crypt")
LITERAL_IMAGE: Final = LIT("Image")
# Abbreviation of Filter names in PDF 4.8.6. "Inline Images"
LITERALS_FLATE_DECODE: Final = (LIT("FlateDecode"), LIT("Fl"))
LITERALS_LZW_DECODE: Final = (LIT("LZWDecode"), LIT("LZW"))
LITERALS_ASCII85_DECODE: Final = (LIT("ASCII85Decode"), LIT("A85"))
LITERALS_ASCIIHEX_DECODE: Final = (LIT("ASCIIHexDecode"), LIT("AHx"))
LITERALS_RUNLENGTH_DECODE: Final = (LIT("RunLengthDecode"), LIT("RL"))
LITERALS_CCITTFAX_DECODE: Final = (LIT("CCITTFaxDecode"), LIT("CCF"))
LITERALS_DCT_DECODE: Final = (LIT("DCTDecode"), LIT("DCT"))
LITERALS_JBIG2_DECODE: Final = (LIT("JBIG2Decode"),)
LITERALS_JPX_DECODE: Final = (LIT("JPXDecode"),)


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
    """Fully typed decipher callback, with optional parameter."""

    def __call__(
        self,
        objid: int,
        genno: int,
        data: bytes,
        attrs: Union[Dict[str, Any], None] = None,
    ) -> bytes: ...


class ObjRef:
    def __init__(
        self,
        doc: Union[DocumentRef, None] = None,
        objid: int = 0,
    ) -> None:
        """Reference to a PDF object.

        :param doc: The PDF document.
        :param objid: The object number.
        """
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

    def resolve(self, default: PDFObject = None) -> PDFObject:
        if self.doc is None:
            return default
        doc = _deref_document(self.doc)
        try:
            return doc[self.objid]
        except KeyError:
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
        lp = list_value(o)
        if len(lp) != 2:
            raise ValueError("Point must have 2 elements")
        x = num_value(lp[0])
        y = num_value(lp[1])
        return x, y
    except ValueError:
        raise ValueError("Could not parse point %r" % (o,))
    except TypeError:
        raise TypeError("Point contains non-numeric values")


def rect_value(o: PDFObject) -> Rect:
    try:
        lr = list_value(o)
        if len(lr) != 4:
            raise ValueError("Rect must have 4 elements")
        x0 = num_value(lr[0])
        y0 = num_value(lr[1])
        x1 = num_value(lr[2])
        y1 = num_value(lr[3])
        return x0, y0, x1, y1
    except ValueError:
        raise ValueError("Could not parse rectangle %r" % (o,))
    except TypeError:
        raise TypeError("Rectangle contains non-numeric values")


def matrix_value(o: PDFObject) -> Matrix:
    try:
        lm = list_value(o)
        if len(lm) != 6:
            raise ValueError("Matrix must have 6 elements")
        a = num_value(lm[0])
        b = num_value(lm[1])
        c = num_value(lm[2])
        d = num_value(lm[3])
        e = num_value(lm[4])
        f = num_value(lm[5])
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


class ContentStream(Mapping[str, PDFObject]):
    _data: Union[bytes, None] = None
    _colorspace: Union["ColorSpace", None] = None
    objid: Union[int, None] = None
    genno: Union[int, None] = None

    def __init__(
        self,
        attrs: Union[Dict[str, Any], None] = None,
        rawdata: bytes = b"",
        decipher: Union[DecipherCallable, None] = None,
    ) -> None:
        if attrs is None:
            attrs = {}
        self.attrs = attrs
        self.rawdata = rawdata
        self.decipher = decipher

    def __repr__(self) -> str:
        if self._data is None:
            return "<ContentStream(%r): raw=%d, %r>" % (
                self.objid,
                len(self.rawdata),
                self.attrs,
            )
        else:
            return "<ContentStream(%r): len=%d, %r>" % (
                self.objid,
                len(self._data),
                self.attrs,
            )

    def __contains__(self, name: object) -> bool:
        return name in self.attrs

    def __getitem__(self, name: str) -> Any:
        return self.attrs[name]

    def __iter__(self) -> Iterator[str]:
        return iter(self.attrs)

    def __len__(self) -> int:
        return len(self.attrs)

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

    def decode(self, strict: bool = False) -> bytes:
        data = self.rawdata
        if self.decipher:
            # Handle encryption
            assert self.objid is not None
            assert self.genno is not None
            data = self.decipher(self.objid, self.genno, data, self.attrs)
        filters = self.get_filters()
        if not filters:
            self._data = data
            return data
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
        return data

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

        if self._colorspace is not None:
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
        return self.decode()


class InlineImage(ContentStream):
    """Specific class for inline images so the interpreter can
    recognize them (they are otherwise the same thing as content
    streams)."""
