"""Adobe character mapping (CMap) support.

CMaps provide the mapping between character codes and Unicode
code-points to character ids (CIDs).

More information is available on:

  https://github.com/adobe-type-tools/cmap-resources

"""

from bisect import bisect_left
import functools
import gzip
import logging
import os
import os.path
import pickle as pickle
import struct
import sys
from typing import (
    Any,
    Dict,
    Iterable,
    Iterator,
    List,
    MutableMapping,
    Optional,
    TextIO,
    Tuple,
    Union,
    cast,
)

from playa.exceptions import PDFSyntaxError
from playa.parser import (
    KWD,
    ObjectParser,
    PDFObject,
    PSKeyword,
    literal_name,
)
from playa.utils import choplist, nunpack

log = logging.getLogger(__name__)


class CMapError(Exception):
    pass


class CMapBase:
    debug = 0

    def __init__(self, **kwargs: object) -> None:
        self.attrs: MutableMapping[str, object] = kwargs.copy()

    def is_vertical(self) -> bool:
        return self.attrs.get("WMode", 0) != 0

    def set_attr(self, k: str, v: object) -> None:
        self.attrs[k] = v

    def use_cmap(self, cmap: "CMapBase") -> None:
        pass

    def decode(self, code: bytes) -> Iterable[int]:
        raise NotImplementedError


class CMap(CMapBase):
    def __init__(self, **kwargs: Union[str, int]) -> None:
        CMapBase.__init__(self, **kwargs)
        self.code2cid: Dict[int, object] = {}

    def __repr__(self) -> str:
        return "<CMap: %s>" % self.attrs.get("CMapName")

    def use_cmap(self, cmap: CMapBase) -> None:
        assert isinstance(cmap, CMap), str(type(cmap))

        def copy(dst: Dict[int, object], src: Dict[int, object]) -> None:
            for k, v in src.items():
                if isinstance(v, dict):
                    d: Dict[int, object] = {}
                    dst[k] = d
                    copy(d, v)
                else:
                    dst[k] = v

        copy(self.code2cid, cmap.code2cid)

    def decode(self, code: bytes) -> Iterator[int]:
        log.debug("decode: %r, %r", self, code)
        d = self.code2cid
        for i in iter(code):
            if i in d:
                x = d[i]
                if isinstance(x, int):
                    yield x
                    d = self.code2cid
                else:
                    d = cast(Dict[int, object], x)
            else:
                d = self.code2cid

    def dump(
        self,
        out: TextIO = sys.stdout,
        code2cid: Optional[Dict[int, object]] = None,
        code: Tuple[int, ...] = (),
    ) -> None:
        if code2cid is None:
            code2cid = self.code2cid
            code = ()
        for k, v in sorted(code2cid.items()):
            c = code + (k,)
            if isinstance(v, int):
                out.write("code %r = cid %d\n" % (c, v))
            else:
                self.dump(out=out, code2cid=cast(Dict[int, object], v), code=c)


class IdentityCMap(CMapBase):
    def decode(self, code: bytes) -> Tuple[int, ...]:
        n = len(code) // 2
        if n:
            return struct.unpack(">%dH" % n, code)
        else:
            return ()


class IdentityCMapByte(IdentityCMap):
    def decode(self, code: bytes) -> Tuple[int, ...]:
        n = len(code)
        if n:
            return struct.unpack(">%dB" % n, code)
        else:
            return ()


class UnicodeMap(CMapBase):
    def __init__(self, **kwargs: Union[str, int]) -> None:
        CMapBase.__init__(self, **kwargs)
        self.cid2unichr: Dict[int, str] = {}

    def __repr__(self) -> str:
        return "<UnicodeMap: %s>" % self.attrs.get("CMapName")

    def get_unichr(self, cid: int) -> str:
        log.debug("get_unichr: %r, %r", self, cid)
        return self.cid2unichr[cid]

    def dump(self, out: TextIO = sys.stdout) -> None:
        for k, v in sorted(self.cid2unichr.items()):
            out.write("cid %d = unicode %r\n" % (k, v))


class IdentityUnicodeMap(UnicodeMap):
    def get_unichr(self, cid: int) -> str:
        """Interpret character id as unicode codepoint"""
        log.debug("get_unichr: %r, %r", self, cid)
        return chr(cid)


class PyCMap(CMap):
    def __init__(self, name: str, module: Any) -> None:
        super().__init__(CMapName=name)
        self.code2cid = module.CODE2CID
        if module.IS_VERTICAL:
            self.attrs["WMode"] = 1


class PyUnicodeMap(UnicodeMap):
    def __init__(self, name: str, module: Any, vertical: bool) -> None:
        super().__init__(CMapName=name)
        if vertical:
            self.cid2unichr = module.CID2UNICHR_V
            self.attrs["WMode"] = 1
        else:
            self.cid2unichr = module.CID2UNICHR_H


class CMapDB:
    _cmap_cache: Dict[str, PyCMap] = {}
    _umap_cache: Dict[str, List[PyUnicodeMap]] = {}

    @classmethod
    def _load_data(cls, name: str) -> Any:
        name = name.replace("\0", "")
        filename = "%s.pickle.gz" % name
        log.debug("loading: %r", name)
        cmap_paths = (
            os.environ.get("CMAP_PATH", "/usr/share/pdfminer/"),
            os.path.join(os.path.dirname(__file__), "cmap"),
        )
        for directory in cmap_paths:
            path = os.path.join(directory, filename)
            if os.path.exists(path):
                gzfile = gzip.open(path)
                try:
                    return type(str(name), (), pickle.loads(gzfile.read()))
                finally:
                    gzfile.close()
        raise KeyError(f"CMap {name!r} not found in CMapDB")

    @classmethod
    def get_cmap(cls, name: str) -> CMapBase:
        if name == "Identity-H":
            return IdentityCMap(CMapName=name, WMode=0)
        elif name == "Identity-V":
            return IdentityCMap(CMapName=name, WMode=1)
        elif name == "OneByteIdentityH":
            return IdentityCMapByte(CMapName=name, WMode=0)
        elif name == "OneByteIdentityV":
            return IdentityCMapByte(CMapName=name, WMode=1)
        if name in cls._cmap_cache:
            return cls._cmap_cache[name]
        data = cls._load_data(name)
        cls._cmap_cache[name] = cmap = PyCMap(name, data)
        return cmap

    @classmethod
    def get_unicode_map(cls, name: str, vertical: bool = False) -> UnicodeMap:
        try:
            return cls._umap_cache[name][vertical]
        except KeyError:
            pass
        data = cls._load_data("to-unicode-%s" % name)
        cls._umap_cache[name] = [PyUnicodeMap(name, data, v) for v in (False, True)]
        return cls._umap_cache[name][vertical]


KEYWORD_BEGINCMAP = KWD(b"begincmap")
KEYWORD_ENDCMAP = KWD(b"endcmap")
KEYWORD_USECMAP = KWD(b"usecmap")
KEYWORD_DEF = KWD(b"def")
KEYWORD_BEGINCODESPACERANGE = KWD(b"begincodespacerange")
KEYWORD_ENDCODESPACERANGE = KWD(b"endcodespacerange")
KEYWORD_BEGINCIDRANGE = KWD(b"begincidrange")
KEYWORD_ENDCIDRANGE = KWD(b"endcidrange")
KEYWORD_BEGINCIDCHAR = KWD(b"begincidchar")
KEYWORD_ENDCIDCHAR = KWD(b"endcidchar")
KEYWORD_BEGINBFRANGE = KWD(b"beginbfrange")
KEYWORD_ENDBFRANGE = KWD(b"endbfrange")
KEYWORD_BEGINBFCHAR = KWD(b"beginbfchar")
KEYWORD_ENDBFCHAR = KWD(b"endbfchar")
KEYWORD_BEGINNOTDEFRANGE = KWD(b"beginnotdefrange")
KEYWORD_ENDNOTDEFRANGE = KWD(b"endnotdefrange")


# These are generally characters or short strings (glyph clusters) so
# caching them makes sense (they repeat themselves often)
@functools.cache
def decode_utf16_char(utf16: bytes) -> str:
    return utf16.decode("UTF-16BE", "ignore")


class FileUnicodeMap(UnicodeMap):
    """ToUnicode map loaded from a PDF stream"""

    def add_cid2bytes(self, cid: int, utf16: bytes) -> None:
        self.add_cid2unichr(cid, decode_utf16_char(utf16))

    def add_cid2code(self, cid: int, code: int) -> None:
        unichr = chr(code)
        self.add_cid2unichr(cid, unichr)

    def add_cid2unichr(self, cid: int, unichr: str) -> None:
        # A0 = non-breaking space, some weird fonts can have a collision on a cid here.
        assert isinstance(unichr, str)
        if unichr == "\u00a0" and self.cid2unichr.get(cid) == " ":
            return
        self.cid2unichr[cid] = unichr

    def add_bf_range(self, start_byte: bytes, end_byte: bytes, code: PDFObject) -> None:
        start = nunpack(start_byte)
        end = nunpack(end_byte)
        if isinstance(code, list):
            if len(code) != end - start + 1:
                log.warning(
                    "The difference between the start and end "
                    "offsets does not match the code length.",
                )
            for cid, unicode_value in zip(range(start, end + 1), code):
                assert isinstance(unicode_value, bytes)
                self.add_cid2bytes(cid, unicode_value)
        else:
            assert isinstance(code, bytes)
            var = code[-4:]
            base = nunpack(var)
            prefix = code[:-4]
            vlen = len(var)
            for i in range(end - start + 1):
                x = prefix + struct.pack(">L", base + i)[-vlen:]
                self.add_cid2bytes(start + i, x)


def parse_tounicode(data: bytes) -> FileUnicodeMap:
    cmap = FileUnicodeMap()
    stack: List[PDFObject] = []
    parser = ObjectParser(data)
    # some ToUnicode maps don't have "begincmap" keyword.
    in_cmap = True

    while True:
        try:
            pos, obj = next(parser)
        except PDFSyntaxError as e:
            # CMap syntax is apparently not PDF syntax (e.g. "def"
            # seems to occur within dictionaries, for no apparent
            # reason, perhaps a PostScript thing?)
            log.debug("Ignoring syntax error: %s", e)
            parser.reset()
            continue
        except StopIteration:
            break

        if not isinstance(obj, PSKeyword):
            stack.append(obj)
            continue
        log.debug("keyword: %r (%r)", obj, stack)
        # Ignore everything outside begincmap / endcmap
        if obj is KEYWORD_BEGINCMAP:
            in_cmap = True
            del stack[:]
        elif obj is KEYWORD_ENDCMAP:
            in_cmap = False
        if not in_cmap:
            return cmap

        if obj is KEYWORD_DEF:
            try:
                # Might fail with IndexError if the file is corrputed
                v = stack.pop()
                k = stack.pop()
                cmap.set_attr(literal_name(k), v)
            except (IndexError, TypeError):
                pass
        elif obj is KEYWORD_USECMAP:
            try:
                cmapname = stack.pop()
                cmap.use_cmap(CMapDB.get_cmap(literal_name(cmapname)))
            except (IndexError, TypeError, KeyError):
                pass
        elif obj is KEYWORD_BEGINCODESPACERANGE:
            del stack[:]
        elif obj is KEYWORD_ENDCODESPACERANGE:
            del stack[:]
        elif obj is KEYWORD_BEGINCIDRANGE:
            del stack[:]
        elif obj is KEYWORD_ENDCIDRANGE:
            del stack[:]
        elif obj is KEYWORD_BEGINCIDCHAR:
            del stack[:]
        elif obj is KEYWORD_ENDCIDCHAR:
            del stack[:]
        elif obj is KEYWORD_BEGINBFRANGE:
            del stack[:]
        elif obj is KEYWORD_ENDBFRANGE:
            for start_byte, end_byte, code in choplist(3, stack):
                if not isinstance(start_byte, bytes):
                    log.warning("The start object is not a byte.")
                    continue
                if not isinstance(end_byte, bytes):
                    log.warning("The end object is not a byte.")
                    continue
                if len(start_byte) != len(end_byte):
                    log.warning("The start and end byte have different lengths.")
                    continue
                cmap.add_bf_range(start_byte, end_byte, code)
            del stack[:]
        elif obj is KEYWORD_BEGINBFCHAR:
            del stack[:]
        elif obj is KEYWORD_ENDBFCHAR:
            for cid, code in choplist(2, stack):
                if isinstance(cid, bytes) and isinstance(code, bytes):
                    cmap.add_cid2bytes(nunpack(cid), code)
            del stack[:]
        elif obj is KEYWORD_BEGINNOTDEFRANGE:
            del stack[:]
        elif obj is KEYWORD_ENDNOTDEFRANGE:
            del stack[:]
        else:
            # It's ... something else (probably bogus)
            stack.append(obj)
    return cmap


class EncodingCMap(CMap):
    """Encoding map loaded from a PDF stream."""

    def __init__(self):
        super().__init__()
        self.bytes2cid: Dict[bytes, int] = {}
        self.code_lengths = []
        self.code_space = []

    def add_code_range(self, start: bytes, end: bytes):
        """Add a code-space range"""
        if len(start) != len(end):
            log.warning("Ignoring inconsistent code lengths in code space: %r / %r", start, end)
            return
        codelen = len(start)
        pos = bisect_left(self.code_lengths, codelen)
        self.code_lengths.insert(pos, codelen)
        self.code_space.insert(pos, (start, end))

    def decode(self, code: bytes) -> Tuple[int, ...]:
        idx = 0
        codelen = 1
        codes = []
        while idx < len(code):
            # Match code space ranges
            for codelen, (start, end) in zip(self.code_lengths, self.code_space):
                substr = code[idx : idx + codelen]
                # NOTE: lexicographical ordering is the same as
                # big-endian numerical ordering so this works
                if substr >= start and substr <= end:
                    if substr not in self.bytes2cid:
                        # 9.7.6.3: If a code maps to a CID for which
                        # no such glyph exists in the descendant
                        # CIDFont...
                        # FIXME: Implement notdef mappings
                        codes.append(0)
                    else:
                        codes.append(self.bytes2cid[substr])
                    idx += codelen
                    break
            else:
                # 9.7.6.3 If the code is invalid—that is, the bytes
                # extracted from the string to be shown do not match
                # any codespace range in the CMap...
                log.warning("No code space found for %r", code[idx:])
                # FIXME: Implement the somewhat obscure partial
                # matching algorithm (might consume more than 1 byte)
                idx += 1
        return tuple(codes)

    def add_bytes2cid(self, utf16: bytes, cid: int) -> None:
        self.bytes2cid[utf16] = cid

    def add_cid_range(self, start_byte: bytes, end_byte: bytes, cid: int) -> None:
        start_prefix = start_byte[:-4]
        end_prefix = end_byte[:-4]
        if start_prefix != end_prefix:
            log.warning(
                "The prefix of the start and end byte of "
                "begincidrange are not the same.",
            )
            return
        svar = start_byte[-4:]
        evar = end_byte[-4:]
        start = nunpack(svar)
        end = nunpack(evar)
        vlen = len(svar)
        for i in range(end - start + 1):
            x = start_prefix + struct.pack(">L", start + i)[-vlen:]
            self.add_bytes2cid(x, cid + i)


def parse_encoding(data: bytes) -> EncodingCMap:
    """Parse an Encoding CMap."""
    cmap = EncodingCMap()
    stack: List[PDFObject] = []
    parser = ObjectParser(data)

    while True:
        try:
            pos, obj = next(parser)
        except PDFSyntaxError as e:
            log.debug("Ignoring syntax error: %s", e)
            parser.reset()
            continue
        except StopIteration:
            break

        if not isinstance(obj, PSKeyword):
            stack.append(obj)
            continue
        log.debug("keyword: %r (%r)", obj, stack)

        if obj is KEYWORD_DEF:
            try:
                # Might fail with IndexError if the file is corrputed
                v = stack.pop()
                k = stack.pop()
                cmap.set_attr(literal_name(k), v)
            except (IndexError, TypeError):
                pass
        elif obj is KEYWORD_USECMAP:
            log.warning("usecmap not supported for EncodingCMap")
            del stack[:]
        elif obj is KEYWORD_BEGINCODESPACERANGE:
            del stack[:]
        elif obj is KEYWORD_ENDCODESPACERANGE:
            for start_code, end_code in choplist(2, stack):
                cmap.add_code_range(start_code, end_code)
            del stack[:]
        elif obj is KEYWORD_BEGINCIDRANGE:
            del stack[:]
        elif obj is KEYWORD_ENDCIDRANGE:
            for start_byte, end_byte, cid in choplist(3, stack):
                if not isinstance(start_byte, bytes):
                    log.warning("The start object of begincidrange is not a byte.")
                    return cmap
                if not isinstance(end_byte, bytes):
                    log.warning("The end object of begincidrange is not a byte.")
                    return cmap
                if not isinstance(cid, int):
                    log.warning("The cid object of begincidrange is not a byte.")
                    return cmap
                if len(start_byte) != len(end_byte):
                    log.warning(
                        "The start and end byte of begincidrange have different lengths.",
                    )
                    return cmap
                cmap.add_cid_range(start_byte, end_byte, cid)
            del stack[:]
        elif obj is KEYWORD_BEGINCIDCHAR:
            del stack[:]
        elif obj is KEYWORD_ENDCIDCHAR:
            for code, cid in choplist(2, stack):
                if isinstance(code, bytes) and isinstance(cid, int):
                    cmap.add_bytes2cid(code, cid)
            del stack[:]
        elif obj is KEYWORD_BEGINBFRANGE:
            del stack[:]
        elif obj is KEYWORD_ENDBFRANGE:
            del stack[:]
        elif obj is KEYWORD_BEGINBFCHAR:
            del stack[:]
        elif obj is KEYWORD_ENDBFCHAR:
            del stack[:]
        elif obj is KEYWORD_BEGINNOTDEFRANGE:
            del stack[:]
        elif obj is KEYWORD_ENDNOTDEFRANGE:
            del stack[:]
        else:
            # It's ... something else (probably bogus)
            stack.append(obj)
    return cmap
