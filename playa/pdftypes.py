import io
import logging
import weakref
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
    cast,
)

from playa import settings
from playa.ascii85 import ascii85decode, asciihexdecode
from playa.ccitt import ccittfaxdecode
from playa.exceptions import (
    PDFException,
    PDFNotImplementedError,
    PDFTypeError,
    PDFValueError,
    PSTypeError,
)
from playa.lzw import lzwdecode
from playa.runlength import rldecode
from playa.utils import apply_png_predictor

if TYPE_CHECKING:
    from playa.document import PDFDocument

logger = logging.getLogger(__name__)


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
        if settings.STRICT:
            raise PSTypeError(f"Literal required: {x!r}")
        return str(x)
    else:
        return x.name


def keyword_name(x: Any) -> str:
    if not isinstance(x, PSKeyword):
        if settings.STRICT:
            raise PSTypeError("Keyword required: %r" % x)
        else:
            return str(x)
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


_DEFAULT = object()


class ObjRef:
    def __init__(
        self,
        doc: weakref.ReferenceType["PDFDocument"],
        objid: int,
    ) -> None:
        """Reference to a PDF object.

        :param doc: The PDF document.
        :param objid: The object number.
        """
        if objid == 0:
            if settings.STRICT:
                raise PDFValueError("PDF object id cannot be 0.")

        self.doc = doc
        self.objid = objid

    def __repr__(self) -> str:
        return "<ObjRef:%d>" % (self.objid)

    def resolve(self, default: object = None) -> Any:
        doc = self.doc()
        if doc is None:
            raise RuntimeError("Document no longer exists")
        try:
            return doc[self.objid]
        except IndexError:
            return default


def resolve1(x: object, default: object = None) -> Any:
    """Resolves an object.

    If this is an array or dictionary, it may still contains
    some indirect objects inside.
    """
    while isinstance(x, ObjRef):
        x = x.resolve(default=default)
    return x


def resolve_all(x: object, default: object = None) -> Any:
    """Recursively resolves the given object and all the internals.

    Make sure there is no indirect reference within the nested object.
    This procedure might be slow.
    """
    while isinstance(x, ObjRef):
        x = x.resolve(default=default)
    if isinstance(x, list):
        x = [resolve_all(v, default=default) for v in x]
    elif isinstance(x, dict):
        for k, v in x.items():
            x[k] = resolve_all(v, default=default)
    return x


def decipher_all(decipher: DecipherCallable, objid: int, genno: int, x: object) -> Any:
    """Recursively deciphers the given object."""
    if isinstance(x, bytes):
        if len(x) == 0:
            return x
        return decipher(objid, genno, x)
    if isinstance(x, list):
        x = [decipher_all(decipher, objid, genno, v) for v in x]
    elif isinstance(x, dict):
        for k, v in x.items():
            x[k] = decipher_all(decipher, objid, genno, v)
    return x


def int_value(x: object) -> int:
    x = resolve1(x)
    if not isinstance(x, int):
        if settings.STRICT:
            raise PDFTypeError("Integer required: %r" % (x,))
        return 0
    return x


def float_value(x: object) -> float:
    x = resolve1(x)
    if not isinstance(x, float):
        if settings.STRICT:
            raise PDFTypeError("Float required: %r" % (x,))
        return 0.0
    return x


def num_value(x: object) -> float:
    x = resolve1(x)
    if not isinstance(x, (int, float)):  # == utils.isnumber(x)
        if settings.STRICT:
            raise PDFTypeError("Int or Float required: %r" % x)
        return 0
    return x


def uint_value(x: object, n_bits: int) -> int:
    """Resolve number and interpret it as a two's-complement unsigned number"""
    xi = int_value(x)
    if xi > 0:
        return xi
    else:
        return xi + cast(int, 2**n_bits)


def str_value(x: object) -> bytes:
    x = resolve1(x)
    if not isinstance(x, bytes):
        if settings.STRICT:
            raise PDFTypeError("String required: %r" % x)
        return b""
    return x


def list_value(x: object) -> Union[List[Any], Tuple[Any, ...]]:
    x = resolve1(x)
    if not isinstance(x, (list, tuple)):
        if settings.STRICT:
            raise PDFTypeError("List required: %r" % x)
        return []
    return x


def dict_value(x: object) -> Dict[Any, Any]:
    x = resolve1(x)
    if not isinstance(x, dict):
        if settings.STRICT:
            logger.error("PDFTypeError : Dict required: %r", x)
            raise PDFTypeError("Dict required: %r" % x)
        return {}
    return x


def stream_value(x: object) -> "ContentStream":
    x = resolve1(x)
    if not isinstance(x, ContentStream):
        if settings.STRICT:
            raise PDFTypeError("ContentStream required: %r" % x)
        return ContentStream({}, b"")
    return x


def decompress_corrupted(data: bytes) -> bytes:
    """Called on some data that can't be properly decoded because of CRC checksum
    error. Attempt to decode it skipping the CRC.
    """
    d = zlib.decompressobj()
    f = io.BytesIO(data)
    result_str = b""
    buffer = f.read(1)
    i = 0
    try:
        while buffer:
            result_str += d.decompress(buffer)
            buffer = f.read(1)
            i += 1
    except zlib.error:
        # Let the error propagates if we're not yet in the CRC checksum
        if i < len(data) - 3:
            logger.warning("Data-loss while decompressing corrupted data")
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
        self.data: Optional[bytes] = None
        self.objid: Optional[int] = None
        self.genno: Optional[int] = None

    def set_objid(self, objid: int, genno: int) -> None:
        self.objid = objid
        self.genno = genno

    def __repr__(self) -> str:
        if self.data is None:
            assert self.rawdata is not None
            return "<ContentStream(%r): raw=%d, %r>" % (
                self.objid,
                len(self.rawdata),
                self.attrs,
            )
        else:
            assert self.data is not None
            return "<ContentStream(%r): len=%d, %r>" % (
                self.objid,
                len(self.data),
                self.attrs,
            )

    def __contains__(self, name: object) -> bool:
        return name in self.attrs

    def __getitem__(self, name: str) -> Any:
        return self.attrs[name]

    def get(self, name: str, default: object = None) -> Any:
        return self.attrs.get(name, default)

    def get_any(self, names: Iterable[str], default: object = None) -> Any:
        for name in names:
            if name in self.attrs:
                return self.attrs[name]
        return default

    def get_filters(self) -> List[Tuple[Any, Any]]:
        filters = self.get_any(("F", "Filter"))
        params = self.get_any(("DP", "DecodeParms", "FDecodeParms"), {})
        if not filters:
            return []
        if not isinstance(filters, list):
            filters = [filters]
        if not isinstance(params, list):
            # Make sure the parameters list is the same as filters.
            params = [params] * len(filters)
        if settings.STRICT and len(params) != len(filters):
            raise PDFException("Parameters len filter mismatch")

        resolved_filters = [resolve1(f) for f in filters]
        resolved_params = [resolve1(param) for param in params]
        return list(zip(resolved_filters, resolved_params))

    def decode(self) -> None:
        assert self.data is None and self.rawdata is not None, str(
            (self.data, self.rawdata),
        )
        data = self.rawdata
        if self.decipher:
            # Handle encryption
            assert self.objid is not None
            assert self.genno is not None
            data = self.decipher(self.objid, self.genno, data, self.attrs)
        filters = self.get_filters()
        if not filters:
            self.data = data
            self.rawdata = None
            return
        for f, params in filters:
            if f in LITERALS_FLATE_DECODE:
                # will get errors if the document is encrypted.
                try:
                    data = zlib.decompress(data)

                except zlib.error as e:
                    if settings.STRICT:
                        error_msg = f"Invalid zlib bytes: {e!r}, {data!r}"
                        raise PDFException(error_msg)

                    try:
                        data = decompress_corrupted(data)
                    except zlib.error:
                        data = b""

            elif f in LITERALS_LZW_DECODE:
                data = lzwdecode(data)
            elif f in LITERALS_ASCII85_DECODE:
                data = ascii85decode(data)
            elif f in LITERALS_ASCIIHEX_DECODE:
                data = asciihexdecode(data)
            elif f in LITERALS_RUNLENGTH_DECODE:
                data = rldecode(data)
            elif f in LITERALS_CCITTFAX_DECODE:
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
                raise PDFNotImplementedError("/Crypt filter is unsupported")
            else:
                raise PDFNotImplementedError("Unsupported filter: %r" % f)
            # apply predictors
            if params and "Predictor" in params:
                pred = int_value(params["Predictor"])
                if pred == 1:
                    # no predictor
                    pass
                elif pred >= 10:
                    # PNG predictor
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
                    raise PDFNotImplementedError(error_msg)
        self.data = data
        self.rawdata = None

    def get_data(self) -> bytes:
        if self.data is None:
            self.decode()
            assert self.data is not None
        return self.data

    def get_rawdata(self) -> Optional[bytes]:
        return self.rawdata
