import logging
import re
from io import BytesIO
from typing import TYPE_CHECKING, BinaryIO, Optional, Union

from playa import settings
from playa.casting import safe_int
from playa.exceptions import PSEOF, PDFSyntaxError
from playa.pdftypes import PDFObjRef, PDFStream, dict_value, int_value
from playa.psparser import KWD, PSKeyword, PSStackParser

if TYPE_CHECKING:
    from playa.pdfdocument import PDFDocument

log = logging.getLogger(__name__)

# Important keywords
KEYWORD_R = KWD(b"R")
KEYWORD_NULL = KWD(b"null")
KEYWORD_ENDOBJ = KWD(b"endobj")
KEYWORD_STREAM = KWD(b"stream")
KEYWORD_XREF = KWD(b"xref")
KEYWORD_STARTXREF = KWD(b"startxref")
KEYWORD_OBJ = KWD(b"obj")


# PDFParser stack holds all the base types plus PDFStream, PDFObjRef, and None
class PDFParser(PSStackParser[Union[PSKeyword, PDFStream, PDFObjRef, None]]):
    """PDFParser fetch PDF objects from a file stream.
    It can handle indirect references by referring to
    a PDF document set by set_document method.
    It also reads XRefs at the end of every PDF file.

    Typical usage:
      parser = PDFParser(fp)
      parser.read_xref()
      parser.read_xref(fallback=True) # optional
      parser.set_document(doc)
      parser.seek(offset)
      parser.nextobject()

    """

    def __init__(self, fp: BinaryIO) -> None:
        PSStackParser.__init__(self, fp)
        self.doc: Optional[PDFDocument] = None
        self.fallback = False

    def set_document(self, doc: Union["PDFDocument", None]) -> None:
        """Associates the parser with a PDFDocument object."""
        self.doc = doc

    def do_keyword(self, pos: int, token: PSKeyword) -> None:
        """Handles PDF-related keywords."""
        if token in (KEYWORD_XREF, KEYWORD_STARTXREF):
            self.add_results(*self.pop(1))

        elif token is KEYWORD_ENDOBJ:
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
                    obj = PDFObjRef(self.doc, object_id)
                    self.push((pos, obj))

        elif token is KEYWORD_STREAM:
            # stream object
            ((_, dic),) = self.pop(1)
            dic = dict_value(dic)
            objlen = 0
            if not self.fallback:
                try:
                    objlen = int_value(dic["Length"])
                except KeyError:
                    if settings.STRICT:
                        raise PDFSyntaxError("/Length is undefined: %r" % dic)
            self.seek(pos)
            try:
                (_, line) = self.nextline()  # 'stream'
            except PSEOF:
                if settings.STRICT:
                    raise PDFSyntaxError("Unexpected EOF")
                return
            pos += len(line)
            self.fp.seek(pos)
            data = bytearray(self.fp.read(objlen))
            self.seek(pos + objlen)
            while True:
                try:
                    (linepos, line) = self.nextline()
                except PSEOF:
                    if settings.STRICT:
                        raise PDFSyntaxError("Unexpected EOF")
                    break
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
                "Stream: pos=%d, objlen=%d, dic=%r, data=%r...",
                pos,
                objlen,
                dic,
                data[:10],
            )
            assert self.doc is not None
            stream = PDFStream(dic, bytes(data), self.doc.decipher)
            self.push((pos, stream))

        else:
            # others
            self.push((pos, token))


class PDFStreamParser(PDFParser):
    """PDFStreamParser is used to parse PDF content streams
    that is contained in each page and has instructions
    for rendering the page. A reference to a PDF document is
    needed because a PDF content stream can also have
    indirect references to other objects in the same document.
    """

    def __init__(self, data: bytes) -> None:
        PDFParser.__init__(self, BytesIO(data))

    def flush(self) -> None:
        self.add_results(*self.popall())

    def do_keyword(self, pos: int, token: PSKeyword) -> None:
        if token is KEYWORD_R:
            # reference to indirect object
            (_, _object_id), _ = self.pop(2)
            object_id = safe_int(_object_id)
            if object_id is not None:
                obj = PDFObjRef(self.doc, object_id)
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
