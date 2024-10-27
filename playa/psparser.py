#!/usr/bin/env python3
import logging
import mmap
import re
from binascii import unhexlify
from collections import deque
from typing import (
    Any,
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
    PSException,
    PSSyntaxError,
    PSTypeError,
)
from playa.utils import choplist

log = logging.getLogger(__name__)


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
KEYWORD_PROC_BEGIN = KWD(b"{")
KEYWORD_PROC_END = KWD(b"}")
KEYWORD_ARRAY_BEGIN = KWD(b"[")
KEYWORD_ARRAY_END = KWD(b"]")
KEYWORD_DICT_BEGIN = KWD(b"<<")
KEYWORD_DICT_END = KWD(b">>")
KEYWORD_GT = KWD(b">")


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


EOL = b"\r\n"
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
LEXER = re.compile(
    rb"""(?:
      (?P<whitespace> \s+)
    | (?P<comment> %[^\r\n]*[\r\n])
    | (?P<name> /(?: \#[A-Fa-f\d][A-Fa-f\d] | [^#/%\[\]()<>{}\s])+ )
    | (?P<number> [-+]? (?: \d*\.\d+ | \d+ ) )
    | (?P<keyword> [A-Za-z] [^#/%\[\]()<>{}\s]*)
    | (?P<startstr> \([^()\\]*)
    | (?P<hexstr> <[A-Fa-f\d\s]*>)
    | (?P<startdict> <<)
    | (?P<enddict> >>)
    | (?P<other> .)
)
""",
    re.VERBOSE,
)
STRLEXER = re.compile(
    rb"""(?:
      (?P<octal> \\[0-7]{1,3})
    | (?P<linebreak> \\(?:\r\n?|\n))
    | (?P<escape> \\.)
    | (?P<parenleft> \()
    | (?P<parenright> \))
    | (?P<newline> \r\n?|\n)
    | (?P<other> .)
)""",
    re.VERBOSE,
)
HEXDIGIT = re.compile(rb"#([A-Fa-f\d][A-Fa-f\d])")
EOLR = re.compile(rb"\r\n?|\n")
SPC = re.compile(rb"\s")


class Lexer:
    """Lexer for PDF data."""

    def __init__(self, data: Union[bytes, mmap.mmap]) -> None:
        self.data = data
        self.pos = 0
        self.end = len(data)
        self._tokens: Deque[Tuple[int, PSBaseParserToken]] = deque()

    def seek(self, pos: int) -> None:
        """Seek to a position and reinitialize parser state."""
        self.pos = pos
        self._curtoken = b""
        self._curtokenpos = 0
        self._tokens.clear()

    def tell(self) -> int:
        """Get the current position in the buffer."""
        return self.pos

    def read(self, objlen: int) -> bytes:
        """Read data from current position, advancing to the end of
        this data."""
        pos = self.pos
        self.pos = min(pos + objlen, len(self.data))
        return self.data[pos : self.pos]

    def nextline(self) -> Tuple[int, bytes]:
        r"""Fetches a next line that ends either with \r, \n, or \r\n."""
        if self.pos == self.end:
            raise StopIteration
        linepos = self.pos
        m = EOLR.search(self.data, self.pos)
        if m is None:
            self.pos = self.end
        else:
            self.pos = m.end()
        return (linepos, self.data[linepos : self.pos])

    def revreadlines(self) -> Iterator[bytes]:
        """Fetches a next line backwards.

        This is used to locate the trailers at the end of a file.
        """
        endline = pos = self.end
        while True:
            nidx = self.data.rfind(b"\n", 0, pos)
            ridx = self.data.rfind(b"\r", 0, pos)
            best = max(nidx, ridx)
            if best == -1:
                yield self.data[:endline]
                break
            yield self.data[best + 1 : endline]
            endline = best + 1
            pos = best
            if pos > 0 and self.data[pos - 1 : pos + 1] == b"\r\n":
                pos -= 1

    def get_inline_data(
        self, target: bytes = b"EI", blocksize: int = -1
    ) -> Tuple[int, bytes]:
        """Get the data for an inline image up to the target
        end-of-stream marker.

        Returns a tuple of the position of the target in the data and the
        data *including* the end of stream marker.  Advances the file
        pointer to a position after the end of the stream.

        The caller is responsible for removing the end-of-stream if
        necessary (this depends on the filter being used) and parsing
        the end-of-stream token (likewise) if necessary.
        """
        tpos = self.data.find(target, self.pos)
        if tpos != -1:
            nextpos = tpos + len(target)
            result = (tpos, self.data[self.pos : nextpos])
            self.pos = nextpos
            return result
        return (-1, b"")

    def __iter__(self) -> Iterator[Tuple[int, PSBaseParserToken]]:
        """Iterate over tokens."""
        return self

    def nexttoken(self) -> Tuple[int, PSBaseParserToken]:
        """Get the next token in iteration, raising StopIteration when done."""
        return self.__next__()

    def __next__(self) -> Tuple[int, PSBaseParserToken]:
        """Get the next token in iteration, raising StopIteration when
        done."""
        while True:
            m = LEXER.match(self.data, self.pos)
            if m is None:  # can only happen at EOS
                raise StopIteration
            self._curtokenpos = m.start()
            self.pos = m.end()
            if m.lastgroup not in ("whitespace", "comment"):  # type: ignore
                # Okay, we got a token or something
                break
        self._curtoken = m[0]
        if m.lastgroup == "name":  # type: ignore
            self._curtoken = m[0][1:]
            self._curtoken = HEXDIGIT.sub(
                lambda x: bytes((int(x[1], 16),)), self._curtoken
            )
            tok = LIT(name_str(self._curtoken))
            return (self._curtokenpos, tok)
        if m.lastgroup == "number":  # type: ignore
            if b"." in self._curtoken:
                return (self._curtokenpos, float(self._curtoken))
            else:
                return (self._curtokenpos, int(self._curtoken))
        if m.lastgroup == "startdict":  # type: ignore
            return (self._curtokenpos, KEYWORD_DICT_BEGIN)
        if m.lastgroup == "enddict":  # type: ignore
            return (self._curtokenpos, KEYWORD_DICT_END)
        if m.lastgroup == "startstr":  # type: ignore
            return self._parse_endstr(self.data[m.start() + 1 : m.end()], m.end())
        if m.lastgroup == "hexstr":  # type: ignore
            self._curtoken = SPC.sub(b"", self._curtoken[1:-1])
            if len(self._curtoken) % 2 == 1:
                self._curtoken += b"0"
            return (self._curtokenpos, unhexlify(self._curtoken))
        # Anything else is treated as a keyword (whether explicitly matched or not)
        if self._curtoken == b"true":
            return (self._curtokenpos, True)
        elif self._curtoken == b"false":
            return (self._curtokenpos, False)
        else:
            return (self._curtokenpos, KWD(self._curtoken))

    def _parse_endstr(self, start: bytes, pos: int) -> Tuple[int, PSBaseParserToken]:
        """Parse the remainder of a string."""
        # Handle nonsense CRLF conversion in strings (PDF 1.7, p.15)
        parts = [EOLR.sub(b"\n", start)]
        paren = 1
        for m in STRLEXER.finditer(self.data, pos):
            self.pos = m.end()
            if m.lastgroup == "parenright":  # type: ignore
                paren -= 1
                if paren == 0:
                    # By far the most common situation!
                    break
                parts.append(m[0])
            elif m.lastgroup == "parenleft":  # type: ignore
                parts.append(m[0])
                paren += 1
            elif m.lastgroup == "escape":  # type: ignore
                chr = m[0][1:2]
                if chr not in ESC_STRING:
                    log.warning("Unrecognized escape %r", m[0])
                    parts.append(chr)
                else:
                    parts.append(bytes((ESC_STRING[chr],)))
            elif m.lastgroup == "octal":  # type: ignore
                chrcode = int(m[0][1:], 8)
                if chrcode >= 256:
                    # PDF1.7 p.16: "high-order overflow shall be
                    # ignored."
                    log.warning("Invalid octal %r (%d)", m[0][1:], chrcode)
                else:
                    parts.append(bytes((chrcode,)))
            elif m.lastgroup == "newline":  # type: ignore
                # Handle nonsense CRLF conversion in strings (PDF 1.7, p.15)
                parts.append(b"\n")
            elif m.lastgroup == "linebreak":  # type: ignore
                pass
            else:
                parts.append(m[0])
        if paren != 0:
            log.warning("Unterminated string at %d", pos)
            raise StopIteration
        return (self._curtokenpos, b"".join(parts))


# Stack slots may by occupied by any of:
#  * the name of a literal
#  * the PSBaseParserToken types
#  * list (via KEYWORD_ARRAY)
#  * dict (via KEYWORD_DICT)
#  * subclass-specific extensions (e.g. PDFStream, PDFObjRef) via ExtraT
ExtraT = TypeVar("ExtraT")
PSStackType = Union[str, float, bool, PSLiteral, bytes, List, Dict, ExtraT]
PSStackEntry = Tuple[int, PSStackType[ExtraT]]


class Parser(Generic[ExtraT]):
    """Basic parser for PDF objects in a bytes-like object."""

    def __init__(self, data: Union[bytes, mmap.mmap]) -> None:
        self.reinit(data)

    def reinit(self, data: Union[bytes, mmap.mmap]) -> None:
        """Reinitialize with new data (FIXME: Should go away, use a
        new parser for each stream as it's clearer and safer)"""
        self._lexer = Lexer(data)
        self.reset()

    def reset(self) -> None:
        """Reset parser state."""
        self.context: List[Tuple[int, Optional[str], List[PSStackEntry[ExtraT]]]] = []
        self.curtype: Optional[str] = None
        self.curstack: List[PSStackEntry[ExtraT]] = []
        self.results: List[PSStackEntry[ExtraT]] = []

    def seek(self, pos: int) -> None:
        """Seek to a position and reset parser state."""
        self._lexer.seek(pos)
        self.reset()

    def tell(self) -> int:
        """Get the current position in the file."""
        return self._lexer.tell()

    def push(self, *objs: PSStackEntry[ExtraT]) -> None:
        """Push some objects onto the stack."""
        self.curstack.extend(objs)

    def pop(self, n: int) -> List[PSStackEntry[ExtraT]]:
        """Pop some objects off the stack."""
        objs = self.curstack[-n:]
        self.curstack[-n:] = []
        return objs

    def popall(self) -> List[PSStackEntry[ExtraT]]:
        """Pop all the things off the stack."""
        objs = self.curstack
        self.curstack = []
        return objs

    def add_results(self, *objs: PSStackEntry[ExtraT]) -> None:
        """Move some objects to the output."""
        try:
            log.debug("add_results: %r", objs)
        except Exception:
            log.debug("add_results: (unprintable object)")
        self.results.extend(objs)

    def start_type(self, pos: int, type: str) -> None:
        """Start a composite object (array, dict, etc)."""
        self.context.append((pos, self.curtype, self.curstack))
        (self.curtype, self.curstack) = (type, [])
        log.debug("start_type: pos=%r, type=%r", pos, type)

    def end_type(self, type: str) -> Tuple[int, List[PSStackType[ExtraT]]]:
        """End a composite object (array, dict, etc)."""
        if self.curtype != type:
            raise PSTypeError(f"Type mismatch: {self.curtype!r} != {type!r}")
        objs = [obj for (_, obj) in self.curstack]
        (pos, self.curtype, self.curstack) = self.context.pop()
        log.debug("end_type: pos=%r, type=%r, objs=%r", pos, type, objs)
        return (pos, objs)

    def do_keyword(self, pos: int, token: PSKeyword) -> None:
        """Handle a PDF keyword."""
        pass

    def flush(self) -> None:
        """Add objects from stack to output (or, actually, not)."""
        return

    def __next__(self) -> PSStackEntry[ExtraT]:
        """Return the next object, returning StopIteration at EOF.

        Arrays and dictionaries are represented as Python lists and
        dictionaries.
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
            else:
                self.flush()
        pos, obj = self.results.pop(0)
        try:
            log.debug("__next__: object at %d: %r", pos, obj)
        except Exception:
            log.debug("__next__: (unprintable object) at %d", pos)
        return pos, obj

    def __iter__(self) -> Iterator[PSStackEntry[ExtraT]]:
        """Iterate over objects, raising StopIteration at EOF."""
        return self

    # Delegation follows
    def nextline(self) -> Tuple[int, bytes]:
        r"""Fetches a next line that ends either with \r, \n, or
        \r\n."""
        return self._lexer.nextline()

    def revreadlines(self) -> Iterator[bytes]:
        """Fetches a next line backwards.

        This is used to locate the trailers at the end of a file.
        """
        return self._lexer.revreadlines()

    def read(self, objlen: int) -> bytes:
        """Read data from a specified position, moving the current
        position to the end of this data."""
        return self._lexer.read(objlen)

    def get_inline_data(self, target: bytes = b"EI") -> Tuple[int, bytes]:
        """Get the data for an inline image up to the target
        end-of-stream marker."""
        return self._lexer.get_inline_data(target)

    def nexttoken(self) -> Tuple[int, PSBaseParserToken]:
        """Get the next token in iteration, raising StopIteration when
        done."""
        return self._lexer.__next__()
