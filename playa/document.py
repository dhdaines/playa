"""
Basic classes for PDF document parsing.
"""

import io
import itertools
import logging
import mmap
import re
from concurrent.futures import Executor
from typing import (
    Any,
    BinaryIO,
    Callable,
    Dict,
    Iterable,
    Iterator,
    List,
    Mapping,
    Optional,
    Set,
    Tuple,
    Union,
    overload,
)

from playa.data_structures import NameTree, NumberTree
from playa.exceptions import (
    PDFEncryptionError,
    PDFSyntaxError,
)
from playa.font import CIDFont, Font, TrueTypeFont, Type1Font, Type3Font
from playa.outline import Destination, Outline
from playa.page import (
    DeviceSpace,
    Page,
)
from playa.parser import (
    KEYWORD_OBJ,
    KEYWORD_XREF,
    LIT,
    IndirectObject,
    IndirectObjectParser,
    Lexer,
    ObjectParser,
    ObjectStreamParser,
    PDFObject,
    PSLiteral,
    Token,
    literal_name,
    reverse_iter_lines,
)
from playa.pdftypes import (
    ContentStream,
    DecipherCallable,
    ObjRef,
    dict_value,
    int_value,
    list_value,
    resolve1,
    str_value,
    stream_value,
)
from playa.security import SECURITY_HANDLERS
from playa.structure import Tree
from playa.utils import (
    decode_text,
    format_int_alpha,
    format_int_roman,
)
from playa.worker import (
    PageRef,
    _deref_document,
    _deref_page,
    _ref_document,
    _set_document,
    in_worker,
)
from playa.xref import XRef, XRefFallback, XRefStream, XRefTable

log = logging.getLogger(__name__)


# Some predefined literals and keywords (these can be defined wherever
# they are used as they are interned to the same objects)
LITERAL_PDF = LIT("PDF")
LITERAL_TEXT = LIT("Text")
LITERAL_FONT = LIT("Font")
LITERAL_OBJSTM = LIT("ObjStm")
LITERAL_XREF = LIT("XRef")
LITERAL_CATALOG = LIT("Catalog")
LITERAL_PAGE = LIT("Page")
LITERAL_PAGES = LIT("Pages")
INHERITABLE_PAGE_ATTRS = {"Resources", "MediaBox", "CropBox", "Rotate"}


def _find_header(buffer: Union[bytes, mmap.mmap]) -> Tuple[bytes, int]:
    start = buffer.find(b"%PDF-")
    if start == -1:
        log.warning("Could not find b'%PDF-' header, is this a PDF?")
        return b"", 0
    return buffer[start : start + 8], start


def _open_input(fp: Union[BinaryIO, bytes]) -> Tuple[str, int, Union[bytes, mmap.mmap]]:
    if isinstance(fp, bytes):
        buffer: Union[bytes, mmap.mmap] = fp
    else:
        try:
            buffer = mmap.mmap(fp.fileno(), 0, access=mmap.ACCESS_READ)
        except io.UnsupportedOperation:
            log.warning("mmap not supported on %r, reading document into memory", fp)
            buffer = fp.read()
        except ValueError:
            raise
    hdr, offset = _find_header(buffer)
    try:
        version = hdr[5:].decode("ascii")
    except UnicodeDecodeError:
        log.warning("Version number in header %r contains non-ASCII characters", hdr)
        version = "1.0"
    if not re.match(r"\d\.\d", version):
        log.warning("Version number in header %r is invalid", hdr)
        version = "1.0"
    return version, offset, buffer


class Document:
    """Representation of a PDF document.

    Since PDF documents can be very large and complex, merely creating
    a `Document` does very little aside from verifying that the
    password is correct and getting a minimal amount of metadata.  In
    general, PLAYA will try to open just about anything as a PDF, so
    you should not expect the constructor to fail here if you give it
    nonsense (something else may fail later on).

    Some metadata, such as the structure tree and page tree, will be
    loaded lazily and cached.  We do not handle modification of PDFs.

    Args:
      fp: File-like object in binary mode, or a buffer with binary data.
          Files will be read using `mmap` if possible.  They do not need
          to be seekable, as if `mmap` fails the entire file will simply
          be read into memory (so a pipe or socket ought to work).
      password: Password for decryption, if needed.
      space: the device space to use for interpreting content ("screen"
          or "page")

    Raises:
      TypeError: if `fp` is a file opened in text mode (don't do that!)
      PDFEncryptionError: if the PDF has an unsupported encryption scheme
      PDFPasswordIncorrect: if the password is incorrect
    """

    _fp: Union[BinaryIO, None] = None
    _pages: Union["PageList", None] = None
    _pool: Union[Executor, None] = None
    _outline: Union["Outline", None] = None
    _destinations: Union["Destinations", None] = None

    def __enter__(self) -> "Document":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def close(self) -> None:
        # If we were opened from a file then close it
        if self._fp:
            self._fp.close()
            self._fp = None
        # Shutdown process pool
        if self._pool:
            self._pool.shutdown()
            self._pool = None

    def __init__(
        self,
        fp: Union[BinaryIO, bytes],
        password: str = "",
        space: DeviceSpace = "screen",
        _boss_id: int = 0,
    ) -> None:
        if _boss_id:
            # Set this **right away** because it is needed to get
            # indirect object references right.
            _set_document(self, _boss_id)
            assert in_worker()
        self.xrefs: List[XRef] = []
        self.space = space
        self.info = []
        self.catalog: Dict[str, Any] = {}
        self.encryption: Optional[Tuple[Any, Any]] = None
        self.decipher: Optional[DecipherCallable] = None
        self._cached_objs: Dict[int, PDFObject] = {}
        self._parsed_objs: Dict[int, Tuple[List[PDFObject], int]] = {}
        self._cached_fonts: Dict[object, Font] = {}
        if isinstance(fp, io.TextIOBase):
            raise TypeError("fp is not a binary file")
        self.pdf_version, self.offset, self.buffer = _open_input(fp)
        self.is_printable = self.is_modifiable = self.is_extractable = True
        # Getting the XRef table and trailer is done non-lazily
        # because they contain encryption information among other
        # things.  As noted above we don't try to look for the first
        # page cross-reference table (for linearized PDFs) after the
        # header, it will instead be loaded with all the rest.
        self.parser = IndirectObjectParser(self.buffer, self)
        self.parser.seek(self.offset)
        self._xrefpos: Set[int] = set()
        try:
            pos = self._find_xref()
            log.debug("Found xref at %d", pos)
            self._read_xref_from(pos, self.xrefs)
        except (ValueError, IndexError, StopIteration, PDFSyntaxError) as e:
            log.debug("Using fallback XRef parsing: %s", e)
            newxref = XRefFallback(self.parser)
            self.xrefs.append(newxref)
        # Now find the trailer
        for xref in self.xrefs:
            trailer = xref.trailer
            if not trailer:
                continue
            # If there's an encryption info, remember it.
            if "Encrypt" in trailer:
                if "ID" in trailer:
                    id_value = list_value(trailer["ID"])
                else:
                    # Some documents may not have a /ID, use two empty
                    # byte strings instead. Solves
                    # https://github.com/pdfminer/pdfminer.six/issues/594
                    id_value = (b"", b"")
                self.encryption = (id_value, dict_value(trailer["Encrypt"]))
                self._initialize_password(password)
            if "Info" in trailer:
                try:
                    self.info.append(dict_value(trailer["Info"]))
                except TypeError:
                    log.warning("Info is a broken reference (incorrect xref table?)")
            if "Root" in trailer:
                # Every PDF file must have exactly one /Root dictionary.
                try:
                    self.catalog = dict_value(trailer["Root"])
                except TypeError:
                    log.warning("Root is a broken reference (incorrect xref table?)")
                    self.catalog = {}
                break
        else:
            log.warning("No /Root object! - Is this really a PDF?")
        if self.catalog.get("Type") is not LITERAL_CATALOG:
            log.warning("Catalog not found!")
        if "Version" in self.catalog:
            log.debug(
                "Using PDF version %r from catalog instead of %r from header",
                self.catalog["Version"],
                self.pdf_version,
            )
            self.pdf_version = literal_name(self.catalog["Version"])
        self.is_tagged = False
        markinfo = resolve1(self.catalog.get("MarkInfo"))
        if isinstance(markinfo, dict):
            self.is_tagged = not not markinfo.get("Marked")

    def _initialize_password(self, password: str = "") -> None:
        """Initialize the decryption handler with a given password, if any.

        Internal function, requires the Encrypt dictionary to have
        been read from the trailer into self.encryption.
        """
        assert self.encryption is not None
        (docid, param) = self.encryption
        if literal_name(param.get("Filter")) != "Standard":
            raise PDFEncryptionError("Unknown filter: param=%r" % param)
        v = int_value(param.get("V", 0))
        # 3 (PDF 1.4) An unpublished algorithm that permits encryption
        # key lengths ranging from 40 to 128 bits. This value shall
        # not appear in a conforming PDF file.
        if v == 3:
            raise PDFEncryptionError("Unpublished algorithm 3 not supported")
        factory = SECURITY_HANDLERS.get(v)
        # 0 An algorithm that is undocumented. This value shall not be used.
        if factory is None:
            raise PDFEncryptionError("Unknown algorithm: param=%r" % param)
        handler = factory(docid, param, password)
        self.decipher = handler.decrypt
        self.is_printable = handler.is_printable
        self.is_modifiable = handler.is_modifiable
        self.is_extractable = handler.is_extractable
        assert self.parser is not None
        # Ensure that no extra data leaks into encrypted streams
        self.parser.strict = True
        self.parser.decipher = self.decipher

    def __iter__(self) -> Iterator[IndirectObject]:
        """Iterate over top-level `IndirectObject` (does not expand object streams)"""
        return (
            obj
            for pos, obj in IndirectObjectParser(
                self.buffer, self, strict=self.parser.strict
            )
        )

    @property
    def objects(self) -> Iterator[IndirectObject]:
        """Iterate over all indirect objects (including, then expanding object
        streams)"""
        for pos, obj in IndirectObjectParser(
            self.buffer, self, strict=self.parser.strict
        ):
            yield obj
            if (
                isinstance(obj.obj, ContentStream)
                and obj.obj.get("Type") is LITERAL_OBJSTM
            ):
                parser = ObjectStreamParser(obj.obj, self)
                for spos, sobj in parser:
                    yield sobj

    @property
    def tokens(self) -> Iterator[Token]:
        """Iterate over tokens."""
        return (tok for pos, tok in Lexer(self.buffer))

    @property
    def structure(self) -> Union[Tree, None]:
        """Logical structure of this document, if any.

        In the case where no logical structure tree exists, this will
        be `None`.  Otherwise you may iterate over it, search it, etc.
        """
        if "StructTreeRoot" not in self.catalog:
            return None
        return Tree(self)

    @property
    def parent_tree(self) -> Union[NumberTree, None]:
        """Parent tree of this document.

        This is a somewhat obscure data structure that links marked
        content sections to their corresponding structure elements.
        If you don't know what that means, you probably don't need it,
        but if you do, here it is.
        """
        if "StructTreeRoot" not in self.catalog:
            return None
        st = dict_value(self.catalog["StructTreeRoot"])
        if "ParentTree" not in st:
            return None
        return NumberTree(st["ParentTree"])

    def _getobj_objstm(
        self, stream: ContentStream, index: int, objid: int
    ) -> PDFObject:
        if stream.objid in self._parsed_objs:
            (objs, n) = self._parsed_objs[stream.objid]
        else:
            (objs, n) = self._get_objects(stream)
            assert stream.objid is not None
            self._parsed_objs[stream.objid] = (objs, n)
        i = n * 2 + index
        try:
            obj = objs[i]
        except IndexError:
            raise PDFSyntaxError("index too big: %r" % index)
        return obj

    def _get_objects(self, stream: ContentStream) -> Tuple[List[PDFObject], int]:
        if stream.get("Type") is not LITERAL_OBJSTM:
            log.warning("Content stream Type is not /ObjStm: %r" % stream)
        try:
            n = int_value(stream["N"])
        except KeyError:
            log.warning("N is not defined in content stream: %r" % stream)
            n = 0
        except TypeError:
            log.warning("N is invalid in content stream: %r" % stream)
            n = 0
        parser = ObjectParser(stream.buffer, self)
        objs: List[PDFObject] = [obj for _, obj in parser]
        return (objs, n)

    def _getobj_parse(self, pos: int, objid: int) -> PDFObject:
        assert self.parser is not None
        self.parser.seek(pos)
        try:
            _, obj = next(self.parser)
            if obj.objid != objid:
                raise PDFSyntaxError(f"objid mismatch: {obj.objid!r}={objid!r}")
        except (ValueError, IndexError, PDFSyntaxError) as e:
            log.warning(
                "Indirect object %d not found at position %d: %r", objid, pos, e
            )
            # In case of malformed pdf files where the offset in the
            # xref table doesn't point exactly at the object
            # definition (probably more frequent than you think), just
            # use a regular expression to find the object because we
            # can do that.
            realpos = -1
            lastgen = -1
            for m in re.finditer(rb"%d\s+(\d+)\s+obj" % objid, self.buffer):
                genno = int(m.group(1))
                if genno > lastgen:
                    lastgen = genno
                    realpos = m.start(0)
            if realpos == -1:
                raise PDFSyntaxError(
                    f"Indirect object {objid!r} not found in document"
                ) from e
            self.parser.seek(realpos)
            (_, obj) = next(self.parser)
        if obj.objid != objid:
            raise PDFSyntaxError(f"objid mismatch: {obj.objid!r}={objid!r}")
        return obj.obj

    def __getitem__(self, objid: int) -> PDFObject:
        """Get an indirect object from the PDF.

        Note that the behaviour in the case of a non-existent object
        (raising `IndexError`), while Pythonic, is not PDFic, as PDF
        1.7 sec 7.3.10 states:

        > An indirect reference to an undefined object shall not be
        considered an error by a conforming reader; it shall be
        treated as a reference to the null object.

        Raises:
          ValueError: if Document is not initialized
          IndexError: if objid does not exist in PDF

        """
        if not self.xrefs:
            raise ValueError("Document is not initialized")
        if objid not in self._cached_objs:
            obj = None
            for xref in self.xrefs:
                try:
                    (strmid, index, genno) = xref.get_pos(objid)
                except KeyError:
                    continue
                try:
                    if strmid is not None:
                        stream = stream_value(self[strmid])
                        obj = self._getobj_objstm(stream, index, objid)
                    else:
                        obj = self._getobj_parse(index, objid)
                    break
                # FIXME: We might not actually want to catch these...
                except StopIteration:
                    log.debug("EOF when searching for object %d", objid)
                    continue
                except PDFSyntaxError as e:
                    log.debug("Syntax error when searching for object %d: %s", objid, e)
                    continue
            if obj is None:
                raise IndexError(f"Object with ID {objid} not found")
            self._cached_objs[objid] = obj
        return self._cached_objs[objid]

    def get_font(self, objid: object, spec: Mapping[str, object]) -> Font:
        if objid and objid in self._cached_fonts:
            return self._cached_fonts[objid]
        if spec.get("Type") is not LITERAL_FONT:
            log.warning("Font specification Type is not /Font: %r", spec)
        # Create a Font object.
        if "Subtype" in spec:
            subtype = literal_name(spec["Subtype"])
        else:
            log.warning("Font specification Subtype is not specified: %r", spec)
            subtype = ""
        if subtype in ("Type1", "MMType1"):
            # Type1 Font
            font: Font = Type1Font(spec)
        elif subtype == "TrueType":
            # TrueType Font
            font = TrueTypeFont(spec)
        elif subtype == "Type3":
            # Type3 Font
            font = Type3Font(spec)
        elif subtype == "Type0":
            # Type0 Font
            dfonts = list_value(spec["DescendantFonts"])
            assert dfonts
            if len(dfonts) != 1:
                log.debug("Type 0 font should have 1 descendant, has more: %r", dfonts)
            subspec = dict_value(dfonts[0]).copy()
            # Merge the root and descendant font dictionaries
            for k in ("Encoding", "ToUnicode"):
                if k in spec:
                    subspec[k] = resolve1(spec[k])
            font = CIDFont(subspec)
        else:
            log.warning("Invalid Font spec, creating dummy font: %r" % spec)
            # We need a dummy font object to be able to do *something*
            # (even if it's the wrong thing) with text objects.
            font = Font({}, {})
        if objid:
            self._cached_fonts[objid] = font
        return font

    @property
    def outline(self) -> Union[Outline, None]:
        """Document outline, if any."""
        if "Outlines" not in self.catalog:
            return None
        if self._outline is None:
            try:
                self._outline = Outline(self)
            except TypeError:
                log.warning(
                    "Invalid Outlines entry in catalog: %r", self.catalog["Outlines"]
                )
                return None
        return self._outline

    @property
    def page_labels(self) -> Iterator[str]:
        """Generate page label strings for the PDF document.

        If the document includes page labels, generates strings, one per page.
        If not, raise KeyError.

        The resulting iterator is unbounded (because the page label
        tree does not actually include all the pages), so it is
        recommended to use `pages` instead.

        Raises:
          KeyError: No page labels are present in the catalog

        """
        assert self.catalog is not None  # really it cannot be None

        page_labels = PageLabels(self.catalog["PageLabels"])
        return page_labels.labels

    PageType = Dict[Any, Dict[Any, Any]]

    def _get_pages_from_xrefs(self) -> Iterator[Tuple[int, PageType]]:
        """Find pages from the cross-reference tables if the page tree
        is missing (note that this only happens in invalid PDFs, but
        it happens.)

        Returns:
          an iterator over (objid, dict) pairs.
        """
        for xref in self.xrefs:
            for object_id in xref.objids:
                try:
                    obj = self[object_id]
                    if isinstance(obj, dict) and obj.get("Type") is LITERAL_PAGE:
                        yield object_id, obj
                except IndexError:
                    pass

    def _get_page_objects(self) -> Iterator[Tuple[int, PageType]]:
        """Iterate over the flattened page tree in reading order, propagating
        inheritable attributes.  Returns an iterator over (objid, dict) pairs.

        Raises:
          KeyError: if there is no page tree.
        """
        if "Pages" not in self.catalog:
            raise KeyError("No 'Pages' entry in catalog")
        stack = [(self.catalog["Pages"], self.catalog)]
        visited = set()
        while stack:
            (obj, parent) = stack.pop()
            if isinstance(obj, ObjRef):
                # The PDF specification *requires* both the Pages
                # element of the catalog and the entries in Kids in
                # the page tree to be indirect references.
                object_id = int(obj.objid)
            elif isinstance(obj, int):
                # Should not happen in a valid PDF, but probably does?
                log.warning("Page tree contains bare integer: %r in %r", obj, parent)
                object_id = obj
            else:
                log.warning("Page tree contains unknown object: %r", obj)
            page_object = dict_value(self[object_id])

            # Avoid recursion errors by keeping track of visited nodes
            # (again, this should never actually happen in a valid PDF)
            if object_id in visited:
                log.warning("Circular reference %r in page tree", obj)
                continue
            visited.add(object_id)

            # Propagate inheritable attributes
            object_properties = page_object.copy()
            for k, v in parent.items():
                if k in INHERITABLE_PAGE_ATTRS and k not in object_properties:
                    object_properties[k] = v

            # Recurse, depth-first
            object_type = object_properties.get("Type")
            if object_type is None:
                log.warning("Page has no Type, trying type: %r", object_properties)
                object_type = object_properties.get("type")
            if object_type is LITERAL_PAGES and "Kids" in object_properties:
                for child in reversed(list_value(object_properties["Kids"])):
                    stack.append((child, object_properties))
            elif object_type is LITERAL_PAGE:
                yield object_id, object_properties

    @property
    def pages(self) -> "PageList":
        """Pages of the document as an iterable/addressable `PageList` object."""
        if self._pages is None:
            self._pages = PageList(self)
        return self._pages

    @property
    def names(self) -> Dict[str, Any]:
        """PDF name dictionary (PDF 1.7 sec 7.7.4).

        Raises:
          KeyError: if nonexistent.
        """
        return dict_value(self.catalog["Names"])

    @property
    def destinations(self) -> "Destinations":
        """Named destinations as an iterable/addressable `Destinations` object."""
        if self._destinations is None:
            self._destinations = Destinations(self)
        return self._destinations

    def _find_xref(self) -> int:
        """Internal function used to locate the first XRef."""
        # search the last xref table by scanning the file backwards.
        prev = b""
        for pos, line in reverse_iter_lines(self.buffer):
            line = line.strip()
            if line == b"startxref":
                if not prev.isdigit():
                    log.warning("Invalid startxref position: %r", prev)
                    continue
                start = int(prev)
                if not start >= 0:
                    raise ValueError("Invalid negative startxref position: %d" % start)
                elif start > pos:
                    raise ValueError(
                        "Invalid startxref position (> %d): %d" % (pos, start)
                    )
                return start + self.offset
            elif line == b"xref":
                return pos
            elif line == b"endobj":
                # Okay, we're probably not in Kansas anymore...
                break
            if line:
                prev = line
        raise ValueError("No xref table found at end of file")

    # read xref table
    def _read_xref_from(
        self,
        start: int,
        xrefs: List[XRef],
    ) -> None:
        """Reads XRefs from the given location."""
        if start in self._xrefpos:
            log.warning("Detected circular xref chain at %d", start)
            return
        self._xrefpos.add(start)
        parser = ObjectParser(self.buffer, self, start)
        try:
            (pos, token) = parser.nexttoken()
        except StopIteration:
            raise ValueError("Unexpected EOF at {start}")
        if token is KEYWORD_XREF:
            parser.nextline()
            xref: XRef = XRefTable(parser, self.offset)
        else:
            # It might be an XRefStream, if this is an indirect object...
            _, token = parser.nexttoken()
            _, token = parser.nexttoken()
            if token is KEYWORD_OBJ:
                # XRefStream: PDF-1.5
                self.parser.seek(pos)
                self.parser.reset()
                xref = XRefStream(self.parser, self.offset)
            else:
                # Well, maybe it's an XRef table without "xref" (but
                # probably not)
                parser.seek(pos)
                xref = XRefTable(parser, self.offset)
        xrefs.append(xref)
        trailer = xref.trailer
        # For hybrid-reference files, an additional set of xrefs as a
        # stream.
        if "XRefStm" in trailer:
            pos = int_value(trailer["XRefStm"])
            self._read_xref_from(pos + self.offset, xrefs)
        # Recurse into any previous xref tables or streams
        if "Prev" in trailer:
            # find previous xref
            pos = int_value(trailer["Prev"])
            self._read_xref_from(pos + self.offset, xrefs)


def call_page(func: Callable[[Page], Any], pageref: PageRef) -> Any:
    """Call a function on a page in a worker process."""
    return func(_deref_page(pageref))


class PageList:
    """List of pages indexable by 0-based index or string label.

    Attributes:
        have_labels: If pages have explicit labels in the PDF.
    """

    have_labels: bool

    def __init__(
        self, doc: Document, pages: Union[Iterable[Page], None] = None
    ) -> None:
        self.docref = _ref_document(doc)
        if pages is not None:
            self._pages = list(pages)
            self._labels: Dict[str, Page] = {
                page.label: page for page in pages if page.label is not None
            }
            self.have_labels = not not self._labels
        else:
            self._init_pages(doc)

    def _init_pages(self, doc: Document) -> None:
        try:
            page_labels: Iterable[Union[str, None]] = doc.page_labels
            self.have_labels = True
        except (KeyError, ValueError):
            page_labels = (str(idx) for idx in itertools.count(1))
            self.have_labels = False
        self._pages = []
        self._objids = {}
        self._labels = {}
        try:
            page_objects = list(doc._get_page_objects())
        except (KeyError, IndexError, TypeError):
            page_objects = list(doc._get_pages_from_xrefs())
        for page_idx, ((objid, properties), label) in enumerate(
            zip(page_objects, page_labels)
        ):
            page = Page(doc, objid, properties, label, page_idx, doc.space)
            self._pages.append(page)
            self._objids[objid] = page
            if label is not None:
                if label in self._labels:
                    log.info("Duplicate page label %s at index %d", label, page_idx)
                else:
                    self._labels[label] = page

    @property
    def doc(self) -> "Document":
        """Get associated document if it exists."""
        return _deref_document(self.docref)

    def __len__(self) -> int:
        return len(self._pages)

    def __iter__(self) -> Iterator[Page]:
        return iter(self._pages)

    @overload
    def __getitem__(self, key: int) -> Page: ...

    @overload
    def __getitem__(self, key: str) -> Page: ...

    @overload
    def __getitem__(self, key: slice) -> "PageList": ...

    @overload
    def __getitem__(self, key: Iterable[int]) -> "PageList": ...

    @overload
    def __getitem__(self, key: Iterator[Union[int, str]]) -> "PageList": ...

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._pages[key]
        elif isinstance(key, str):
            return self._labels[key]
        elif isinstance(key, slice):
            return PageList(_deref_document(self.docref), self._pages[key])
        else:
            return PageList(_deref_document(self.docref), (self[k] for k in key))

    def by_id(self, objid: int) -> Page:
        """Get a page by its indirect object ID.

        Args:
            objid: Indirect object ID for the page object.

        Returns:
            the page in question.
        """
        return self._objids[objid]

    def map(self, func: Callable[[Page], Any]) -> Iterator:
        """Apply a function over each page, iterating over its results.

        Args:
            func: The function to apply to each page.

        Note:
            This possibly runs `func` in a separate process.  If its
            return value is not serializable (by `pickle`) then you
            will encounter errors.
        """
        doc = _deref_document(self.docref)
        if doc._pool is not None:
            return doc._pool.map(
                call_page,
                itertools.repeat(func),
                ((id(doc), page.page_idx) for page in self),
            )
        else:
            return (func(page) for page in self)


class PageLabels(NumberTree):
    """PageLabels from the document catalog.

    See Section 12.4.2 in the PDF 1.7 Reference.
    """

    @property
    def labels(self) -> Iterator[str]:
        itor = iter(self)
        try:
            start, label_dict_unchecked = next(itor)
            # The tree must begin with page index 0
            if start != 0:
                log.warning("PageLabels tree is missing page index 0")
                # Try to cope, by assuming empty labels for the initial pages
                start = 0
        except StopIteration:
            log.warning("PageLabels tree is empty")
            start = 0
            label_dict_unchecked = {}

        while True:  # forever!
            label_dict = dict_value(label_dict_unchecked)
            style = label_dict.get("S")
            prefix = decode_text(str_value(label_dict.get("P", b"")))
            first_value = int_value(label_dict.get("St", 1))

            try:
                next_start, label_dict_unchecked = next(itor)
            except StopIteration:
                # This is the last specified range. It continues until the end
                # of the document.
                values: Iterable[int] = itertools.count(first_value)
            else:
                range_length = next_start - start
                values = range(first_value, first_value + range_length)
                start = next_start

            for value in values:
                label = self._format_page_label(value, style)
                yield prefix + label

    @staticmethod
    def _format_page_label(value: int, style: Any) -> str:
        """Format page label value in a specific style"""
        if style is None:
            label = ""
        elif style is LIT("D"):  # Decimal arabic numerals
            label = str(value)
        elif style is LIT("R"):  # Uppercase roman numerals
            label = format_int_roman(value).upper()
        elif style is LIT("r"):  # Lowercase roman numerals
            label = format_int_roman(value)
        elif style is LIT("A"):  # Uppercase letters A-Z, AA-ZZ...
            label = format_int_alpha(value).upper()
        elif style is LIT("a"):  # Lowercase letters a-z, aa-zz...
            label = format_int_alpha(value)
        else:
            log.warning("Unknown page label style: %r", style)
            label = ""
        return label


class Destinations:
    """Mapping of named destinations.

    These either come as a NameTree or a dict, depending on the
    version of the PDF standard, so this abstracts that away.
    """

    dests_dict: Union[Dict[str, PDFObject], None] = None
    dests_tree: Union[NameTree, None] = None

    def __init__(self, doc: Document) -> None:
        self._docref = _ref_document(doc)
        self.dests: Dict[str, Destination] = {}
        if "Dests" in doc.catalog:
            # PDF-1.1: dictionary
            self.dests_dict = resolve1(doc.catalog["Dests"])
            if not isinstance(self.dests_dict, dict):
                log.warning(
                    "Dests entry in catalog is not dictionary: %r", self.dests_dict
                )
                self.dests_dict = None
        elif "Names" in doc.catalog:
            names = resolve1(doc.catalog["Names"])
            if not isinstance(names, dict):
                log.warning("Names entry in catalog is not dictionary: %r", names)
                return
            if "Dests" in names:
                dests = resolve1(names["Dests"])
                if not isinstance(names, dict):
                    log.warning("Dests entry in names is not dictionary: %r", dests)
                    return
                self.dests_tree = NameTree(dests)

    def __iter__(self) -> Iterator[str]:
        """Iterate over names of destinations.

        Danger: Beware of corrupted PDFs
            This simply iterates over the names listed in the PDF, and
            does not attempt to actually parse the destinations
            (because that's pretty slow).  If the PDF is broken, you
            may encounter exceptions when actually trying to access
            them by name.
        """
        if self.dests_dict is not None:
            yield from self.dests_dict
        elif self.dests_tree is not None:
            for kb, _ in self.dests_tree:
                ks = decode_text(kb)
                yield ks

    def items(self) -> Iterator[Tuple[str, Destination]]:
        """Iterate over named destinations."""
        if self.dests_dict is not None:
            for name, dest in self.dests_dict.items():
                if name not in self.dests:
                    dest = resolve1(self.dests_dict[name])
                    self.dests[name] = self._create_dest(dest, name)
                yield name, self.dests[name]
        elif self.dests_tree is not None:
            for k, v in self.dests_tree:
                name = decode_text(k)
                if name not in self.dests:
                    dest = resolve1(v)
                    self.dests[name] = self._create_dest(dest, name)
                yield name, self.dests[name]

    def __getitem__(self, name: Union[bytes, str, PSLiteral]) -> Destination:
        """Get a named destination.

        Args:
            name: The name of the destination.

        Raises:
            KeyError: If no such destination exists.
            TypeError: If the PDF is damaged and the destinations tree
                contains something unexpected or missing.
        """
        if isinstance(name, bytes):
            name = decode_text(name)
        elif isinstance(name, PSLiteral):
            name = literal_name(name)
        if name in self.dests:
            return self.dests[name]
        elif self.dests_dict is not None:
            # This will raise KeyError or TypeError if necessary, so
            # we don't have to do it explicitly
            dest = resolve1(self.dests_dict[name])
            self.dests[name] = self._create_dest(dest, name)
        elif self.dests_tree is not None:
            # This is not at all efficient, but we need to decode
            # the keys (and we cache the result...)
            for k, v in self.dests_tree:
                if decode_text(k) == name:
                    dest = resolve1(v)
                    self.dests[name] = self._create_dest(dest, name)
                    break
        # This will also raise KeyError if necessary
        return self.dests[name]

    def _create_dest(self, dest: PDFObject, name: str) -> Destination:
        if isinstance(dest, list):
            return Destination.from_list(self.doc, dest)
        elif isinstance(dest, dict) and "D" in dest:
            destlist = resolve1(dest["D"])
            if not isinstance(destlist, list):
                raise TypeError("Invalid destination for %s: %r", name, dest)
            return Destination.from_list(self.doc, destlist)
        else:
            raise TypeError("Invalid destination for %s: %r", name, dest)

    @property
    def doc(self) -> "Document":
        """Get associated document if it exists."""
        return _deref_document(self._docref)
