import io
import itertools
import logging
import re
import struct
from hashlib import md5, sha256, sha384, sha512
from typing import (
    Any,
    BinaryIO,
    Callable,
    Dict,
    Iterable,
    Iterator,
    List,
    NamedTuple,
    Optional,
    Protocol,
    Sequence,
    Tuple,
    Union,
    cast,
)

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from playa import settings
from playa.arcfour import Arcfour
from playa.data_structures import NameTree, NumberTree
from playa.exceptions import (
    PSEOF,
    PDFEncryptionError,
    PDFException,
    PDFKeyError,
    PDFNoOutlines,
    PDFNoPageLabels,
    PDFNoPageTree,
    PDFNoValidXRef,
    PDFPasswordIncorrect,
    PDFSyntaxError,
    PDFTypeError,
    PSException,
)
from playa.pdfpage import PDFPage
from playa.pdfparser import KEYWORD_XREF, PDFParser, PDFStreamParser
from playa.pdftypes import (
    DecipherCallable,
    PDFObjRef,
    PDFStream,
    decipher_all,
    dict_value,
    int_value,
    list_value,
    resolve1,
    str_value,
    stream_value,
    uint_value,
)
from playa.psparser import KWD, LIT, PSLiteral, literal_name
from playa.utils import (
    choplist,
    decode_text,
    format_int_alpha,
    format_int_roman,
    nunpack,
)

log = logging.getLogger(__name__)


# Some predefined literals and keywords (these can be defined wherever
# they are used as they are interned to the same objects)
LITERAL_OBJSTM = LIT("ObjStm")
LITERAL_XREF = LIT("XRef")
LITERAL_CATALOG = LIT("Catalog")
LITERAL_PAGE = LIT("Page")
LITERAL_PAGES = LIT("Pages")
KEYWORD_OBJ = KWD(b"obj")
INHERITABLE_PAGE_ATTRS = {"Resources", "MediaBox", "CropBox", "Rotate"}


class PDFXRef(Protocol):
    """
    Duck-typing for XRef table implementations, which are expected to be read-only.
    """

    @property
    def trailer(self) -> Dict[str, Any]: ...
    @property
    def objids(self) -> Iterable[int]: ...
    def get_pos(self, objid: int) -> Tuple[Optional[int], int, int]: ...


class PDFXRefTable:
    """Simplest (PDF 1.0) implementation of cross-reference table, in
    plain text at the end of the file.
    """

    def __init__(self, parser: PDFParser) -> None:
        self.offsets: Dict[int, Tuple[Optional[int], int, int]] = {}
        self.trailer: Dict[str, Any] = {}
        self._load(parser)

    def _load(self, parser: PDFParser) -> None:
        while True:
            try:
                (pos, line) = parser.nextline()
                line = line.strip()
                if not line:
                    continue
            except PSEOF:
                raise PDFNoValidXRef("Unexpected EOF - file corrupted?")
            if line.startswith(b"trailer"):
                parser.seek(pos)
                break
            f = line.split(b" ")
            if len(f) != 2:
                error_msg = f"Trailer not found: {parser!r}: line={line!r}"
                raise PDFNoValidXRef(error_msg)
            try:
                (start, nobjs) = map(int, f)
            except ValueError:
                error_msg = f"Invalid line: {parser!r}: line={line!r}"
                raise PDFNoValidXRef(error_msg)
            for objid in range(start, start + nobjs):
                try:
                    (_, line) = parser.nextline()
                    line = line.strip()
                except PSEOF:
                    raise PDFNoValidXRef("Unexpected EOF - file corrupted?")
                f = line.split(b" ")
                if len(f) != 3:
                    error_msg = f"Invalid XRef format: {parser!r}, line={line!r}"
                    raise PDFNoValidXRef(error_msg)
                (pos_b, genno_b, use_b) = f
                if use_b != b"n":
                    continue
                self.offsets[objid] = (None, int(pos_b), int(genno_b))
        log.debug("xref objects: %r", self.offsets)
        self._load_trailer(parser)

    def _load_trailer(self, parser: PDFParser) -> None:
        try:
            (_, kwd) = parser.nexttoken()
            assert kwd is KWD(b"trailer"), str(kwd)
            (_, dic) = parser.nextobject()
        except PSEOF:
            x = parser.pop(1)
            if not x:
                raise PDFNoValidXRef("Unexpected EOF - file corrupted")
            (_, dic) = x[0]
        self.trailer.update(dict_value(dic))
        log.debug("trailer=%r", self.trailer)

    def __repr__(self) -> str:
        return "<PDFXRefTable: offsets=%r>" % (self.offsets.keys())

    @property
    def objids(self) -> Iterable[int]:
        return self.offsets.keys()

    def get_pos(self, objid: int) -> Tuple[Optional[int], int, int]:
        return self.offsets[objid]


PDFOBJ_CUE = re.compile(r"^(\d+)\s+(\d+)\s+obj\b")


class PDFXRefFallback(PDFXRefTable):
    """Fallback implementation of cross-reference table, for broken
    PDFs I guess?
    """

    def __repr__(self) -> str:
        return "<PDFXRefFallback: offsets=%r>" % (self.offsets.keys())

    def _load(self, parser: PDFParser) -> None:
        parser.seek(0)
        while 1:
            try:
                (pos, line_bytes) = parser.nextline()
            except PSEOF:
                break
            if line_bytes.startswith(b"trailer"):
                parser.seek(pos)
                self._load_trailer(parser)
                log.debug("trailer: %r", self.trailer)
                break
            line = line_bytes.decode("latin-1")  # default pdf encoding
            m = PDFOBJ_CUE.match(line)
            if not m:
                continue
            (objid_s, genno_s) = m.groups()
            objid = int(objid_s)
            genno = int(genno_s)
            self.offsets[objid] = (None, pos, genno)
            # expand ObjStm.
            parser.seek(pos)
            (_, obj) = parser.nextobject()
            if isinstance(obj, PDFStream) and obj.get("Type") is LITERAL_OBJSTM:
                stream = stream_value(obj)
                try:
                    n = stream["N"]
                except KeyError:
                    if settings.STRICT:
                        raise PDFSyntaxError("N is not defined: %r" % stream)
                    n = 0
                parser1 = PDFStreamParser(stream.get_data())
                objs: List[int] = []
                try:
                    while 1:
                        (_, obj) = parser1.nextobject()
                        objs.append(cast(int, obj))
                except PSEOF:
                    pass
                n = min(n, len(objs) // 2)
                for index in range(n):
                    objid1 = objs[index * 2]
                    self.offsets[objid1] = (objid, index, 0)


class PDFXRefStream:
    """Cross-reference stream (as of PDF 1.5)"""

    def __init__(self, parser: PDFParser) -> None:
        self.data: Optional[bytes] = None
        self.entlen: Optional[int] = None
        self.fl1: Optional[int] = None
        self.fl2: Optional[int] = None
        self.fl3: Optional[int] = None
        self.ranges: List[Tuple[int, int]] = []
        self._load(parser)

    def __repr__(self) -> str:
        return "<PDFXRefStream: ranges=%r>" % (self.ranges)

    def _load(self, parser: PDFParser) -> None:
        (_, objid) = parser.nexttoken()  # ignored
        (_, genno) = parser.nexttoken()  # ignored
        (_, kwd) = parser.nexttoken()
        (_, stream) = parser.nextobject()
        if not isinstance(stream, PDFStream) or stream.get("Type") is not LITERAL_XREF:
            raise PDFNoValidXRef("Invalid PDF stream spec.")
        size = stream["Size"]
        index_array = stream.get("Index", (0, size))
        if len(index_array) % 2 != 0:
            raise PDFSyntaxError("Invalid index number")
        self.ranges.extend(cast(Iterator[Tuple[int, int]], choplist(2, index_array)))
        (self.fl1, self.fl2, self.fl3) = stream["W"]
        assert self.fl1 is not None and self.fl2 is not None and self.fl3 is not None
        self.data = stream.get_data()
        self.entlen = self.fl1 + self.fl2 + self.fl3
        self.trailer = stream.attrs
        log.debug(
            "xref stream: objid=%s, fields=%d,%d,%d",
            ", ".join(map(repr, self.ranges)),
            self.fl1,
            self.fl2,
            self.fl3,
        )

    @property
    def objids(self) -> Iterator[int]:
        for start, nobjs in self.ranges:
            for i in range(nobjs):
                assert self.entlen is not None
                assert self.data is not None
                offset = self.entlen * i
                ent = self.data[offset : offset + self.entlen]
                f1 = nunpack(ent[: self.fl1], 1)
                if f1 == 1 or f1 == 2:
                    yield start + i

    def get_pos(self, objid: int) -> Tuple[Optional[int], int, int]:
        index = 0
        for start, nobjs in self.ranges:
            if start <= objid and objid < start + nobjs:
                index += objid - start
                break
            else:
                index += nobjs
        else:
            raise PDFKeyError(objid)
        assert self.entlen is not None
        assert self.data is not None
        assert self.fl1 is not None and self.fl2 is not None and self.fl3 is not None
        offset = self.entlen * index
        ent = self.data[offset : offset + self.entlen]
        f1 = nunpack(ent[: self.fl1], 1)
        f2 = nunpack(ent[self.fl1 : self.fl1 + self.fl2])
        f3 = nunpack(ent[self.fl1 + self.fl2 :])
        if f1 == 1:
            return (None, f2, f3)
        elif f1 == 2:
            return (f2, f3, 0)
        else:
            # this is a free object
            raise PDFKeyError(objid)


PASSWORD_PADDING = (
    b"(\xbfN^Nu\x8aAd\x00NV\xff\xfa\x01\x08" b"..\x00\xb6\xd0h>\x80/\x0c\xa9\xfedSiz"
)


class PDFStandardSecurityHandler:
    """Basic security handler for basic encryption types."""

    supported_revisions: Tuple[int, ...] = (2, 3)

    def __init__(
        self,
        docid: Sequence[bytes],
        param: Dict[str, Any],
        password: str = "",
    ) -> None:
        self.docid = docid
        self.param = param
        self.password = password
        self.init()

    def init(self) -> None:
        self.init_params()
        if self.r not in self.supported_revisions:
            error_msg = "Unsupported revision: param=%r" % self.param
            raise PDFEncryptionError(error_msg)
        self.init_key()

    def init_params(self) -> None:
        self.v = int_value(self.param.get("V", 0))
        self.r = int_value(self.param["R"])
        self.p = uint_value(self.param["P"], 32)
        self.o = str_value(self.param["O"])
        self.u = str_value(self.param["U"])
        self.length = int_value(self.param.get("Length", 40))

    def init_key(self) -> None:
        self.key = self.authenticate(self.password)
        if self.key is None:
            raise PDFPasswordIncorrect

    @property
    def is_printable(self) -> bool:
        return bool(self.p & 4)

    @property
    def is_modifiable(self) -> bool:
        return bool(self.p & 8)

    @property
    def is_extractable(self) -> bool:
        return bool(self.p & 16)

    def compute_u(self, key: bytes) -> bytes:
        if self.r == 2:
            # Algorithm 3.4
            return Arcfour(key).encrypt(PASSWORD_PADDING)  # 2
        else:
            # Algorithm 3.5
            hash = md5(PASSWORD_PADDING)  # 2
            hash.update(self.docid[0])  # 3
            result = Arcfour(key).encrypt(hash.digest())  # 4
            for i in range(1, 20):  # 5
                k = b"".join(bytes((c ^ i,)) for c in iter(key))
                result = Arcfour(k).encrypt(result)
            result += result  # 6
            return result

    def compute_encryption_key(self, password: bytes) -> bytes:
        # Algorithm 3.2
        password = (password + PASSWORD_PADDING)[:32]  # 1
        hash = md5(password)  # 2
        hash.update(self.o)  # 3
        # See https://github.com/pdfminer/pdfminer.six/issues/186
        hash.update(struct.pack("<L", self.p))  # 4
        hash.update(self.docid[0])  # 5
        if self.r >= 4:
            if not cast(PDFStandardSecurityHandlerV4, self).encrypt_metadata:
                hash.update(b"\xff\xff\xff\xff")
        result = hash.digest()
        n = 5
        if self.r >= 3:
            n = self.length // 8
            for _ in range(50):
                result = md5(result[:n]).digest()
        return result[:n]

    def authenticate(self, password: str) -> Optional[bytes]:
        password_bytes = password.encode("latin1")
        key = self.authenticate_user_password(password_bytes)
        if key is None:
            key = self.authenticate_owner_password(password_bytes)
        return key

    def authenticate_user_password(self, password: bytes) -> Optional[bytes]:
        key = self.compute_encryption_key(password)
        if self.verify_encryption_key(key):
            return key
        else:
            return None

    def verify_encryption_key(self, key: bytes) -> bool:
        # Algorithm 3.6
        u = self.compute_u(key)
        if self.r == 2:
            return u == self.u
        return u[:16] == self.u[:16]

    def authenticate_owner_password(self, password: bytes) -> Optional[bytes]:
        # Algorithm 3.7
        password = (password + PASSWORD_PADDING)[:32]
        hash = md5(password)
        if self.r >= 3:
            for _ in range(50):
                hash = md5(hash.digest())
        n = 5
        if self.r >= 3:
            n = self.length // 8
        key = hash.digest()[:n]
        if self.r == 2:
            user_password = Arcfour(key).decrypt(self.o)
        else:
            user_password = self.o
            for i in range(19, -1, -1):
                k = b"".join(bytes((c ^ i,)) for c in iter(key))
                user_password = Arcfour(k).decrypt(user_password)
        return self.authenticate_user_password(user_password)

    def decrypt(
        self,
        objid: int,
        genno: int,
        data: bytes,
        attrs: Optional[Dict[str, Any]] = None,
    ) -> bytes:
        return self.decrypt_rc4(objid, genno, data)

    def decrypt_rc4(self, objid: int, genno: int, data: bytes) -> bytes:
        assert self.key is not None
        key = self.key + struct.pack("<L", objid)[:3] + struct.pack("<L", genno)[:2]
        hash = md5(key)
        key = hash.digest()[: min(len(key), 16)]
        return Arcfour(key).decrypt(data)


class PDFStandardSecurityHandlerV4(PDFStandardSecurityHandler):
    """Security handler for encryption type 4."""

    supported_revisions: Tuple[int, ...] = (4,)

    def init_params(self) -> None:
        super().init_params()
        self.length = 128
        self.cf = dict_value(self.param.get("CF"))
        self.stmf = literal_name(self.param["StmF"])
        self.strf = literal_name(self.param["StrF"])
        self.encrypt_metadata = bool(self.param.get("EncryptMetadata", True))
        if self.stmf != self.strf:
            error_msg = "Unsupported crypt filter: param=%r" % self.param
            raise PDFEncryptionError(error_msg)
        self.cfm = {}
        for k, v in self.cf.items():
            f = self.get_cfm(literal_name(v["CFM"]))
            if f is None:
                error_msg = "Unknown crypt filter method: param=%r" % self.param
                raise PDFEncryptionError(error_msg)
            self.cfm[k] = f
        self.cfm["Identity"] = self.decrypt_identity
        if self.strf not in self.cfm:
            error_msg = "Undefined crypt filter: param=%r" % self.param
            raise PDFEncryptionError(error_msg)

    def get_cfm(self, name: str) -> Optional[Callable[[int, int, bytes], bytes]]:
        if name == "V2":
            return self.decrypt_rc4
        elif name == "AESV2":
            return self.decrypt_aes128
        else:
            return None

    def decrypt(
        self,
        objid: int,
        genno: int,
        data: bytes,
        attrs: Optional[Dict[str, Any]] = None,
        name: Optional[str] = None,
    ) -> bytes:
        if not self.encrypt_metadata and attrs is not None:
            t = attrs.get("Type")
            if t is not None and literal_name(t) == "Metadata":
                return data
        if name is None:
            name = self.strf
        return self.cfm[name](objid, genno, data)

    def decrypt_identity(self, objid: int, genno: int, data: bytes) -> bytes:
        return data

    def decrypt_aes128(self, objid: int, genno: int, data: bytes) -> bytes:
        assert self.key is not None
        key = (
            self.key
            + struct.pack("<L", objid)[:3]
            + struct.pack("<L", genno)[:2]
            + b"sAlT"
        )
        hash = md5(key)
        key = hash.digest()[: min(len(key), 16)]
        initialization_vector = data[:16]
        ciphertext = data[16:]
        cipher = Cipher(
            algorithms.AES(key),
            modes.CBC(initialization_vector),
            backend=default_backend(),
        )  # type: ignore
        return cipher.decryptor().update(ciphertext)  # type: ignore


class PDFStandardSecurityHandlerV5(PDFStandardSecurityHandlerV4):
    """Security handler for encryption types 5 and 6."""

    supported_revisions = (5, 6)

    def init_params(self) -> None:
        super().init_params()
        self.length = 256
        self.oe = str_value(self.param["OE"])
        self.ue = str_value(self.param["UE"])
        self.o_hash = self.o[:32]
        self.o_validation_salt = self.o[32:40]
        self.o_key_salt = self.o[40:]
        self.u_hash = self.u[:32]
        self.u_validation_salt = self.u[32:40]
        self.u_key_salt = self.u[40:]

    def get_cfm(self, name: str) -> Optional[Callable[[int, int, bytes], bytes]]:
        if name == "AESV3":
            return self.decrypt_aes256
        else:
            return None

    def authenticate(self, password: str) -> Optional[bytes]:
        password_b = self._normalize_password(password)
        hash = self._password_hash(password_b, self.o_validation_salt, self.u)
        if hash == self.o_hash:
            hash = self._password_hash(password_b, self.o_key_salt, self.u)
            cipher = Cipher(
                algorithms.AES(hash),
                modes.CBC(b"\0" * 16),
                backend=default_backend(),
            )  # type: ignore
            return cipher.decryptor().update(self.oe)  # type: ignore
        hash = self._password_hash(password_b, self.u_validation_salt)
        if hash == self.u_hash:
            hash = self._password_hash(password_b, self.u_key_salt)
            cipher = Cipher(
                algorithms.AES(hash),
                modes.CBC(b"\0" * 16),
                backend=default_backend(),
            )  # type: ignore
            return cipher.decryptor().update(self.ue)  # type: ignore
        return None

    def _normalize_password(self, password: str) -> bytes:
        if self.r == 6:
            # saslprep expects non-empty strings, apparently
            if not password:
                return b""
            from playa._saslprep import saslprep

            password = saslprep(password)
        return password.encode("utf-8")[:127]

    def _password_hash(
        self,
        password: bytes,
        salt: bytes,
        vector: Optional[bytes] = None,
    ) -> bytes:
        """Compute password hash depending on revision number"""
        if self.r == 5:
            return self._r5_password(password, salt, vector)
        return self._r6_password(password, salt[0:8], vector)

    def _r5_password(
        self,
        password: bytes,
        salt: bytes,
        vector: Optional[bytes] = None,
    ) -> bytes:
        """Compute the password for revision 5"""
        hash = sha256(password)
        hash.update(salt)
        if vector is not None:
            hash.update(vector)
        return hash.digest()

    def _r6_password(
        self,
        password: bytes,
        salt: bytes,
        vector: Optional[bytes] = None,
    ) -> bytes:
        """Compute the password for revision 6"""
        initial_hash = sha256(password)
        initial_hash.update(salt)
        if vector is not None:
            initial_hash.update(vector)
        k = initial_hash.digest()
        hashes = (sha256, sha384, sha512)
        round_no = last_byte_val = 0
        while round_no < 64 or last_byte_val > round_no - 32:
            k1 = (password + k + (vector or b"")) * 64
            e = self._aes_cbc_encrypt(key=k[:16], iv=k[16:32], data=k1)
            # compute the first 16 bytes of e,
            # interpreted as an unsigned integer mod 3
            next_hash = hashes[self._bytes_mod_3(e[:16])]
            k = next_hash(e).digest()
            last_byte_val = e[len(e) - 1]
            round_no += 1
        return k[:32]

    @staticmethod
    def _bytes_mod_3(input_bytes: bytes) -> int:
        # 256 is 1 mod 3, so we can just sum 'em
        return sum(b % 3 for b in input_bytes) % 3

    def _aes_cbc_encrypt(self, key: bytes, iv: bytes, data: bytes) -> bytes:
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
        encryptor = cipher.encryptor()  # type: ignore
        return encryptor.update(data) + encryptor.finalize()  # type: ignore

    def decrypt_aes256(self, objid: int, genno: int, data: bytes) -> bytes:
        initialization_vector = data[:16]
        ciphertext = data[16:]
        assert self.key is not None
        cipher = Cipher(
            algorithms.AES(self.key),
            modes.CBC(initialization_vector),
            backend=default_backend(),
        )  # type: ignore
        return cipher.decryptor().update(ciphertext)  # type: ignore


SECURITY_HANDLERS = {
    1: PDFStandardSecurityHandler,
    2: PDFStandardSecurityHandler,
    4: PDFStandardSecurityHandlerV4,
    5: PDFStandardSecurityHandlerV5,
}


def read_header(fp: BinaryIO) -> str:
    """Read the PDF header and return the (initial) version string.

    Note that this version can be overridden in the document catalog."""
    try:
        hdr = fp.read(8)
    except IOError as err:
        raise PDFSyntaxError("Failed to read PDF header") from err
    if not hdr.startswith(b"%PDF-"):
        # Try harder... there might be some extra junk before it
        fp.seek(0)
        hdr += fp.read(4096)
        start = hdr.find(b"%PDF-")
        if start == -1:
            raise PDFSyntaxError("Could not find b'%%PDF-', is this a PDF?")
        hdr = hdr[start : start + 8]
        fp.seek(start)
    try:
        version = hdr[5:].decode("ascii")
    except UnicodeDecodeError as err:
        raise PDFSyntaxError(
            "Version number in %r contains non-ASCII characters" % hdr
        ) from err
    if not re.match(r"\d\.\d", version):
        raise PDFSyntaxError("Version number in  %r is invalid" % hdr)
    return version


class OutlineItem(NamedTuple):
    """The most relevant fields of an outline item dictionary."""

    level: int
    title: str
    dest: Union[PSLiteral, bytes, list, None]
    action: Union[dict, None]
    se: Union[PDFObjRef, None]


class PDFDocument:
    """Representation of a PDF document on disk.

    Since PDF documents can be very large and complex, merely creating
    a `PDFDocument` does very little aside from opening the file and
    verifying that the password is correct and it is, in fact, a PDF.
    This may, however, involve a certain amount of random file access
    since the cross-reference table and trailer must be read in order
    to determine this (we do not treat linearized PDFs specially for
    the moment).

    Some metadata, such as the structure tree and page tree, will be
    loaded lazily and cached.  Because PLAYA is a LAYout Analyzer, we
    do not handle modification of PDFs, and all such data can be
    assumed to be constant and read-only.

    Args:
      fp: File-like object in binary mode.  Must support random access.
      password: Password for decryption, if needed.

    """

    _fp: Union[BinaryIO, None] = None

    def __enter__(self) -> "PDFDocument":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        # Undo the circular reference
        self.parser.set_document(None)
        # If we were opened from a file then close it
        if self._fp:
            self._fp.close()
            self._fp = None

    def __init__(
        self,
        fp: BinaryIO,
        password: str = "",
    ) -> None:
        self.xrefs: List[PDFXRef] = []
        self.info = []
        self.catalog: Dict[str, Any] = {}
        self.encryption: Optional[Tuple[Any, Any]] = None
        self.decipher: Optional[DecipherCallable] = None
        self._cached_objs: Dict[int, Tuple[object, int]] = {}
        self._parsed_objs: Dict[int, Tuple[List[object], int]] = {}
        if isinstance(fp, io.TextIOBase):
            raise PSException("fp is not a binary file")
        self.pdf_version = read_header(fp)
        self.parser = PDFParser(fp)
        self.parser.set_document(self)  # FIXME: annoying circular reference
        self.is_printable = self.is_modifiable = self.is_extractable = True
        # Getting the XRef table and trailer is done non-lazily
        # because they contain encryption information among other
        # things.  As noted above we don't try to look for the first
        # page cross-reference table (for linearized PDFs) after the
        # header, it will instead be loaded with all the rest.
        try:
            pos = self.find_xref()
            self.read_xref_from(pos, self.xrefs)
        except PDFNoValidXRef as e:
            log.debug("Using fallback XRef parsing: %s", e)
            self.parser.fallback = True
            newxref = PDFXRefFallback(self.parser)
            self.xrefs.append(newxref)
        # Now find the trailer
        for xref in self.xrefs:
            trailer = xref.trailer
            if not trailer:
                continue
            # If there's an encryption info, remember it.
            if "Encrypt" in trailer:
                if "ID" in trailer:
                    id_value = list_value(trailer["ID"])
                else:
                    # Some documents may not have a /ID, use two empty
                    # byte strings instead. Solves
                    # https://github.com/pdfminer/pdfminer.six/issues/594
                    id_value = (b"", b"")
                self.encryption = (id_value, dict_value(trailer["Encrypt"]))
                self._initialize_password(password)
            if "Info" in trailer:
                self.info.append(dict_value(trailer["Info"]))
            if "Root" in trailer:
                # Every PDF file must have exactly one /Root dictionary.
                self.catalog = dict_value(trailer["Root"])
                break
        else:
            raise PDFSyntaxError("No /Root object! - Is this really a PDF?")
        if self.catalog.get("Type") is not LITERAL_CATALOG:
            if settings.STRICT:
                raise PDFSyntaxError("Catalog not found!")

    def _initialize_password(self, password: str = "") -> None:
        """Initialize the decryption handler with a given password, if any.

        Internal function, requires the Encrypt dictionary to have
        been read from the trailer into self.encryption.
        """
        assert self.encryption is not None
        (docid, param) = self.encryption
        if literal_name(param.get("Filter")) != "Standard":
            raise PDFEncryptionError("Unknown filter: param=%r" % param)
        v = int_value(param.get("V", 0))
        # 3 (PDF 1.4) An unpublished algorithm that permits encryption
        # key lengths ranging from 40 to 128 bits. This value shall
        # not appear in a conforming PDF file.
        if v == 3:
            raise PDFEncryptionError("Unpublished algorithm 3 not supported")
        factory = SECURITY_HANDLERS.get(v)
        # 0 An algorithm that is undocumented. This value shall not be used.
        if factory is None:
            raise PDFEncryptionError("Unknown algorithm: param=%r" % param)
        handler = factory(docid, param, password)
        self.decipher = handler.decrypt
        self.is_printable = handler.is_printable
        self.is_modifiable = handler.is_modifiable
        self.is_extractable = handler.is_extractable
        assert self.parser is not None
        self.parser.fallback = False  # need to read streams with exact length

    def _getobj_objstm(self, stream: PDFStream, index: int, objid: int) -> object:
        if stream.objid in self._parsed_objs:
            (objs, n) = self._parsed_objs[stream.objid]
        else:
            (objs, n) = self._get_objects(stream)
            assert stream.objid is not None
            self._parsed_objs[stream.objid] = (objs, n)
        i = n * 2 + index
        try:
            obj = objs[i]
        except IndexError:
            raise PDFSyntaxError("index too big: %r" % index)
        return obj

    def _get_objects(self, stream: PDFStream) -> Tuple[List[object], int]:
        if stream.get("Type") is not LITERAL_OBJSTM:
            if settings.STRICT:
                raise PDFSyntaxError("Not a stream object: %r" % stream)
        try:
            n = cast(int, stream["N"])
        except KeyError:
            if settings.STRICT:
                raise PDFSyntaxError("N is not defined: %r" % stream)
            n = 0
        parser = PDFStreamParser(stream.get_data())
        parser.set_document(self)
        objs: List[object] = []
        try:
            while 1:
                (_, obj) = parser.nextobject()
                objs.append(obj)
        except PSEOF:
            pass
        return (objs, n)

    def _getobj_parse(self, pos: int, objid: int) -> object:
        assert self.parser is not None
        self.parser.seek(pos)
        (_, objid1) = self.parser.nexttoken()  # objid
        (_, genno) = self.parser.nexttoken()  # genno
        (_, kwd) = self.parser.nexttoken()
        # hack around malformed pdf files
        # copied from https://github.com/jaepil/pdfminer3k/blob/master/
        # pdfminer/pdfparser.py#L399
        # to solve https://github.com/pdfminer/pdfminer.six/issues/56
        # assert objid1 == objid, str((objid1, objid))
        if objid1 != objid:
            x = []
            while kwd is not KEYWORD_OBJ:
                (_, kwd) = self.parser.nexttoken()
                x.append(kwd)
            if len(x) >= 2:
                objid1 = x[-2]
        # #### end hack around malformed pdf files
        if objid1 != objid:
            raise PDFSyntaxError(f"objid mismatch: {objid1!r}={objid!r}")

        if kwd != KWD(b"obj"):
            raise PDFSyntaxError("Invalid object spec: offset=%r" % pos)
        (_, obj) = self.parser.nextobject()
        return obj

    def __getitem__(self, objid: int) -> object:
        """Get object from PDF

        :raises PDFException if PDFDocument is not initialized
        :raises IndexError if objid does not exist in PDF
        """
        if not self.xrefs:
            raise PDFException("PDFDocument is not initialized")
        log.debug("getobj: objid=%r", objid)
        if objid in self._cached_objs:
            (obj, genno) = self._cached_objs[objid]
        else:
            obj = None
            for xref in self.xrefs:
                try:
                    (strmid, index, genno) = xref.get_pos(objid)
                except KeyError:
                    continue
                try:
                    if strmid is not None:
                        stream = stream_value(self[strmid])
                        obj = self._getobj_objstm(stream, index, objid)
                    else:
                        obj = self._getobj_parse(index, objid)
                        if self.decipher:
                            obj = decipher_all(self.decipher, objid, genno, obj)

                    if isinstance(obj, PDFStream):
                        obj.set_objid(objid, genno)
                    break
                except (PSEOF, PDFSyntaxError):
                    continue
            if obj is None:
                raise IndexError(f"Object with ID {objid} not found")
            log.debug("register: objid=%r: %r", objid, obj)
            self._cached_objs[objid] = (obj, genno)
        return obj

    @property
    def outlines(self) -> Iterator[OutlineItem]:
        if "Outlines" not in self.catalog:
            raise PDFNoOutlines

        def search(entry: object, level: int) -> Iterator[OutlineItem]:
            entry = dict_value(entry)
            if "Title" in entry:
                if "A" in entry or "Dest" in entry:
                    title = decode_text(str_value(entry["Title"]))
                    dest = entry.get("Dest")
                    action = entry.get("A")
                    se = entry.get("SE")
                    yield OutlineItem(
                        level, title, resolve1(dest), resolve1(action), se
                    )
            if "First" in entry and "Last" in entry:
                yield from search(entry["First"], level + 1)
            if "Next" in entry:
                yield from search(entry["Next"], level)

        return search(self.catalog["Outlines"], 0)

    @property
    def page_labels(self) -> Iterator[str]:
        """Generate page label strings for the PDF document.

        If the document includes page labels, generates strings, one per page.
        If not, raises PDFNoPageLabels.

        The resulting iterator is unbounded, so it is recommended to
        zip it with the iterator over actual pages returned by `get_pages`.

        """
        assert self.catalog is not None

        try:
            page_labels = PageLabels(self.catalog["PageLabels"])
        except (PDFTypeError, KeyError):
            raise PDFNoPageLabels

        return page_labels.labels

    PageType = Dict[Any, Dict[Any, Any]]

    def get_pages_from_xrefs(self) -> Iterator[Tuple[int, PageType]]:
        """Find pages from the cross-reference tables if the page tree
        is missing (note that this only happens in invalid PDFs, but
        it happens.)

        Returns an iterator over (objid, dict) pairs.
        """
        for xref in self.xrefs:
            for object_id in xref.objids:
                try:
                    obj = self[object_id]
                    if isinstance(obj, dict) and obj.get("Type") is LITERAL_PAGE:
                        yield object_id, obj
                except IndexError:
                    pass

    def get_page_objects(self) -> Iterator[Tuple[int, PageType]]:
        """Iterate over the flattened page tree in reading order, propagating
        inheritable attributes.  Returns an iterator over (objid, dict) pairs.

        Will raise PDFNoPageTree if there is no page tree.
        """
        if "Pages" not in self.catalog:
            raise PDFNoPageTree("No 'Pages' entry in catalog")
        stack = [(self.catalog["Pages"], self.catalog)]
        visited = set()
        while stack:
            (obj, parent) = stack.pop()
            if isinstance(obj, PDFObjRef):
                # The PDF specification *requires* both the Pages
                # element of the catalog and the entries in Kids in
                # the page tree to be indirect references.
                object_id = obj.objid
            elif isinstance(obj, int):
                # Should not happen in a valid PDF, but probably does?
                log.warning("Page tree contains bare integer: %r in %r", obj, parent)
                object_id = obj
            else:
                log.warning("Page tree contains unknown object: %r", obj)
            page_object = dict_value(self[object_id])

            # Avoid recursion errors by keeping track of visited nodes
            # (again, this should never actually happen in a valid PDF)
            if object_id in visited:
                log.warning("Circular reference %r in page tree", obj)
                continue
            visited.add(object_id)

            # Propagate inheritable attributes
            object_properties = page_object.copy()
            for k, v in parent.items():
                if k in INHERITABLE_PAGE_ATTRS and k not in object_properties:
                    object_properties[k] = v

            # Recurse, depth-first
            object_type = object_properties.get("Type")
            if object_type is None and not settings.STRICT:  # See #64
                object_type = object_properties.get("type")
            if object_type is LITERAL_PAGES and "Kids" in object_properties:
                log.debug("Pages: Kids=%r", object_properties["Kids"])
                for child in reversed(list_value(object_properties["Kids"])):
                    stack.append((child, object_properties))
            elif object_type is LITERAL_PAGE:
                log.debug("Page: %r", object_properties)
                yield object_id, object_properties

    @property
    def pages(self) -> Iterator[PDFPage]:
        """Iterator over PDFPage objects, which contain
        information about the pages in the document.
        """
        try:
            page_labels: Iterator[Optional[str]] = self.page_labels
        except PDFNoPageLabels:
            page_labels = itertools.repeat(None)
        try:
            for (objid, properties), label in zip(self.get_page_objects(), page_labels):
                yield PDFPage(objid, properties, label)
        except PDFNoPageTree:
            for (objid, properties), label in zip(
                self.get_pages_from_xrefs(), page_labels
            ):
                yield PDFPage(objid, properties, label)

    @property
    def names(self) -> Dict[str, Any]:
        """PDF name dictionary (PDF 1.7 sec 7.7.4). Raises KeyError if
        nonexistent.
        """
        return dict_value(self.catalog["Names"])

    @property
    def dests(self) -> Iterable[Tuple[str, Any]]:
        """Iterable of named destinations as (name, object) tuples
        (PDF 1.7 sec 12.3.2). Raises KeyError if no destination
        dictionary exists.

        Note that we assume the names of destinations are either "name
        objects" (that's PDF for UTF-8) or "text strings", since the
        PDF spec says (p. 367):

        > The keys in the name tree may be treated as text strings for
        > display purposes.

        therefore, you get them as `str`.
        """
        try:
            # PDF-1.2 or later
            return ((decode_text(k), v) for k, v in NameTree(self.names["Dests"]))
        except KeyError:
            # PDF-1.1 or prior
            return dict_value(self.catalog["Dests"]).items()

    # find_xref
    def find_xref(self) -> int:
        """Internal function used to locate the first XRef."""
        # search the last xref table by scanning the file backwards.
        prev = b""
        # FIXME: This will scan *the whole file* looking for an xref
        # table, it should maybe give up sooner?
        for line in self.parser.revreadlines():
            line = line.strip()
            log.debug("find_xref: %r", line)
            if line == b"startxref":
                log.debug("xref found: pos=%r", prev)
                if not prev.isdigit():
                    raise PDFNoValidXRef(f"Invalid xref position: {prev!r}")
                start = int(prev)
                if not start >= 0:
                    raise PDFNoValidXRef(f"Invalid negative xref position: {start}")
                return start
            if line:
                prev = line
        raise PDFNoValidXRef("No xref table found at end of file")

    # read xref table
    def read_xref_from(
        self,
        start: int,
        xrefs: List[PDFXRef],
    ) -> None:
        """Reads XRefs from the given location."""
        self.parser.seek(start)
        self.parser.reset()
        try:
            (pos, token) = self.parser.nexttoken()
        except PSEOF:
            raise PDFNoValidXRef("Unexpected EOF at {start}")
        log.debug("read_xref_from: start=%d, token=%r", start, token)
        if isinstance(token, int):
            # XRefStream: PDF-1.5
            self.parser.seek(pos)
            self.parser.reset()
            xref: PDFXRef = PDFXRefStream(self.parser)
        else:
            if token is KEYWORD_XREF:
                self.parser.nextline()
            xref = PDFXRefTable(self.parser)
        xrefs.append(xref)
        trailer = xref.trailer
        log.debug("trailer: %r", trailer)
        if "XRefStm" in trailer:
            pos = int_value(trailer["XRefStm"])
            self.read_xref_from(pos, xrefs)
        if "Prev" in trailer:
            # find previous xref
            pos = int_value(trailer["Prev"])
            self.read_xref_from(pos, xrefs)


class PageLabels(NumberTree):
    """PageLabels from the document catalog.

    See Section 12.4.2 in the PDF 1.7 Reference.
    """

    @property
    def labels(self) -> Iterator[str]:
        itor = iter(self)
        try:
            start, label_dict_unchecked = next(itor)
            # The tree must begin with page index 0
            if start != 0:
                if settings.STRICT:
                    raise PDFSyntaxError("PageLabels is missing page index 0")
                else:
                    # Try to cope, by assuming empty labels for the initial pages
                    start = 0
        except StopIteration:
            if settings.STRICT:
                raise PDFSyntaxError("PageLabels is empty")
            start = 0
            label_dict_unchecked = {}

        while True:  # forever!
            label_dict = dict_value(label_dict_unchecked)
            style = label_dict.get("S")
            prefix = decode_text(str_value(label_dict.get("P", b"")))
            first_value = int_value(label_dict.get("St", 1))

            try:
                next_start, label_dict_unchecked = next(itor)
            except StopIteration:
                # This is the last specified range. It continues until the end
                # of the document.
                values: Iterable[int] = itertools.count(first_value)
            else:
                range_length = next_start - start
                values = range(first_value, first_value + range_length)
                start = next_start

            for value in values:
                label = self._format_page_label(value, style)
                yield prefix + label

    @staticmethod
    def _format_page_label(value: int, style: Any) -> str:
        """Format page label value in a specific style"""
        if style is None:
            label = ""
        elif style is LIT("D"):  # Decimal arabic numerals
            label = str(value)
        elif style is LIT("R"):  # Uppercase roman numerals
            label = format_int_roman(value).upper()
        elif style is LIT("r"):  # Lowercase roman numerals
            label = format_int_roman(value)
        elif style is LIT("A"):  # Uppercase letters A-Z, AA-ZZ...
            label = format_int_alpha(value).upper()
        elif style is LIT("a"):  # Lowercase letters a-z, aa-zz...
            label = format_int_alpha(value)
        else:
            log.warning("Unknown page label style: %r", style)
            label = ""
        return label
