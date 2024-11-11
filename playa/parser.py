import logging
import mmap
import re
import weakref
from binascii import unhexlify
from collections import deque
from typing import (
    TYPE_CHECKING,
    Any,
    Deque,
    Dict,
    Iterator,
    List,
    NamedTuple,
    Optional,
    Tuple,
    Union,
)

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


Token = Union[float, bool, PSLiteral, PSKeyword, bytes]
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
        self._tokens: Deque[Tuple[int, Token]] = deque()

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

    def __iter__(self) -> Iterator[Tuple[int, Token]]:
        """Iterate over tokens."""
        return self

    def __next__(self) -> Tuple[int, Token]:
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

    def _parse_endstr(self, start: bytes, pos: int) -> Tuple[int, Token]:
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


PDFObject = Union[
    str,
    float,
    bool,
    PSLiteral,
    bytes,
    List,
    Dict,
    ContentStream,
    ObjRef,
    PSKeyword,
    None,
]
StackEntry = Tuple[int, PDFObject]


class ObjectParser:
    """ObjectParser is used to parse PDF object streams (and
    content streams, which have the same syntax).  Notably these
    consist of, well, a stream of objects without the surrounding
    `obj` and `endobj` tokens (which cannot occur in an object
    stream).

    They can contain indirect object references (so, must be
    initialized with a `PDFDocument` to resolve these) but for perhaps
    obvious reasons (how would you parse that) these cannot occur at
    the top level of the stream, only inside an array or dictionary.
    """

    def __init__(
        self, data: Union[bytes, mmap.mmap], doc: Union["PDFDocument", None] = None
    ) -> None:
        self._lexer = Lexer(data)
        self.stack: List[StackEntry] = []
        self.doc = None if doc is None else weakref.ref(doc)

    def __iter__(self) -> Iterator[StackEntry]:
        """Iterate over (position, object) tuples, raising StopIteration at EOF."""
        return self

    def __next__(self) -> StackEntry:
        """Get next PDF object from stream (raises StopIteration at EOF)."""
        top: Union[int, None] = None
        obj: Union[Dict[Any, Any], List[PDFObject], PDFObject]
        while True:
            if self.stack and top is None:
                return self.stack.pop()
            (pos, token) = next(self._lexer)
            if token is KEYWORD_ARRAY_BEGIN:
                if top is None:
                    top = pos
                self.stack.append((pos, token))
            elif token is KEYWORD_ARRAY_END:
                try:
                    pos, obj = self.pop_to(KEYWORD_ARRAY_BEGIN)
                except TypeError as e:
                    log.warning(f"When constructing array: {e}")
                if pos == top:
                    top = None
                    return pos, obj
                self.stack.append((pos, obj))
            elif token is KEYWORD_DICT_BEGIN:
                if top is None:
                    top = pos
                self.stack.append((pos, token))
            elif token is KEYWORD_DICT_END:
                try:
                    (pos, objs) = self.pop_to(KEYWORD_DICT_BEGIN)
                    if len(objs) % 2 != 0:
                        error_msg = (
                            "Dictionary contains odd number of ojbects: %r" % objs
                        )
                        raise PDFSyntaxError(error_msg)
                    obj = {
                        literal_name(k): v
                        for (k, v) in choplist(2, objs)
                        if v is not None
                    }
                except TypeError as e:
                    log.warning(f"When constructing dict: {e}")
                if pos == top:
                    top = None
                    return pos, obj
                self.stack.append((pos, obj))
            elif token is KEYWORD_PROC_BEGIN:
                if top is None:
                    top = pos
                self.stack.append((pos, token))
            elif token is KEYWORD_PROC_END:
                try:
                    pos, obj = self.pop_to(KEYWORD_PROC_BEGIN)
                except TypeError as e:
                    log.warning(f"When constructing proc: {e}")
                if pos == top:
                    top = None
                    return pos, obj
                self.stack.append((pos, obj))
            elif token is KEYWORD_NULL:
                self.stack.append((pos, None))
            elif token is KEYWORD_R:
                # reference to indirect object (only allowed inside another object)
                if top is None:
                    log.warning("Ignoring indirect object reference at top level")
                    self.stack.append((pos, token))
                else:
                    try:
                        _pos, _genno = self.stack.pop()
                        _pos, objid = self.stack.pop()
                        objid = int(objid)  # type: ignore
                    except TypeError:
                        raise PDFSyntaxError(
                            "Expected numeric object id in indirect object reference"
                        )
                    except ValueError:
                        raise PDFSyntaxError(
                            "Expected generation and object id in indirect object reference"
                        )
                    obj = ObjRef(self.doc, objid)
                    self.stack.append((pos, obj))
            else:
                # Literally anything else, including any other keyword
                # (will be handled by some downstream iterator)
                self.stack.append((pos, token))

    def pop_to(self, token: PSKeyword) -> Tuple[int, List[PDFObject]]:
        """Pop everything from the stack back to token."""
        context: List[PDFObject] = []
        while self.stack:
            pos, last = self.stack.pop()
            if last is token:
                context.reverse()
                return pos, context
            context.append(last)
        raise PDFSyntaxError(f"Unmatched end token {token!r}")


class IndirectObject(NamedTuple):
    objid: int
    genno: int
    obj: PDFObject


class IndirectObjectParser:
    """IndirectObjectParser fetches indirect objects from a data
    stream.  It holds a weak reference to the document in order to
    resolve indirect references.  If the document is deleted then this
    will obviously no longer work.

    Note that according to PDF 1.7 sec 7.5.3, "The body of a PDF file
    shall consist of a sequence of indirect objects representing the
    contents of a document."  Therefore unlike the base `Parser`,
    `IndirectObjectParser` returns *only* indrect objects and not bare
    keywords, strings, numbers, etc.

    Typical usage:
      parser = IndirectObjectParser(fp, doc)
      parser.seek(offset)
      for object in parser:
          ...

    """

    def __init__(self, data: Union[bytes, mmap.mmap], doc: "PDFDocument") -> None:
        super().__init__(data, doc)

    def do_keyword(
        self, pos: int, token: PSKeyword
    ) -> Union[None, Tuple[int, IndirectObject]]:
        """Handles PDF-related keywords."""
        if token is KEYWORD_ENDOBJ:
            # objid genno "obj" ... and the object itself
            (_, obj) = self.stack.pop()
            (_, genno) = self.stack.pop()
            (pos, objid) = self.stack.pop()
            assert isinstance(objid, int), "Object number {objid!r} is not int"
            assert isinstance(genno, int), "Generation number {objid!r} is not int"
            return pos, IndirectObject(objid, genno, obj)
        elif token is KEYWORD_STREAM:
            # stream dictionary, which precedes "stream"
            (_, dic) = self.stack.pop()
            dic = dict_value(dic)
            stream_length = 0
            if "Length" in dic:
                stream_length = int_value(dic["Length"])
            else:
                log.warning("/Length is undefined in stream: %r" % (dic,))
            # back up and read the entire line including 'stream' as
            # the data starts after the trailing newline
            self.seek(pos)
            try:
                _, line = next(self.iter_lines())  # 'stream\n'
            except StopIteration:
                log.warning("Unexpected EOF when reading stream token")
                return
            pos = self.tell()
            data = self.read(stream_length)
            # 7.3.8.1 There should be an end-of-line marker after the
            # data and before endstream; this marker shall not be
            # included in the stream length.
            # FIXME: This is ... not really the right way to do this.
            endstream = -1
            for linepos, line in self.iter_lines():
                log.debug("line at %d: %r", linepos, line)
                endstream = line.find(b"endstream")
                if endstream != -1:
                    data += line[:endstream]
                    break
                data += line
            if endstream == -1:
                log.warning("Unexpected EOF when reading endstream token")
                return
            # Skip past the "endstream" keyword
            self.seek(linepos + endstream + len(b"endstream"))
            # XXX limit objlen not to exceed object boundary
            log.debug(
                "ContentStream: pos=%d, stream_length=%d, len(data)=%d, dic=%r, data=%r...",
                pos,
                stream_length,
                len(data),
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
