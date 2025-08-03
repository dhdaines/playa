"""PDF cross-reference tables / streams."""

import logging
from typing import (
    Any,
    Dict,
    Iterable,
    Iterator,
    List,
    NamedTuple,
    Optional,
    Protocol,
    Tuple,
)

from playa.exceptions import (
    PDFSyntaxError,
)
from playa.parser import (
    KEYWORD_TRAILER,
    LIT,
    IndirectObjectParser,
    ObjectParser,
)
from playa.pdftypes import (
    ContentStream,
    dict_value,
    int_value,
    list_value,
    stream_value,
)
from playa.utils import (
    choplist,
    nunpack,
)

log = logging.getLogger(__name__)
LITERAL_OBJSTM = LIT("ObjStm")
LITERAL_XREF = LIT("XRef")


class XRefPos(NamedTuple):
    streamid: Optional[int]
    pos: int
    genno: int


class XRef(Protocol):
    """
    Duck-typing for XRef table implementations, which are expected to be read-only.
    """

    @property
    def trailer(self) -> Dict[str, Any]: ...

    @property
    def objids(self) -> Iterable[int]: ...

    def get_pos(self, objid: int) -> XRefPos: ...


class XRefTable:
    """Simplest (PDF 1.0) implementation of cross-reference table, in
    plain text at the end of the file.
    """

    def __init__(
        self,
        parser: ObjectParser,
        offset: int = 0,
    ) -> None:
        self.offsets: Dict[int, XRefPos] = {}
        self.trailer: Dict[str, Any] = {}
        self._load(parser, offset)

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
            log.debug("reading positions of objects %d to %d", start, start + nobjs - 1)
            objid = start
            while objid < start + nobjs:
                # FIXME: It's supposed to be exactly 20 bytes, not
                # necessarily a line
                pos, line = parser.nextline()
                log.debug("%r %r", pos, line)
                if line == b"":  # EOF
                    raise StopIteration("EOF in xref table parsing")
                line = line.strip()
                if line == b"trailer":  # oops, nobjs was wrong
                    log.warning(f"Expect object at {pos}, got trailer")
                    # We will hit trailer on the next outer loop
                    parser.seek(pos)
                    break
                # We need to tolerate blank lines here in case someone
                # has creatively ended an entry with \r\r or \n\n
                if line == b"":  # Blank line
                    continue
                f = line.split(b" ")
                if len(f) != 3:
                    raise PDFSyntaxError(f"Invalid XRef format: line={line!r}")
                (pos_b, genno_b, use_b) = f
                if use_b != b"n":
                    # Ignore free entries, we don't care
                    objid += 1
                    continue
                log.debug(
                    "object %d %d at pos %d", objid, int(genno_b), int(pos_b) + offset
                )
                self.offsets[objid] = XRefPos(None, int(pos_b) + offset, int(genno_b))
                objid += 1
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
        return "<XRefTable: offsets=%r>" % (self.offsets.keys())

    @property
    def objids(self) -> Iterable[int]:
        return self.offsets.keys()

    def get_pos(self, objid: int) -> XRefPos:
        return self.offsets[objid]


class XRefFallback:
    """In the case where a file is non-conforming and has no
    `startxref` marker at its end, we will reconstruct a
    cross-reference table by simply scanning the entire file to find
    all indirect objects."""

    def __init__(self, parser: IndirectObjectParser) -> None:
        self.offsets: Dict[int, XRefPos] = {}
        self.trailer: Dict[str, Any] = {}
        self._load(parser)

    def __repr__(self) -> str:
        return "<XRefFallback: offsets=%r>" % (self.offsets.keys())

    def _load(self, parser: IndirectObjectParser) -> None:
        parser.seek(0)
        parser.reset()
        doc = parser.doc
        assert doc is not None
        # Get all the objects
        for pos, obj in parser:
            log.debug(
                "Indirect object %d %d at %d: %r", obj.objid, obj.genno, pos, obj.obj
            )
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
            if (
                isinstance(obj.obj, ContentStream)
                and obj.obj.get("Type") is LITERAL_OBJSTM
            ):
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
        # Now get the trailer.  Maybe there are multiple trailers.
        # Because this is a salvage operation, we will simply
        # agglomerate them - due to incremental updates the last one
        # should be the most recent, but we can't count on it being
        # complete or correct.
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

    @property
    def objids(self) -> Iterable[int]:
        return self.offsets.keys()

    def get_pos(self, objid: int) -> XRefPos:
        return self.offsets[objid]


class XRefStream:
    """Cross-reference stream (as of PDF 1.5)"""

    def __init__(self, parser: IndirectObjectParser, offset: int = 0) -> None:
        self.offset = offset
        self.data: Optional[bytes] = None
        self.entlen: Optional[int] = None
        self.fl1: Optional[int] = None
        self.fl2: Optional[int] = None
        self.fl3: Optional[int] = None
        self.ranges: List[Tuple[int, int]] = []
        self._load(parser)

    def __repr__(self) -> str:
        return "<XRefStream: ranges=%r>" % (self.ranges)

    def _load(self, parser: IndirectObjectParser) -> None:
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

    @property
    def objids(self) -> Iterator[int]:
        for start, nobjs in self.ranges:
            for i in range(nobjs):
                assert self.entlen is not None
                assert self.data is not None
                offset = self.entlen * i
                ent = self.data[offset : offset + self.entlen]
                f1 = nunpack(ent[: self.fl1], 1)
                if f1 == 1 or f1 == 2:
                    yield start + i

    def get_pos(self, objid: int) -> XRefPos:
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
