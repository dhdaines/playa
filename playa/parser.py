"""PDF lexer and parser

Danger: API subject to change.
    These APIs are unstable and subject to revision before PLAYA 1.0.
"""

import itertools
import logging
import mmap
import re
from binascii import unhexlify
from collections import deque
from typing import (
    TYPE_CHECKING,
    Any,
    Deque,
    Dict,
    Iterable,
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
    LITERALS_ASCIIHEX_DECODE,
    ContentStream,
    InlineImage,
    ObjRef,
    PDFObject,
    PSKeyword,
    PSLiteral,
    decipher_all,
    int_value,
    literal_name,
    name_str,
    stream_value,
)
from playa.utils import choplist
from playa.worker import _deref_document, _ref_document

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


Token = Union[float, bool, PSLiteral, PSKeyword, bytes]
LEXER = re.compile(
    rb"""(?:
      (?P<whitespace> \s+)
    | (?P<comment> %[^\r\n]*[\r\n])
    | (?P<name> /(?: \#[A-Fa-f\d][A-Fa-f\d] | [^#/%\[\]()<>{}\s])* )
    | (?P<number> [-+]? (?: \d+\.\d* | \.?\d+ ) )
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
WSR = re.compile(rb"\s+")


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
                    # PDF 1.7 sec 7.3.4.2: If the character following
                    # the REVERSE SOLIDUS is not one of those shown in
                    # Table 3, the REVERSE SOLIDUS shall be ignored.
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


StackEntry = Tuple[int, PDFObject]
EIR = re.compile(rb"\sEI\b")
EIEIR = re.compile(rb"EI")
A85R = re.compile(rb"\s*~\s*>\s*EI\b")
FURTHESTEIR = re.compile(rb".*EI")


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
        strict: bool = False,
        streamid: Union[int, None] = None,
    ) -> None:
        self._lexer = Lexer(data, pos)
        self.stack: List[StackEntry] = []
        self.docref = None if doc is None else _ref_document(doc)
        self.strict = strict
        self.streamid = streamid

    @property
    def doc(self) -> Union["Document", None]:
        """Get associated document if it exists."""
        if self.docref is None:
            return None
        return _deref_document(self.docref)

    def newstream(
        self, data: Union[bytes, mmap.mmap], streamid: Union[int, None] = None
    ) -> None:
        """Continue parsing from a new data stream."""
        self._lexer = Lexer(data)
        self.streamid = streamid

    def reset(self) -> None:
        """Clear internal parser state."""
        del self.stack[:]

    def __iter__(self) -> Iterator[StackEntry]:
        """Iterate over (position, object) tuples."""
        return self

    def __next__(self) -> StackEntry:
        """Get next PDF object from stream (raises StopIteration at EOF)."""
        top: Union[int, None] = None
        obj: Union[Dict[Any, Any], List[PDFObject], PDFObject] = None
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
                except (TypeError, PDFSyntaxError) as e:
                    if self.strict:
                        raise e
                    log.warning("When constructing array from %r: %s", obj, e)
                if pos == top:
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
                except (TypeError, PDFSyntaxError) as e:
                    if self.strict:
                        raise e
                    log.warning("When constructing dict from %r: %s", self.stack, e)
                if pos == top:
                    return pos, obj
                self.stack.append((pos, obj))
            elif token is KEYWORD_PROC_BEGIN:
                if top is None:
                    top = pos
                self.stack.append((pos, token))
            elif token is KEYWORD_PROC_END:
                try:
                    pos, obj = self.pop_to(KEYWORD_PROC_BEGIN)
                except (TypeError, PDFSyntaxError) as e:
                    if self.strict:
                        raise e
                    log.warning("When constructing proc from %r: %s", obj, e)
                if pos == top:
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
                    obj = self.get_object_reference(pos, token)
                    self.stack.append((pos, obj))
            elif token is KEYWORD_BI:
                # Inline images must occur at the top level, otherwise
                # something is wrong (probably a corrupt file)
                if top is not None:
                    raise PDFSyntaxError(
                        "Inline image not at top level of stream "
                        f"({pos} != {top}, {self.stack})"
                    )
                if (
                    self.doc is not None
                    and self.streamid is not None
                    and (inline_image_id := (self.streamid, pos))
                    in self.doc._cached_inline_images
                ):
                    end, obj = self.doc._cached_inline_images[inline_image_id]
                    self.seek(end)
                    if obj is not None:
                        return pos, obj
                else:
                    top = pos
                    self.stack.append((pos, token))
            elif token is KEYWORD_ID:
                obj = self.get_inline_image(pos, token)
                assert top is not None
                if self.doc is not None and self.streamid is not None:
                    inline_image_id = (self.streamid, top)
                    self.doc._cached_inline_images[inline_image_id] = self.tell(), obj
                if obj is not None:
                    return top, obj
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

    def get_object_reference(self, pos: int, token: Token) -> Union[ObjRef, None]:
        """Get an indirect object reference upon finding an "R" token."""
        _pos, genno = self.stack.pop()
        _pos, objid = self.stack.pop()
        if not isinstance(objid, int):
            if self.strict:
                raise PDFSyntaxError(
                    f"Expected object number and generation id, got {objid!r} {genno!r}"
                )
            log.warning(
                "Expected object number and generation id, got %r %r", objid, genno
            )
            return None
        if objid == 0:
            if self.strict:
                raise PDFSyntaxError(
                    "Object ID in reference at pos %d cannot be 0" % (pos,)
                )
            log.warning("Ignoring indirect object reference to 0 at %s", pos)
            return None
        return ObjRef(self.docref, objid)

    def get_inline_image(self, pos: int, token: Token) -> Union[InlineImage, None]:
        """Get an inline image upon finding an "ID" token.

        Returns a tuple of the position of the target in the data and
        the image data.  Advances the file pointer to a position after
        the "EI" token that (we hope) ends the image.

        Note: WELCOME IN THE HELL!!!
            If you're lucky enough to have PDF 2.0 documents, then you
            can skip this, you aren't actually in (the) hell.  Otherwise
            read on to know why you might be missng images or reading
            a lot of garbage in your logs:

            - The PDF 1.7 standard only specifies that image data must be
              delimited by `ID` and `EI`, and that "The bytes between
              the `ID` and `EI` operators shall be treated the same as a
              stream object’s data, even though they do not follow the
              standard stream syntax."  What does that even mean?
            - And, that must be "a single whitespace character"
              following `ID` (floating in perfume, served in a man's
              hat), except in the case of `ASCIIHexDecode` or
              `ASCII85Decode` (in which case there can just be any
              whitespace you like, or none at all).
            - It's obviously impossible to determine what a "conforming
              implementation" of this should do.

            In the easiest case, if it's `ASCIIHexDecode` data then we
            can just look for the first instance of `b"EI"`, ignoring all
            whitespace, since `b"EI"` is thankfully not a valid hex
            sequence.

            Otherwise, the stream data can, and inevitably will,
            contain the literal bytes `b"EI"`, so no, we can't just
            search for that.  In the case of `ASCII85Decode`, however,
            you can look for the `b"~>"` end-of-data sequence but note
            that sometimes it... contains whitespace!

            So, we try for `b"\\sEI\\b"`, which is not foolproof since
            you could have the pixel values `(32, 69, 73)` in your
            image followed by some other byte... so in that case,
            expect a bunch of nonsense in the logs and possible data
            loss.  Also in the rare case where `b"EI"` was preceded by
            `b"\\r\\n"`, there will be an extra `\\r` in the image
            data.  Too bad.

            And finally if that doesn't work then we will try to salvage
            something by just looking for "EI", somewhere, anywhere.  We
            take the most distant one, and if this causes you to lose
            data, well, it's definitely Adobe's fault.

            There **is** an absolutely foolproof way to parse inline
            images, but it's ridiculous so we won't do it:

            1. Find the very first instance of `b"EI"`.
            2. Extract the image itself (which could be in various formats).
            3. If it's a valid image, congratulations!  Otherwise try again.

            The moral of the story is that the author of this part of
            the PDF specification should have considered a career in
            literally anything else.

        """
        assert isinstance(token, PSKeyword) and token is KEYWORD_ID, (
            f"Not ID: {token!r}"
        )
        idpos = pos
        (pos, objs) = self.pop_to(KEYWORD_BI)
        if len(objs) % 2 != 0:
            error_msg = f"Dictionary contains odd number of objects: {objs!r}"
            if self.strict:
                raise PDFSyntaxError(error_msg)
            else:
                log.warning(error_msg)
        dic = {literal_name(k): v for (k, v) in choplist(2, objs) if v is not None}

        target_re = EIR
        whitespace_re = SPC
        # Final filter is actually the *first* in the list
        final_filter = dic.get("F", dic.get("Filter"))
        if isinstance(final_filter, list) and final_filter:
            final_filter = final_filter[0]
        if final_filter in LITERALS_ASCII85_DECODE:
            # ASCII85: look for ~>EI, ignoring all whitespace
            whitespace_re = WSR
            target_re = A85R
        elif final_filter in LITERALS_ASCIIHEX_DECODE:
            # ASCIIHex: just look for EI
            whitespace_re = WSR
            target_re = EIEIR

        # Find the start of the image data by skipping the appropriate
        # amount of whitespace.  In the case of ASCII filters, we need
        # to skip any extra whitespace before we use a possible Length
        # value (this is very dumb but the standard says...)
        pos = idpos + len(token.name)
        data = self._lexer.data
        m = whitespace_re.match(data, pos)
        if m is None:  # Note that WSR will also match nothing
            errmsg = f"ID token at {pos} not followed by whitespace"
            if self.strict:
                raise PDFSyntaxError(errmsg)
            else:
                log.warning(errmsg)
        else:
            pos = m.end(0)

        # If you have Length, you have everything
        length = dic.get("L", dic.get("Length"))
        if length is not None:
            end = pos + int_value(length)
            self.seek(end)
            (_, token) = self.nexttoken()
            if token is not KEYWORD_EI:
                errmsg = f"EI not found after Length {length!r}"
                if self.strict:
                    raise PDFSyntaxError(errmsg)
                else:
                    log.warning(errmsg)
            return InlineImage(dic, data[pos:end])

        m = target_re.search(data, pos)
        if m is not None:
            self.seek(m.end(0))
            return InlineImage(dic, data[pos : m.start(0)])
        errmsg = f"Inline image at {pos} not terminated with {target_re}"
        if self.strict:
            raise PDFSyntaxError(errmsg)
        else:
            log.warning(errmsg)

        m = FURTHESTEIR.match(data, pos)
        if m is not None:
            log.warning(
                "Inline image at %d has no whitespace before EI, "
                "expect horrible data loss!!!",
                pos,
            )
            self.seek(m.end(0))
            return InlineImage(dic, data[pos : m.end(0) - 2])
        return None

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


ENDSTREAMR = re.compile(rb"(?:\r\n|\r|\n|)endstream")


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
        pos: int = 0,
        strict: bool = False,
    ) -> None:
        self._parser = ObjectParser(data, doc, pos=pos, strict=strict)
        self.buffer = data
        self.objstack: List[Tuple[int, Union[PDFObject, ContentStream]]] = []
        self.docref = None if doc is None else _ref_document(doc)
        self.strict = strict
        self.decipher = None if doc is None else doc.decipher

    @property
    def doc(self) -> Union["Document", None]:
        """Get associated document if it exists."""
        if self.docref is None:
            return None
        return _deref_document(self.docref)

    def __iter__(self) -> Iterator[Tuple[int, IndirectObject]]:
        return self

    def __next__(self) -> Tuple[int, IndirectObject]:
        obj: Union[PDFObject, ContentStream]
        while True:
            try:
                pos, obj = next(self._parser)
                if obj is KEYWORD_ENDOBJ:
                    return self._endobj(pos, obj)
                elif obj is KEYWORD_STREAM:
                    stream = self._stream(pos, obj)
                    self.objstack.append((pos, stream))
                elif obj is KEYWORD_ENDSTREAM:
                    if not isinstance(self.objstack[-1][1], ContentStream):
                        raise PDFSyntaxError("Got endstream without a stream")
                elif isinstance(obj, PSKeyword) and obj.name.startswith(b"endstream"):
                    # Some broken PDFs have junk after "endstream"
                    errmsg = "Expected 'endstream', got %r" % (obj,)
                    raise PDFSyntaxError(errmsg)
                elif isinstance(obj, PSKeyword) and obj.name.startswith(b"endobj"):
                    # Some broken PDFs have junk after "endobj"
                    errmsg = "Expected 'endobj', got %r" % (obj,)
                    if self.strict:
                        raise PDFSyntaxError(errmsg)
                    log.warning(errmsg)
                    return self._endobj(pos, obj)
                else:
                    self.objstack.append((pos, obj))
            except StopIteration:
                raise
            except Exception as e:
                errmsg = "Syntax error near position %d: %s" % (pos, e)
                if self.strict:
                    raise PDFSyntaxError(errmsg) from e
                else:
                    log.warning(errmsg)
                    continue

    def _endobj(self, pos: int, obj: PDFObject) -> Tuple[int, IndirectObject]:
        # Some broken PDFs omit the space after `endobj`...
        if obj is not KEYWORD_ENDOBJ:
            self._parser.seek(pos + len(b"endobj"))
        # objid genno "obj" (skipped) ... and the object
        (_, obj) = self.objstack.pop()
        (kpos, kwd) = self.objstack.pop()
        if kwd is not KEYWORD_OBJ:
            errmsg = "Expected 'obj' at %d, got %r" % (kpos, kwd)
            raise PDFSyntaxError(errmsg)
        (_, genno) = self.objstack.pop()
        # Update pos to be the beginning of the indirect object
        (pos, objid) = self.objstack.pop()
        try:
            objid = int_value(objid)
            genno = int_value(genno)
        except TypeError as e:
            objs = " ".join(
                repr(obj)
                for obj in itertools.chain(
                    (x[1] for x in self.objstack), (objid, genno, obj)
                )
            )
            errmsg = (
                f"Failed to parse indirect object at {pos}: got: {objs} before 'endobj'"
            )
            raise PDFSyntaxError(errmsg) from e
        # ContentStream is *special* and needs these
        # internally for decryption.
        if isinstance(obj, ContentStream):
            obj.objid = objid
            obj.genno = genno
        # Decrypt indirect objects at top level (inside object streams
        # they are handled by ObjectStreamParser)
        if self.decipher:
            return pos, IndirectObject(
                objid,
                genno,
                decipher_all(self.decipher, objid, genno, obj),
            )
        else:
            return pos, IndirectObject(objid, genno, obj)

    def _stream(self, pos: int, obj: PDFObject) -> ContentStream:
        # PDF 1.7 sec 7.3.8.1: A stream shall consist of a
        # dictionary followed by zero or more bytes bracketed
        # between the keywords `stream` (followed by newline)
        # and `endstream`
        (_, dic) = self.objstack.pop()
        if not isinstance(dic, dict):
            # sec 7.3.8.1: the stream dictionary shall be a
            # direct object.
            raise PDFSyntaxError("Incorrect type for stream dictionary %r", dic)
        try:
            # sec 7.3.8.2: Every stream dictionary shall have
            # a Length entry that indicates how many bytes of
            # the PDF file are used for the stream’s data
            # FIXME: This call is **not** thread-safe as we currently
            # reuse the same IndirectObjectParser to resolve references
            objlen = int_value(dic["Length"])
        except KeyError:
            log.warning("/Length is undefined in stream dictionary %r", dic)
            objlen = 0
        except ValueError:
            # FIXME: This warning should be suppressed in fallback
            # xref parsing, since we obviously can't resolve any
            # references yet.  Either that or fallback xref parsing
            # should just run a regex over the PDF and not try to
            # actually parse the objects (probably a better solution)
            log.warning("/Length reference cannot be resolved in %r", dic)
            objlen = 0
        except TypeError:
            # FIXME: This may happen with incremental updates
            log.warning("/Length reference resolves to non-integer in %r", dic)
            objlen = 0
        # sec 7.3.8.1: The keyword `stream` that follows the stream
        # dictionary shall be followed by an end-of-line
        # marker consisting of either a CARRIAGE RETURN and a
        # LINE FEED or just a LINE FEED, and not by a CARRIAGE
        # RETURN alone.
        self._parser.seek(pos)
        _, line = self._parser.nextline()
        assert line.strip() == b"stream"
        # Because PDFs do not follow the spec, we will read
        # *at least* the specified number of bytes, which
        # could be zero (particularly if not specified!), up
        # until the "endstream" tag.  In most cases it is
        # expected that this extra data will be included in
        # the stream anyway, but for encrypted streams you
        # probably don't want that (LOL @ PDF "security")
        data = self._parser.read(objlen)
        doc = self.doc
        decipher = None if doc is None else doc.decipher
        # sec 7.3.8.1: There should be an end-of-line marker after the
        # data and before endstream; this marker shall not be included
        # in the stream length.
        #
        # TRANSLATION: We expect either one of PDF's many end-of-line
        # markers, endstream, or EOL + endstream.  If we get something
        # else, it's an error in strict mode, otherwise, we throw it
        # on the pile and keep going.
        pos = self._parser.tell()
        m = ENDSTREAMR.match(self._parser._lexer.data, pos)
        if m is not None:
            return ContentStream(dic, bytes(data), decipher)
        # We already know it's an error in strict mode, but read the
        # line anyway to show the user what's wrong
        pos, line = self._parser.nextline()
        if self.strict:
            raise PDFSyntaxError("Expected newline or 'endstream', got %r" % (line,))
        # Now glom on all the data until we see endstream
        while True:
            if b"endstream" in line:
                idx = line.index(b"endstream")
                data += line[:idx]
                self._parser.seek(pos + idx)
                break
            if b"endobj" in line:
                # Oh no! We've really gone too far now!  Stop before it gets worse
                self._parser.seek(pos)
                break
            data += line
            pos, line = self._parser.nextline()
            if line == b"":  # Means EOF
                log.warning("Incorrect length for stream, no 'endstream' found")
                break
        return ContentStream(dic, bytes(data), decipher)

    # Delegation follows
    def seek(self, pos: int) -> None:
        """Seek to a position."""
        self._parser.seek(pos)

    def tell(self) -> int:
        """Get the current position in the file."""
        return self._parser.tell()

    def reset(self) -> None:
        """Clear internal parser state."""
        self._parser.reset()


class ObjectStreamParser:
    """
    Parse indirect objects from an object stream.
    """

    def __init__(
        self,
        stream: ContentStream,
        doc: Union["Document", None] = None,
    ) -> None:
        self._parser = ObjectParser(stream.buffer, doc)
        self.buffer = stream.buffer
        self.nobj = int_value(stream["N"])
        self.first = int_value(stream["First"])
        self.offsets = []
        while True:
            try:
                _, objid = next(self._parser)
                _, pos = next(self._parser)
                objid = int_value(objid)
                pos = int_value(pos)
            except StopIteration:
                log.warning("Unexpected EOF in object stream")
                break
            self.offsets.append((objid, pos))
            if len(self.offsets) == self.nobj:
                break

    def __iter__(self) -> Iterator[Tuple[int, IndirectObject]]:
        self._parser.seek(self.first)
        for (objid, opos), (pos, obj) in zip(self.offsets, self._parser):
            if pos != self.first + opos:
                log.warning(
                    "Invalid object stream: object %d is at %d, should be at %d",
                    objid,
                    pos,
                    self.first + opos,
                )
            yield pos, IndirectObject(objid=objid, genno=0, obj=obj)


class ContentParser(ObjectParser):
    """Parse the concatenation of multiple content streams, as
    described in the spec (PDF 1.7, p.86):

    ...the effect shall be as if all of the streams in the array were
    concatenated, in order, to form a single stream.  Conforming
    writers can create image objects and other resources as they
    occur, even though they interrupt the content stream. The division
    between streams may occur only at the boundaries between lexical
    tokens (see 7.2, "Lexical Conventions") but shall be unrelated to
    the page’s logical content or organization.
    """

    def __init__(self, streams: Iterable[PDFObject], doc: "Document") -> None:
        self.streamiter = iter(streams)
        try:
            stream = stream_value(next(self.streamiter))
            super().__init__(stream.buffer, doc, streamid=stream.objid)
        except StopIteration:
            super().__init__(b"")
        except TypeError:
            log.warning("Found non-stream in contents: %r", streams)
            super().__init__(b"")

    def nexttoken(self) -> Tuple[int, Token]:
        """Override nexttoken() to continue parsing in subsequent streams.

        TODO: If we want to avoid evil implementation inheritance, we
        should do this in the lexer instead.
        """
        while True:
            try:
                return super().nexttoken()
            except StopIteration:
                # Will also raise StopIteration if there are no more,
                # which is exactly what we want
                try:
                    ref = next(self.streamiter)
                    stream = stream_value(ref)
                    self.newstream(stream.buffer, streamid=stream.objid)
                except TypeError:
                    log.warning("Found non-stream in contents: %r", ref)
