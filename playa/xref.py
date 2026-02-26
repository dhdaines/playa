"""PDF cross-reference tables / streams."""

import itertools
import logging
import re
from typing import (
    Dict,
    Final,
    Iterator,
    List,
    Mapping,
    NamedTuple,
    Tuple,
    Union,
    TYPE_CHECKING,
)

from playa.exceptions import (
    PDFSyntaxError,
)
from playa.parser import (
    WHITESPACE,
    KEYWORD_TRAILER,
    LIT,
    IndirectObjectParser,
    ObjectParser,
)
from playa.pdftypes import (
    ContentStream,
    ObjRef,
    PDFObject,
    dict_value,
    int_value,
    list_value,
    stream_value,
)
from playa.utils import (
    choplist,
    nunpack,
)
from playa.worker import _ref_document

if TYPE_CHECKING:
    from playa.document import Document

log: Final = logging.getLogger(__name__)
LITERAL_OBJSTM: Final = LIT("ObjStm")
LITERAL_XREF: Final = LIT("XRef")
# Specific regex optimized only for finding objects (SFOOFFO)
FIND_INDOBJR: Final = re.compile(rb"(?<!\d)\d{1,10}\s+\d{1,10}\s+obj")
INDOBJR: Final = re.compile(rb"\s*\d{1,10}\s+\d{1,10}\s+obj")
XREFR: Final = re.compile(rb"\s*xref\s*(\d+)\s*(\d+)\s*")


def _update_refs(trailer: Dict[str, PDFObject], doc: "Document") -> None:
    docref = _ref_document(doc)
    for val in trailer.values():
        if isinstance(val, ObjRef):
            val.doc = docref


class XRefPos(NamedTuple):
    streamid: Union[int, None]
    pos: int
    genno: int


class XRef(Mapping[int, XRefPos]):
    """
    XRef table interface (expected to be read-only)
    """

    trailer: Dict[str, PDFObject]


class XRefTable(XRef):
    """Simplest (PDF 1.0) implementation of cross-reference table, in
    plain text at the end of the file.
    """

    def __init__(
        self, doc: Union["Document", None] = None, pos: int = 0, offset: int = 0
    ) -> None:
        self.subsections: List[XRefTableSubsection] = []
        self.trailer: Dict[str, PDFObject] = {}
        if doc is not None:
            self._load(ObjectParser(doc.buffer, doc, pos), offset)

    def _load(self, parser: ObjectParser, offset: int) -> None:
        while True:
            pos, start = next(parser)
            # This means that xref table parsing can only end in three
            # ways: "trailer" (success), EOF (failure) or something
            # other than two numbers (failure).  Hope that's okay.
            if start is KEYWORD_TRAILER:
                parser.seek(pos)
                break
            pos, nobjs = next(parser)
            if not (isinstance(start, int) and isinstance(nobjs, int)):
                raise PDFSyntaxError(
                    f"Expected object ID and count, got {start!r} {nobjs!r}"
                )
            # Cue up the table data
            _, ws = parser.nextline()
            if any(b for b in ws if b not in WHITESPACE):
                raise PDFSyntaxError
            table_data = parser.read(20 * nobjs)
            if len(table_data) != 20 * nobjs:
                raise PDFSyntaxError
            subsection = XRefTableSubsection(table_data, start, nobjs)
            log.debug(subsection)
            if log.level <= logging.DEBUG:
                for objid in subsection:
                    try:
                        ref = subsection[objid]
                    except Exception as e:
                        raise PDFSyntaxError from e
                    log.debug(
                        "object %d %d at pos %d", objid, ref.genno, ref.pos + offset
                    )
            self.subsections.append(subsection)
        self._load_trailer(parser)

    def _load_trailer(self, parser: ObjectParser) -> None:
        (_, kwd) = next(parser)
        # This can actually never happen, because if an xref table
        # doesn't end with "trailer" then some other error happens
        if kwd is not KEYWORD_TRAILER:
            raise PDFSyntaxError(
                "Expected %r, got %r"
                % (
                    KEYWORD_TRAILER,
                    kwd,
                )
            )
        (_, dic) = next(parser)
        self.trailer.update(dict_value(dic))

    def __repr__(self) -> str:
        return "<XRefTable: subsections=%r>" % (self.subsections)

    def __len__(self) -> int:
        return sum(len(x) for x in self.subsections)

    def __iter__(self) -> Iterator[int]:
        return itertools.chain.from_iterable(self.subsections)

    def __getitem__(self, objid: int) -> XRefPos:
        for s in self.subsections:
            if objid in s.range:
                return s[objid]
        raise KeyError


class XRefTableSubsection:
    """A contiguous chunk of object numbers from the cross-reference table."""
    def __init__(
        self,
        data: bytes,
        start: int,
        nobjs: int,
    ):
        self.data = data
        self.start = start
        self.nobjs = nobjs

    def __repr__(self) -> str:
        return "<XRefTableSubsection: start=%d, nobjs=%d>" % (self.start, self.nobjs)

    @property
    def range(self) -> range:
        return range(self.start, self.start + self.nobjs)

    def __len__(self):
        return self.nobjs

    def __iter__(self):
        return (objid for objid in self.range if objid in self)

    def __contains__(self, objid):
        return b"f" != self._get_row(objid)[17:18]

    def _get_row(self, objid: int) -> bytes:
        offset = 20 * self.range.index(objid)
        return self.data[offset:offset + 20]

    def __getitem__(self, objid: int) -> XRefPos:
        row = self._get_row(objid)
        pos = int(row[0:10])
        genno = int(row[11:16])
        use = row[17:18]
        match use:
            case b"n":
                return XRefPos(None, pos, genno)
            case b"f":
                # Ignore free entries, we don't care
                raise KeyError
            case _:
                raise PDFSyntaxError(row)

class XRefFallback(XRef):
    """In the case where a file is non-conforming and has no
    `startxref` marker at its end, we will reconstruct a
    cross-reference table by simply scanning the entire file to find
    all indirect objects."""

    def __init__(
        self, doc: Union["Document", None] = None, pos: int = 0, offset: int = 0
    ) -> None:
        self.offsets: Dict[int, XRefPos] = {}
        self.trailer: Dict[str, PDFObject] = {}
        # Create a new IndirectObjectParser without a parent document
        # to avoid endless looping
        if doc is not None:
            self._load(IndirectObjectParser(doc.buffer, doc=None, pos=pos), doc)

    def __repr__(self) -> str:
        return "<XRefFallback: offsets=%r>" % (self.offsets.keys())

    def _load(self, parser: IndirectObjectParser, doc: "Document") -> None:
        # Get all the objects
        for m in FIND_INDOBJR.finditer(parser.buffer):
            pos = m.start(0)
            log.debug("Indirect object at %d: %r", pos, m.group(0))
            parser.seek(pos)
            pos, obj = next(parser)
            prev_genno = -1
            if obj.objid in self.offsets:
                prev_genno = self.offsets[obj.objid].genno
                # Apparently this isn't an error, nothing requires you
                # to update the generation number!  (what is it good
                # for anyway then?)  PDF 1.7 section 7.5.6
                # (Incremental Updates): As shown in Figure 3, a file
                # that has been updated several times contains several
                # trailers. Because updates are appended to PDF files,
                # a file may have several copies of an object with the
                # same object identifier (object number and generation
                # number).
                if obj.genno == prev_genno:
                    log.debug(
                        "Duplicate object %d %d at %d: %r",
                        obj.objid,
                        obj.genno,
                        pos,
                        obj.obj,
                    )
            if obj.genno >= prev_genno:
                self.offsets[obj.objid] = XRefPos(None, pos, obj.genno)
            # Expand any object streams right away
            if not isinstance(obj.obj, ContentStream):
                continue
            stream_type = obj.obj.get("Type")
            if stream_type is LITERAL_OBJSTM:
                stream = stream_value(obj.obj)
                try:
                    n = stream["N"]
                except KeyError:
                    log.warning("N is not defined in object stream: %r", stream)
                    n = 0
                parser1 = ObjectParser(stream.buffer, doc)
                objs: List = [obj for _, obj in parser1]
                # FIXME: This is choplist
                n = min(n, len(objs) // 2)
                for index in range(n):
                    objid1 = objs[index * 2]
                    self.offsets[objid1] = XRefPos(obj.objid, index, 0)
                # If we find a cross-reference stream, use it as the trailer
            elif stream_type is LITERAL_XREF:
                # See below re: salvage operation
                self.trailer.update(obj.obj.attrs)
        if self.trailer:
            _update_refs(self.trailer, doc)
            return
        # Get the trailer if we didn't find one.  Maybe there are
        # multiple trailers.  Because this is a salvage operation, we
        # will simply agglomerate them - due to incremental updates
        # the last one should be the most recent, but we can't count
        # on it being complete or correct.
        pos = 0
        while True:
            pos = parser.buffer.find(b"trailer", pos)
            if pos == -1:
                break
            pos += len(b"trailer")
            log.debug("Found possible trailer at %d", pos)
            try:
                _, trailer = next(ObjectParser(parser.buffer, doc, pos))
            except (TypeError, PDFSyntaxError):  # pragma: no cover
                # This actually can't happen because ObjectParser will
                # never throw an exception without strict mode (which
                # we won't turn on when doing fallback parsing)
                continue
            if not isinstance(trailer, dict):
                continue
            log.debug("Trailer: %r", trailer)
            self.trailer.update(trailer)
        if not self.trailer:
            log.warning("b'trailer' not found in document or invalid")

    def __len__(self) -> int:
        return len(self.offsets)

    def __iter__(self) -> Iterator[int]:
        return iter(self.offsets)

    def __getitem__(self, objid: int) -> XRefPos:
        return self.offsets[objid]


class XRefStream(XRef):
    """Cross-reference stream (as of PDF 1.5)"""

    def __init__(
        self, doc: Union["Document", None] = None, pos: int = 0, offset: int = 0
    ) -> None:
        self.offset = offset
        self.data: Union[bytes, None] = None
        self.entlen: Union[int, None] = None
        self.fl1: Union[int, None] = None
        self.fl2: Union[int, None] = None
        self.fl3: Union[int, None] = None
        self.ranges: List[Tuple[int, int]] = []
        # Because an XRefStream's dictionary may contain indirect
        # object references, we create a new IndirectObjectParser
        # here with no document to avoid trying to follow them
        # (and thus creating an infinite loop)
        if doc is not None:
            self._load(IndirectObjectParser(doc.buffer, doc=None, pos=pos), doc)

    def __repr__(self) -> str:
        return "<XRefStream: ranges=%r>" % (self.ranges)

    def _load(self, parser: IndirectObjectParser, doc: "Document") -> None:
        (_, obj) = next(parser)
        stream = obj.obj
        if (
            not isinstance(stream, ContentStream)
            or stream.get("Type") is not LITERAL_XREF
        ):
            raise ValueError(f"Invalid PDF stream spec {stream!r}")
        size = stream["Size"]
        index_array = list_value(stream.get("Index") or [0, size])
        if len(index_array) % 2 != 0:
            raise PDFSyntaxError("Invalid index number")
        for start, end in choplist(2, index_array):
            self.ranges.append((int_value(start), int_value(end)))
        (self.fl1, self.fl2, self.fl3) = stream["W"]
        assert self.fl1 is not None and self.fl2 is not None and self.fl3 is not None
        self.data = stream.buffer
        self.entlen = self.fl1 + self.fl2 + self.fl3
        self.trailer = stream.attrs
        # Update any references in trailer to point to the document
        _update_refs(self.trailer, doc)
        # Dump out objects for debugging
        for start, nobjs in self.ranges:
            if log.level > logging.DEBUG:
                break
            log.debug("objects %d - %d:", start, start + nobjs)
            for index in range(nobjs):
                offset = self.entlen * index
                ent = self.data[offset : offset + self.entlen]
                f1 = nunpack(ent[: self.fl1], 1)
                f2 = nunpack(ent[self.fl1 : self.fl1 + self.fl2])
                f3 = nunpack(ent[self.fl1 + self.fl2 :])
                log.debug("obj %d => %d %d %d", start + index, f1, f2, f3)

    def __iter__(self) -> Iterator[int]:
        for start, nobjs in self.ranges:
            for i in range(nobjs):
                assert self.entlen is not None
                assert self.data is not None
                offset = self.entlen * i
                ent = self.data[offset : offset + self.entlen]
                f1 = nunpack(ent[: self.fl1], 1)
                if f1 == 1 or f1 == 2:
                    yield start + i

    def __len__(self) -> int:
        return sum(nobjs for _, nobjs in self.ranges)

    def __getitem__(self, objid: int) -> XRefPos:
        index = 0
        for start, nobjs in self.ranges:
            if start <= objid and objid < start + nobjs:
                index += objid - start
                break
            else:
                index += nobjs
        else:
            raise KeyError(objid)
        assert self.entlen is not None
        assert self.data is not None
        assert self.fl1 is not None and self.fl2 is not None and self.fl3 is not None
        offset = self.entlen * index
        ent = self.data[offset : offset + self.entlen]
        f1 = nunpack(ent[: self.fl1], 1)
        f2 = nunpack(ent[self.fl1 : self.fl1 + self.fl2])
        f3 = nunpack(ent[self.fl1 + self.fl2 :])
        if f1 == 1:  # not in an object stream
            return XRefPos(None, f2 + self.offset, f3)
        elif f1 == 2:  # in an object stream
            return XRefPos(f2, f3, 0)
        else:
            # this is a free object
            raise KeyError(objid)
