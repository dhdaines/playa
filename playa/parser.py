import logging
import mmap
import re
import weakref
from binascii import unhexlify
from collections import deque
from typing import (
    TYPE_CHECKING,
    Deque,
    Dict,
    Generic,
    Iterator,
    List,
    Optional,
    Tuple,
    TypeVar,
    Union,
)

from playa import settings
from playa.casting import safe_int
from playa.exceptions import PDFSyntaxError
from playa.pdftypes import (
    KWD,
    LIT,
    ContentStream,
    ObjRef,
    PSKeyword,
    PSLiteral,
    dict_value,
    int_value,
    literal_name,
    name_str,
)
from playa.utils import choplist

log = logging.getLogger(__name__)
if TYPE_CHECKING:
    from playa.document import PDFDocument

# Intern a bunch of important keywords
KEYWORD_PROC_BEGIN = KWD(b"{")
KEYWORD_PROC_END = KWD(b"}")
KEYWORD_ARRAY_BEGIN = KWD(b"[")
KEYWORD_ARRAY_END = KWD(b"]")
KEYWORD_DICT_BEGIN = KWD(b"<<")
KEYWORD_DICT_END = KWD(b">>")
KEYWORD_GT = KWD(b">")
KEYWORD_R = KWD(b"R")
KEYWORD_NULL = KWD(b"null")
KEYWORD_ENDOBJ = KWD(b"endobj")
KEYWORD_STREAM = KWD(b"stream")
KEYWORD_XREF = KWD(b"xref")
KEYWORD_STARTXREF = KWD(b"startxref")
KEYWORD_OBJ = KWD(b"obj")
KEYWORD_TRAILER = KWD(b"trailer")


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

    def iter_lines(self) -> Iterator[Tuple[int, bytes]]:
        r"""Iterate over lines that end either with \r, \n, or \r\n,
        starting at the current position."""
        while self.pos < self.end:
            linepos = self.pos
            m = EOLR.search(self.data, self.pos)
            if m is None:
                self.pos = self.end
            else:
                self.pos = m.end()
            yield (linepos, self.data[linepos : self.pos])

    def reverse_iter_lines(self) -> Iterator[bytes]:
        """Iterate backwards over lines starting at the current position.

        This is used to locate the trailers at the end of a file.
        """
        endline = self.pos
        while True:
            nidx = self.data.rfind(b"\n", 0, self.pos)
            ridx = self.data.rfind(b"\r", 0, self.pos)
            best = max(nidx, ridx)
            if best == -1:
                yield self.data[:endline]
                break
            yield self.data[best + 1 : endline]
            endline = best + 1
            self.pos = best
            if self.pos > 0 and self.data[self.pos - 1 : self.pos + 1] == b"\r\n":
                self.pos -= 1

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
PDFStackT = PSStackType[ContentStream]  # FIXME: Not entirely correct here


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
            raise TypeError(f"Type mismatch: {self.curtype!r} != {type!r}")
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
        """Return the next object, raising StopIteration at EOF.

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
                except TypeError:
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
                        raise PDFSyntaxError(error_msg)
                    d = {
                        literal_name(k): v
                        for (k, v) in choplist(2, objs)
                        if v is not None
                    }
                    self.push((pos, d))
                except TypeError:
                    if settings.STRICT:
                        raise
            elif token == KEYWORD_PROC_BEGIN:
                # begin proc
                self.start_type(pos, "p")
            elif token == KEYWORD_PROC_END:
                # end proc
                try:
                    self.push(self.end_type("p"))
                except TypeError:
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
                raise PDFSyntaxError(f"unknown token {token!r}")
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
        """Iterate over (position, object) tuples, raising StopIteration at EOF."""
        return self

    @property
    def tokens(self) -> Iterator[Tuple[int, PSBaseParserToken]]:
        """Iterate over (position, token) tuples, raising StopIteration at EOF."""
        return self._lexer

    # Delegation follows
    def seek(self, pos: int) -> None:
        """Seek to a position and reset parser state."""
        self._lexer.seek(pos)
        self.reset()

    def tell(self) -> int:
        """Get the current position in the file."""
        return self._lexer.tell()

    @property
    def end(self) -> int:
        """End (or size) of file, for use with seek()."""
        return self._lexer.end

    def iter_lines(self) -> Iterator[Tuple[int, bytes]]:
        r"""Iterate over lines that end either with \r, \n, or \r\n."""
        return self._lexer.iter_lines()

    def reverse_iter_lines(self) -> Iterator[bytes]:
        """Iterate over lines starting at the end of the file

        This is used to locate the trailers at the end of a file.
        """
        return self._lexer.reverse_iter_lines()

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
        return next(self._lexer)


class PDFParser(Parser[Union[PSKeyword, ContentStream, ObjRef, None]]):
    """PDFParser fetches PDF objects from a file stream.
    It holds a weak reference to the document in order to
    resolve indirect references.  If the document is deleted
    then this will obviously no longer work.

    Typical usage:
      parser = PDFParser(fp, doc)
      parser.seek(offset)
      for object in parser:
          ...

    """

    def __init__(self, data: Union[bytes, mmap.mmap], doc: "PDFDocument") -> None:
        super().__init__(data)
        self.doc = weakref.ref(doc)
        self.fallback = False

    def do_keyword(self, pos: int, token: PSKeyword) -> None:
        """Handles PDF-related keywords."""
        if token in (KEYWORD_XREF, KEYWORD_STARTXREF):
            self.add_results(*self.pop(1))

        elif token is KEYWORD_ENDOBJ:
            # objid genno "obj" ... and the object itself
            self.add_results(*self.pop(4))

        elif token is KEYWORD_NULL:
            # null object
            self.push((pos, None))

        elif token is KEYWORD_R:
            # reference to indirect object
            if len(self.curstack) >= 2:
                (_, _object_id), _ = self.pop(2)
                object_id = safe_int(_object_id)
                if object_id is not None:
                    obj = ObjRef(self.doc, object_id)
                    self.push((pos, obj))

        elif token is KEYWORD_STREAM:
            # stream dictionary, which precedes "stream"
            ((_, dic),) = self.pop(1)
            dic = dict_value(dic)
            objlen = 0
            if not self.fallback:
                try:
                    objlen = int_value(dic["Length"])
                except KeyError:
                    if settings.STRICT:
                        raise PDFSyntaxError("/Length is undefined: %r" % dic)
            # back up and read the entire line including 'stream' as
            # the data starts after the trailing newline
            self.seek(pos)
            try:
                _, line = next(self.iter_lines())  # 'stream\n'
            except StopIteration:
                if settings.STRICT:
                    raise PDFSyntaxError("Unexpected EOF")
                return
            pos = self.tell()
            data = self.read(objlen)
            # FIXME: This is ... not really the right way to do this.
            for linepos, line in self.iter_lines():
                if b"endstream" in line:
                    i = line.index(b"endstream")
                    objlen += i
                    if self.fallback:
                        data += line[:i]
                    break
                objlen += len(line)
                if self.fallback:
                    data += line
            self.seek(pos + objlen)
            # XXX limit objlen not to exceed object boundary
            log.debug(
                "ContentStream: pos=%d, objlen=%d, dic=%r, data=%r...",
                pos,
                objlen,
                dic,
                data[:10],
            )
            doc = self.doc()
            if doc is None:
                raise RuntimeError("Document no longer exists!")
            stream = ContentStream(dic, bytes(data), doc.decipher)
            self.push((pos, stream))

        else:
            # others
            self.push((pos, token))


class ContentStreamParser(PDFParser):
    """StreamParser is used to parse PDF content streams and object
    streams.  These have slightly different rules for how objects are
    described than the top-level PDF file contents.
    """

    def __init__(self, data: bytes, doc: "PDFDocument") -> None:
        super().__init__(data, doc)

    def flush(self) -> None:
        self.add_results(*self.popall())

    def do_keyword(self, pos: int, token: PSKeyword) -> None:
        if token is KEYWORD_R:
            # reference to indirect object
            try:
                (_, _object_id), _ = self.pop(2)
            except ValueError:
                raise PDFSyntaxError(
                    "Expected generation and object id in indirect object reference"
                )
            object_id = safe_int(_object_id)
            if object_id is not None:
                obj = ObjRef(self.doc, object_id)
                self.push((pos, obj))
            return

        elif token in (KEYWORD_OBJ, KEYWORD_ENDOBJ):
            if settings.STRICT:
                # See PDF Spec 3.4.6: Only the object values are stored in the
                # stream; the obj and endobj keywords are not used.
                raise PDFSyntaxError("Keyword endobj found in stream")
            return

        # others
        self.push((pos, token))
