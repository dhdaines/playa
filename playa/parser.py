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
    Tuple,
    Union,
)

from playa.exceptions import PDFSyntaxError
from playa.pdftypes import (
    KWD,
    LIT,
    LITERALS_ASCII85_DECODE,
    ContentStream,
    ObjRef,
    PSKeyword,
    PSLiteral,
    int_value,
    literal_name,
    name_str,
)
from playa.utils import choplist

log = logging.getLogger(__name__)
if TYPE_CHECKING:
    from playa.document import Document

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
KEYWORD_ENDSTREAM = KWD(b"endstream")
KEYWORD_XREF = KWD(b"xref")
KEYWORD_STARTXREF = KWD(b"startxref")
KEYWORD_OBJ = KWD(b"obj")
KEYWORD_TRAILER = KWD(b"trailer")
KEYWORD_BI = KWD(b"BI")
KEYWORD_ID = KWD(b"ID")
KEYWORD_EI = KWD(b"EI")


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


def reverse_iter_lines(buffer: Union[bytes, mmap.mmap]) -> Iterator[bytes]:
    """Iterate backwards over lines starting at the current position.

    This is used to locate the trailers at the end of a file.
    """
    pos = endline = len(buffer)
    while True:
        nidx = buffer.rfind(b"\n", 0, pos)
        ridx = buffer.rfind(b"\r", 0, pos)
        best = max(nidx, ridx)
        if best == -1:
            yield buffer[:endline]
            break
        yield buffer[best + 1 : endline]
        endline = best + 1
        pos = best
        if pos > 0 and buffer[pos - 1 : pos + 1] == b"\r\n":
            pos -= 1


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

    def __init__(self, data: Union[bytes, mmap.mmap], pos: int = 0) -> None:
        self.data = data
        self.pos = pos
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

    def nextline(self) -> Tuple[int, bytes]:
        r"""Get the next line ending either with \r, \n, or \r\n,
        starting at the current position."""
        linepos = self.pos
        m = EOLR.search(self.data, self.pos)
        if m is None:
            self.pos = self.end
        else:
            self.pos = m.end()
        return (linepos, self.data[linepos : self.pos])

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


class InlineImage(ContentStream):
    """Specific class for inline images so the interpreter can
    recognize them (they are otherwise the same thing as content
    streams)."""


PDFObject = Union[
    str,
    float,
    bool,
    PSLiteral,
    bytes,
    List,
    Dict,
    ObjRef,
    PSKeyword,
    InlineImage,
    ContentStream,
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
    initialized with a `Document` to resolve these) but for perhaps
    obvious reasons (how would you parse that) these cannot occur at
    the top level of the stream, only inside an array or dictionary.
    """

    def __init__(
        self,
        data: Union[bytes, mmap.mmap],
        doc: Union["Document", None] = None,
        pos: int = 0,
    ) -> None:
        self._lexer = Lexer(data, pos)
        self.stack: List[StackEntry] = []
        self.doc = None if doc is None else weakref.ref(doc)

    def newstream(self, data: Union[bytes, mmap.mmap]) -> None:
        """Continue parsing from a new data stream."""
        self._lexer = Lexer(data)

    def reset(self) -> None:
        """Clear internal parser state."""
        del self.stack[:]

    def __iter__(self) -> Iterator[StackEntry]:
        """Iterate over (position, object) tuples."""
        return self

    def __next__(self) -> StackEntry:
        """Get next PDF object from stream (raises StopIteration at EOF)."""
        top: Union[int, None] = None
        obj: Union[Dict[Any, Any], List[PDFObject], PDFObject]
        while True:
            if self.stack and top is None:
                return self.stack.pop()
            (pos, token) = self.nexttoken()
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
                            "Dictionary contains odd number of objects: %r" % objs
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
                    except ValueError:
                        raise PDFSyntaxError(
                            "Expected generation and object id in indirect object reference"
                        )
                    objid = int_value(objid)
                    obj = ObjRef(self.doc, objid)
                    self.stack.append((pos, obj))
            elif token is KEYWORD_BI:
                if top is None:
                    top = pos
                self.stack.append((pos, token))
            elif token is KEYWORD_ID:
                idpos = pos
                (pos, objs) = self.pop_to(KEYWORD_BI)
                if len(objs) % 2 != 0:
                    error_msg = f"Invalid dictionary construct: {objs!r}"
                    raise TypeError(error_msg)
                dic = {
                    literal_name(k): v for (k, v) in choplist(2, objs) if v is not None
                }
                eos = b"EI"
                filter = dic.get("F")
                if filter is not None:
                    if not isinstance(filter, list):
                        filter = [filter]
                    if filter[0] in LITERALS_ASCII85_DECODE:
                        eos = b"~>"
                # PDF 1.7 p. 215: Unless the image uses ASCIIHexDecode
                # or ASCII85Decode as one of its filters, the ID
                # operator shall be followed by a single white-space
                # character, and the next character shall be
                # interpreted as the first byte of image data.
                if eos == b"EI":
                    self.seek(idpos + len(KEYWORD_ID.name) + 1)
                    (eipos, data) = self.get_inline_data(target=eos)
                    # FIXME: it is totally unspecified what to do with
                    # a newline between the end of the data and "EI",
                    # since there is no explicit stream length.  (PDF
                    # 1.7 p. 756: There should be an end-of-line
                    # marker after the data and before endstream; this
                    # marker shall not be included in the stream
                    # length.)  We will include it, which might be wrong.
                    data = data[: -len(eos)]
                else:
                    # Note absence of + 1 here (the "Unless" above)
                    self.seek(idpos + len(KEYWORD_ID.name))
                    (_, data) = self.get_inline_data(target=eos)
                    # There should be an "EI" here
                    (eipos, token) = self.nexttoken()
                    if token is not KEYWORD_EI:
                        log.warning(
                            "Inline image not terminated with EI: got %r", token
                        )
                if eipos == -1:
                    raise PDFSyntaxError("End of inline stream %r not found" % eos)
                obj = InlineImage(dic, data)
                log.debug("InlineImage @ %d: %r", pos, obj)
                # Inline images must occur at the top level, otherwise
                # something is wrong (probably a corrupt file)
                assert pos == top, f"Inline image {obj} not at top level of stream"
                top = None
                return pos, obj
            else:
                # Literally anything else, including any other keyword
                # (will be returned above if top is None, or later if
                # we are inside some object)
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

    # Delegation follows
    def seek(self, pos: int) -> None:
        """Seek to a position."""
        self._lexer.seek(pos)

    def tell(self) -> int:
        """Get the current position in the file."""
        return self._lexer.tell()

    def read(self, objlen: int) -> bytes:
        """Read data from a specified position, moving the current
        position to the end of this data."""
        return self._lexer.read(objlen)

    def get_inline_data(self, target: bytes = b"EI") -> Tuple[int, bytes]:
        """Get the data for an inline image up to the target
        end-of-stream marker."""
        return self._lexer.get_inline_data(target)

    def nextline(self) -> Tuple[int, bytes]:
        """Read (and do not parse) next line from underlying data."""
        return self._lexer.nextline()

    def nexttoken(self) -> Tuple[int, Token]:
        """Get the next token in iteration, raising StopIteration when
        done."""
        return next(self._lexer)


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
    contents of a document."  Therefore unlike the base `ObjectParser`,
    `IndirectObjectParser` returns *only* indrect objects and not bare
    keywords, strings, numbers, etc.

    However, unlike `ObjectParser`, it will also read and return
    `ContentStream`s, as these *must* be indirect objects by definition.

    Typical usage:
      parser = IndirectObjectParser(fp, doc)
      for object in parser:
          ...

    """

    def __init__(
        self,
        data: Union[bytes, mmap.mmap],
        doc: Union["Document", None] = None,
        strict: bool = False,
    ) -> None:
        self._parser = ObjectParser(data, doc)
        self.trailer: List[Tuple[int, Union[PDFObject, ContentStream]]] = []
        self.doc = None if doc is None else weakref.ref(doc)
        self.strict = strict

    def __iter__(self) -> Iterator[Tuple[int, IndirectObject]]:
        return self

    def __next__(self) -> Tuple[int, IndirectObject]:
        obj: Union[PDFObject, ContentStream]
        while True:
            pos, obj = next(self._parser)
            log.debug("pos %r obj %r stack %r", pos, obj, self.trailer)
            if obj is KEYWORD_OBJ:
                pass
            elif obj is KEYWORD_ENDOBJ:
                # objid genno "obj" (skipped) ... and the object
                (_, obj) = self.trailer.pop()
                (_, genno) = self.trailer.pop()
                (pos, objid) = self.trailer.pop()
                objid = int_value(objid)
                genno = int_value(genno)
                # ContentStream is *special* and needs these
                # internally for decryption.
                if isinstance(obj, ContentStream):
                    obj.objid = objid
                    obj.genno = genno
                return pos, IndirectObject(objid, genno, obj)
            elif obj is KEYWORD_STREAM:
                # PDF 1.7 sec 7.3.8.1: A stream shall consist of a
                # dictionary followed by zero or more bytes bracketed
                # between the keywords `stream` (followed by newline)
                # and `endstream`
                (_, dic) = self.trailer.pop()
                if not isinstance(dic, dict):
                    # sec 7.3.8.1: the stream dictionary shall be a
                    # direct object.
                    raise PDFSyntaxError("Incorrect type for stream dictionary %r", dic)
                try:
                    # sec 7.3.8.2: Every stream dictionary shall have
                    # a Length entry that indicates how many bytes of
                    # the PDF file are used for the stream’s data
                    objlen = int_value(dic["Length"])
                except KeyError:
                    log.warning("/Length is undefined in stream dictionary %r", dic)
                    objlen = 0
                except ValueError:
                    log.warning("/Length reference cannot be resolved %r", dic)
                    objlen = 0
                # sec 7.3.8.1: The keyword `stream` that follows the stream
                # dictionary shall be followed by an end-of-line
                # marker consisting of either a CARRIAGE RETURN and a
                # LINE FEED or just a LINE FEED, and not by a CARRIAGE
                # RETURN alone.
                self._parser.seek(pos)
                _, line = self._parser.nextline()
                assert line.strip() == b"stream"
                pos = self._parser.tell()
                # Because PDFs do not follow the spec, we will read
                # *at least* the specified number of bytes, which
                # could be zero (particularly if not specified!), up
                # until the "endstream" tag.  In most cases it is
                # expected that this extra data will be included in
                # the stream anyway, but for encrypted streams you
                # probably don't want that (LOL @ PDF "security")
                data = self._parser.read(objlen)
                # sec 7.3.8.1: There should be an end-of-line
                # marker after the data and before endstream; this
                # marker shall not be included in the stream length.
                linepos, line = self._parser.nextline()
                log.debug("After stream data: %r %r", linepos, line)
                if self.strict:
                     # In reality there usually is no end-of-line
                     # marker.  We will nonetheless warn if there's
                     # something other than 'endstream'.
                    if line not in (b"\n", b"\r\n", b"endstream\n", b"endstream\r\n"):
                        log.warning("Expected newline or 'endstream', got %r", line)
                else:
                    # Reuse that line and read more if necessary
                    while True:
                        if b"endstream" in line:
                            idx = line.index(b"endstream")
                            objlen += idx
                            data += line[:idx]
                            self._parser.seek(pos + objlen)
                            break
                        objlen += len(line)
                        data += line
                        linepos, line = self._parser.nextline()
                        log.debug("After stream data: %r %r", linepos, line)
                        if line == b"":  # Means EOF
                            log.warning("Incorrect legnth for stream, no 'endstream' found")
                            break
                doc = None if self.doc is None else self.doc()
                stream = ContentStream(
                    dic, bytes(data), None if doc is None else doc.decipher
                )
                self.trailer.append((pos, stream))
            elif obj is KEYWORD_ENDSTREAM:
                if not isinstance(self.trailer[-1][1], ContentStream):
                    log.warning("Got endstream without a stream, ignoring!")
            else:
                self.trailer.append((pos, obj))

    # Delegation follows
    def seek(self, pos: int) -> None:
        """Seek to a position."""
        self._parser.seek(pos)

    def reset(self) -> None:
        """Clear internal parser state."""
        self._parser.reset()
