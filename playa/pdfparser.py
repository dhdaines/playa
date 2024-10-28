import logging
import mmap
import weakref
from typing import TYPE_CHECKING, Union

from playa import settings
from playa.casting import safe_int
from playa.exceptions import PDFSyntaxError
from playa.pdftypes import PDFObjRef, PDFStream, dict_value, int_value
from playa.psparser import KWD, Parser, PSKeyword

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
class PDFParser(Parser[Union[PSKeyword, PDFStream, PDFObjRef, None]]):
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
                    obj = PDFObjRef(self.doc, object_id)
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
                "Stream: pos=%d, objlen=%d, dic=%r, data=%r...",
                pos,
                objlen,
                dic,
                data[:10],
            )
            doc = self.doc()
            if doc is None:
                raise RuntimeError("Document no longer exists!")
            stream = PDFStream(dic, bytes(data), doc.decipher)
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
