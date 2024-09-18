#!/usr/bin/env python3
import io
import logging
import re
from binascii import unhexlify
from collections import deque
from typing import (
    Any,
    BinaryIO,
    Deque,
    Dict,
    Generic,
    Iterator,
    List,
    Optional,
    Tuple,
    Type,
    TypeVar,
    Union,
)

from playa import settings
from playa.exceptions import (
    PSEOF,
    PSException,
    PSSyntaxError,
    PSTypeError,
)
from playa.utils import choplist

log = logging.getLogger(__name__)


class PSObject:
    """Base class for all PS or PDF-related data types."""


class PSLiteral(PSObject):
    """A class that represents a PostScript literal.

    Postscript literals are used as identifiers, such as
    variable names, property names and dictionary keys.
    Literals are case sensitive and denoted by a preceding
    slash sign (e.g. "/Name")

    Note: Do not create an instance of PSLiteral directly.
    Always use PSLiteralTable.intern().
    """

    NameType = Union[str, bytes]

    def __init__(self, name: NameType) -> None:
        self.name = name

    def __repr__(self) -> str:
        name = self.name
        return "/%r" % name


class PSKeyword(PSObject):
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
        name = self.name
        return "/%r" % name


_SymbolT = TypeVar("_SymbolT", PSLiteral, PSKeyword)


class PSSymbolTable(Generic[_SymbolT]):
    """A utility class for storing PSLiteral/PSKeyword objects.

    Interned objects can be checked its identity with "is" operator.
    """

    def __init__(self, klass: Type[_SymbolT]) -> None:
        self.dict: Dict[PSLiteral.NameType, _SymbolT] = {}
        self.klass: Type[_SymbolT] = klass

    def intern(self, name: PSLiteral.NameType) -> _SymbolT:
        if name in self.dict:
            lit = self.dict[name]
        else:
            # Type confusion issue: PSKeyword always takes bytes as name
            #                       PSLiteral uses either str or bytes
            lit = self.klass(name)  # type: ignore[arg-type]
            self.dict[name] = lit
        return lit


PSLiteralTable = PSSymbolTable(PSLiteral)
PSKeywordTable = PSSymbolTable(PSKeyword)
LIT = PSLiteralTable.intern
KWD = PSKeywordTable.intern
KEYWORD_PROC_BEGIN = KWD(b"{")
KEYWORD_PROC_END = KWD(b"}")
KEYWORD_ARRAY_BEGIN = KWD(b"[")
KEYWORD_ARRAY_END = KWD(b"]")
KEYWORD_DICT_BEGIN = KWD(b"<<")
KEYWORD_DICT_END = KWD(b">>")
KEYWORD_GT = KWD(b">")


def literal_name(x: Any) -> str:
    if isinstance(x, PSLiteral):
        if isinstance(x.name, str):
            return x.name
        try:
            return str(x.name, "utf-8")
        except UnicodeDecodeError:
            return str(x.name)
    else:
        if settings.STRICT:
            raise PSTypeError(f"Literal required: {x!r}")
        return str(x)


def keyword_name(x: Any) -> Any:
    if not isinstance(x, PSKeyword):
        if settings.STRICT:
            raise PSTypeError("Keyword required: %r" % x)
        else:
            name = x
    else:
        name = str(x.name, "utf-8", "ignore")
    return name


EOL = b"\r\n"
SPC = re.compile(rb"\s")
WHITESPACE = b" \t\n\r\f\v"
NUMBER = b"0123456789"
HEX = NUMBER + b"abcdef" + b"ABCDEF"
NOTLITERAL = b"#/%[]()<>{}" + WHITESPACE
NOTKEYWORD = b"#/%[]()<>{}" + WHITESPACE
NOTSTRING = b"()\\"
OCTAL = b"01234567"
ESC_STRING = {
    b"b": 8,
    b"t": 9,
    b"n": 10,
    b"f": 12,
    b"r": 13,
    b"(": 40,
    b")": 41,
    b"\\": 92,
}


PSBaseParserToken = Union[float, bool, PSLiteral, PSKeyword, bytes]


class PSBaseParser:
    def __init__(self, reader: io.BufferedReader):
        self.reader = reader
        self._tokens: Deque[Tuple[int, str]] = deque()
        self.seek(0)

    def seek(self, pos: int) -> None:
        self.reader.seek(pos)
        self._parse1 = self._parse_main
        self._curtoken = b""
        self._curtokenpos = 0
        self._tokens.clear()

    def tell(self) -> None:
        return self.reader.tell()

    def nextline(self) -> Tuple[int, bytes]:
        r"""Fetches a next line that ends either with \r, \n, or \r\n."""
        linepos = self.reader.tell()
        # readline() is implemented on BufferedReader so just use that
        # (except that it only accepts \n as a separator)
        line_or_lines = self.reader.readline()
        if line_or_lines == b"":
            raise PSEOF
        first, sep, rest = line_or_lines.partition(b"\r")
        if len(rest) == 0:
            return (linepos, line_or_lines)
        elif rest != b"\n":
            self.reader.seek(linepos + len(first) + 1)
            return (linepos, first + sep)
        else:
            self.reader.seek(linepos + len(first) + 2)
            return (linepos, first + b"\r\n")

    def revreadlines(self) -> Iterator[bytes]:
        """Fetches a next line backwards.

        This is used to locate the trailers at the end of a file.
        """
        self.reader.seek(0, io.SEEK_END)
        pos = self.reader.tell()
        buf = b""
        while pos > 0:
            # NOTE: This can obviously be optimized to use regular
            # expressions on the (known to exist) buffer in
            # self.reader...
            pos -= 1
            self.reader.seek(pos)
            c = self.reader.read(1)
            if c in b"\r\n":
                yield buf
                buf = c
                if c == b"\n" and pos > 0:
                    self.reader.seek(pos - 1)
                    cc = self.reader.read(1)
                    if cc == b"\r":
                        pos -= 1
                        buf = cc + buf
            else:
                buf = c + buf
        yield buf

    def __iter__(self):
        return self

    def __next__(self) -> Union[None, Tuple[int, PSBaseParserToken]]:
        while True:
            c = self._parse1()
            # print(c, self._curtoken, self._parse1)
            if self._tokens or c == b"":
                break
        if not self._tokens:
            raise StopIteration
        return self._tokens.popleft()

    def nexttoken(self) -> Tuple[int, PSBaseParserToken]:
        try:
            return self.__next__()
        except StopIteration:
            raise PSEOF

    def _getbuf(self) -> bytes:
        return self.reader.peek()

    def _getchar(self) -> bytes:
        return self.reader.read(1)

    def _parse_main(self):
        """Initial/default state for the lexer."""
        c = self.reader.read(1)
        # note that b"" is in everything, which is fine
        if c in WHITESPACE:
            return c
        self._curtokenpos = self.reader.tell() - 1
        if c == b"%":
            self._curtoken = b"%"
            self._parse1 = self._parse_comment
        elif c == b"/":
            self._curtoken = b""
            self._parse1 = self._parse_literal
        elif c in b"-+" or c in NUMBER:
            self._curtoken = c
            self._parse1 = self._parse_number
        elif c == b".":
            self._curtoken = c
            self._parse1 = self._parse_float
        elif c.isalpha():
            self._curtoken = c
            self._parse1 = self._parse_keyword
        elif c == b"(":
            self._curtoken = b""
            self.paren = 1
            self._parse1 = self._parse_string
        elif c == b"<":
            self._curtoken = b""
            self._parse1 = self._parse_wopen
        elif c == b">":
            self._curtoken = b""
            self._parse1 = self._parse_wclose
        elif c == b"\x00":
            pass
        else:
            self._add_token(KWD(c))
        return c

    def _add_token(self, obj: PSBaseParserToken) -> None:
        """Add a succesfully parsed token."""
        self._tokens.append((self._curtokenpos, obj))

    def _parse_comment(self):
        """Comment state for the lexer"""
        c = self.reader.read(1)
        if c in EOL:  # this includes b"", i.e. EOF
            self._parse1 = self._parse_main
            # We ignore comments.
            # self._tokens.append(self._curtoken)
        else:
            self._curtoken += c
        return c

    def _parse_literal(self):
        """Literal (keyword) state for the lexer."""
        c = self.reader.read(1)
        if c == b"#":
            self.hex = b""
            self._parse1 = self._parse_literal_hex
        elif c in NOTLITERAL:
            if c:
                self.reader.seek(-1, io.SEEK_CUR)
            try:
                self._add_token(LIT(self._curtoken.decode("utf-8")))
            except UnicodeDecodeError:
                self._add_token(LIT(self._curtoken))
            self._parse1 = self._parse_main
        else:
            self._curtoken += c
        return c

    def _parse_literal_hex(self):
        """State for escaped hex characters in literal names"""
        # Consume a hex digit only if we can ... consume a hex digit
        c = self.reader.read(1)
        if c and c in HEX and len(self.hex) < 2:
            self.hex += c
        else:
            if c:
                self.reader.seek(-1, io.SEEK_CUR)
            if self.hex:
                self._curtoken += bytes((int(self.hex, 16),))
            self._parse1 = self._parse_literal
        return c

    def _parse_number(self):
        """State for numeric objects."""
        c = self.reader.read(1)
        if c and c in NUMBER:
            self._curtoken += c
        elif c == b".":
            self._curtoken += c
            self._parse1 = self._parse_float
        else:
            if c:
                self.reader.seek(-1, io.SEEK_CUR)
            try:
                self._add_token(int(self._curtoken))
            except ValueError:
                log.warning("Invalid int literal: %r", self._curtoken)
            self._parse1 = self._parse_main
        return c

    def _parse_float(self):
        """State for fractional part of numeric objects."""
        c = self.reader.read(1)
        # b"" is in everything so we have to add an extra check
        if not c or c not in NUMBER:
            if c:
                self.reader.seek(-1, io.SEEK_CUR)
            try:
                self._add_token(float(self._curtoken))
            except ValueError:
                log.warning("Invalid float literal: %r", self._curtoken)
            self._parse1 = self._parse_main
        else:
            self._curtoken += c
        return c

    def _parse_keyword(self):
        """State for keywords."""
        c = self.reader.read(1)
        if c in NOTKEYWORD:  # includes EOF
            if c:
                self.reader.seek(-1, io.SEEK_CUR)
            if self._curtoken == b"true":
                self._add_token(True)
            elif self._curtoken == b"false":
                self._add_token(False)
            else:
                self._add_token(KWD(self._curtoken))
            self._parse1 = self._parse_main
        else:
            self._curtoken += c
        return c

    def _parse_string(self):
        """State for string objects."""
        c = self.reader.read(1)
        if c and c in NOTSTRING:  # does not include EOF
            if c == b"\\":
                self._parse1 = self._parse_string_esc
                return c
            elif c == b"(":
                self.paren += 1
                self._curtoken += c
                return c
            elif c == b")":
                self.paren -= 1
                if self.paren:
                    self._curtoken += c
                    return c
            # We saw the last parenthesis and fell through (it will be
            # consumed, but not added to self._curtoken)
            self._add_token(self._curtoken)
            self._parse1 = self._parse_main
        elif c == b"\r":
            # PDF 1.7 page 15: An end-of-line marker appearing within
            # a literal string without a preceding REVERSE SOLIDUS
            # shall be treated as a byte value of (0Ah), irrespective
            # of whether the end-of-line marker was a CARRIAGE RETURN
            # (0Dh), a LINE FEED (0Ah), or both.
            cc = self.reader.read(1)
            # Put it back if it isn't \n
            if cc and cc != b"\n":
                self.reader.seek(-1, io.SEEK_CUR)
            self._curtoken += b"\n"
        else:
            self._curtoken += c
        return c

    def _parse_string_esc(self):
        """State for escapes in literal strings.  We have seen a
        backslash and nothing else."""
        c = self.reader.read(1)
        if c and c in OCTAL:  # exclude EOF
            self.oct = c
            self._parse1 = self._parse_string_octal
            return c
        elif c and c in ESC_STRING:
            self._curtoken += bytes((ESC_STRING[c],))
        elif c == b"\n":  # Skip newline after backslash
            pass
        elif c == b"\r":  # Also skip CRLF after
            cc = self.reader.read(1)
            # Put it back if it isn't \n
            if cc and cc != b"\n":
                self.reader.seek(-1, io.SEEK_CUR)
        elif c == b"":
            log.warning("EOF inside escape %r", self._curtoken)
        else:
            log.warning("Unrecognized escape %r", c)
            self._curtoken += c
        self._parse1 = self._parse_string
        return c

    def _parse_string_octal(self):
        """State for an octal escape."""
        c = self.reader.read(1)
        if c and c in OCTAL:  # exclude EOF
            self.oct += c
            done = len(self.oct) >= 3  # it can't be > though
        else:
            if c:
                self.reader.seek(-1, io.SEEK_CUR)
            else:
                log.warning("EOF in octal escape %r", self._curtoken)
            done = True
        if done:
            chrcode = int(self.oct, 8)
            if chrcode >= 256:
                # PDF1.7 p.16: "high-order overflow shall be ignored."
                log.warning("Invalid octal %s (%d)", repr(self.oct), chrcode)
            else:
                self._curtoken += bytes((chrcode,))
            # Back to normal string parsing
            self._parse1 = self._parse_string
        return c

    def _parse_wopen(self):
        """State for start of dictionary or hex string."""
        c = self.reader.read(1)
        if c == b"<":
            self._add_token(KEYWORD_DICT_BEGIN)
            self._parse1 = self._parse_main
        else:
            if c:
                self.reader.seek(-1, io.SEEK_CUR)
            self._parse1 = self._parse_hexstring
        return c

    def _parse_wclose(self):
        """State for end of dictionary (accessed from initial state only)"""
        c = self.reader.read(1)
        if c == b">":
            self._add_token(KEYWORD_DICT_END)
        else:
            # Assuming this is a keyword (which means nothing)
            self._add_token(KEYWORD_GT)
            if c:
                self.reader.seek(-1, io.SEEK_CUR)
        self._parse1 = self._parse_main

    def _parse_hexstring(self):
        """State for parsing hexadecimal literal strings."""
        c = self.reader.read(1)
        if not c:
            log.warning("EOF in hex string %r", self._curtoken)
        elif c in WHITESPACE:
            pass
        elif c in HEX:
            self._curtoken += c
        elif c == b">":
            if len(self._curtoken) % 2 == 1:
                self._curtoken += b"0"
            token = unhexlify(self._curtoken)
            self._add_token(token)
            self._parse1 = self._parse_main
        else:
            log.warning("unexpected character %r in hex string %r", c, self._curtoken)
        return c


# Stack slots may by occupied by any of:
#  * the name of a literal
#  * the PSBaseParserToken types
#  * list (via KEYWORD_ARRAY)
#  * dict (via KEYWORD_DICT)
#  * subclass-specific extensions (e.g. PDFStream, PDFObjRef) via ExtraT
ExtraT = TypeVar("ExtraT")
PSStackType = Union[str, float, bool, PSLiteral, bytes, List, Dict, ExtraT]
PSStackEntry = Tuple[int, PSStackType[ExtraT]]


class PSStackParser(PSBaseParser, Generic[ExtraT]):
    def __init__(self, fp: BinaryIO) -> None:
        PSBaseParser.__init__(self, fp)
        self.reset()

    def reset(self) -> None:
        self.context: List[Tuple[int, Optional[str], List[PSStackEntry[ExtraT]]]] = []
        self.curtype: Optional[str] = None
        self.curstack: List[PSStackEntry[ExtraT]] = []
        self.results: List[PSStackEntry[ExtraT]] = []

    def seek(self, pos: int) -> None:
        PSBaseParser.seek(self, pos)
        self.reset()

    def push(self, *objs: PSStackEntry[ExtraT]) -> None:
        self.curstack.extend(objs)

    def pop(self, n: int) -> List[PSStackEntry[ExtraT]]:
        objs = self.curstack[-n:]
        self.curstack[-n:] = []
        return objs

    def popall(self) -> List[PSStackEntry[ExtraT]]:
        objs = self.curstack
        self.curstack = []
        return objs

    def add_results(self, *objs: PSStackEntry[ExtraT]) -> None:
        try:
            log.debug("add_results: %r", objs)
        except Exception:
            log.debug("add_results: (unprintable object)")
        self.results.extend(objs)

    def start_type(self, pos: int, type: str) -> None:
        self.context.append((pos, self.curtype, self.curstack))
        (self.curtype, self.curstack) = (type, [])
        log.debug("start_type: pos=%r, type=%r", pos, type)

    def end_type(self, type: str) -> Tuple[int, List[PSStackType[ExtraT]]]:
        if self.curtype != type:
            raise PSTypeError(f"Type mismatch: {self.curtype!r} != {type!r}")
        objs = [obj for (_, obj) in self.curstack]
        (pos, self.curtype, self.curstack) = self.context.pop()
        log.debug("end_type: pos=%r, type=%r, objs=%r", pos, type, objs)
        return (pos, objs)

    def do_keyword(self, pos: int, token: PSKeyword) -> None:
        pass

    def nextobject(self) -> PSStackEntry[ExtraT]:
        """Yields a list of objects.

        Arrays and dictionaries are represented as Python lists and
        dictionaries.

        :return: keywords, literals, strings, numbers, arrays and dictionaries.
        """
        while not self.results:
            (pos, token) = self.nexttoken()
            if isinstance(token, (int, float, bool, str, bytes, PSLiteral)):
                # normal token
                self.push((pos, token))
            elif token == KEYWORD_ARRAY_BEGIN:
                # begin array
                self.start_type(pos, "a")
            elif token == KEYWORD_ARRAY_END:
                # end array
                try:
                    self.push(self.end_type("a"))
                except PSTypeError:
                    if settings.STRICT:
                        raise
            elif token == KEYWORD_DICT_BEGIN:
                # begin dictionary
                self.start_type(pos, "d")
            elif token == KEYWORD_DICT_END:
                # end dictionary
                try:
                    (pos, objs) = self.end_type("d")
                    if len(objs) % 2 != 0:
                        error_msg = "Invalid dictionary construct: %r" % objs
                        raise PSSyntaxError(error_msg)
                    d = {
                        literal_name(k): v
                        for (k, v) in choplist(2, objs)
                        if v is not None
                    }
                    self.push((pos, d))
                except PSTypeError:
                    if settings.STRICT:
                        raise
            elif token == KEYWORD_PROC_BEGIN:
                # begin proc
                self.start_type(pos, "p")
            elif token == KEYWORD_PROC_END:
                # end proc
                try:
                    self.push(self.end_type("p"))
                except PSTypeError:
                    if settings.STRICT:
                        raise
            elif isinstance(token, PSKeyword):
                log.debug(
                    "do_keyword: pos=%r, token=%r, stack=%r",
                    pos,
                    token,
                    self.curstack,
                )
                self.do_keyword(pos, token)
            else:
                log.error(
                    "unknown token: pos=%r, token=%r, stack=%r",
                    pos,
                    token,
                    self.curstack,
                )
                self.do_keyword(pos, token)
                raise PSException
            if self.context:
                continue
        obj = self.results.pop(0)
        try:
            log.debug("nextobject: %r", obj)
        except Exception:
            log.debug("nextobject: (unprintable object)")
        return obj