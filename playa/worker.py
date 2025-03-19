"""Worker subprocess related functions and data."""

import weakref
from pathlib import Path
from typing import TYPE_CHECKING, Tuple, Union

if TYPE_CHECKING:
    from playa.document import DeviceSpace, Document
    from playa.page import Page

# Type signature of document reference
DocumentRef = int
# Type signature of page reference
PageRef = Tuple[DocumentRef, int]

# A global PDF object used in worker processes
__pdf: Union["Document", None] = None
# Registry of documents which have workers
__bosses: weakref.WeakValueDictionary[int, "Document"] = weakref.WeakValueDictionary()
# Numeric id of the document in the boss process (will show up instead
# of weak references when serialized, gets looked up in _bosses)
GLOBAL_DOC: int = 0


def in_worker() -> bool:
    """Are we currently in a worker process?"""
    return __pdf is not None


def _init_worker(
    boss: int, path: Path, password: str = "", space: "DeviceSpace" = "screen"
) -> None:
    from playa.document import Document

    global __pdf, GLOBAL_DOC
    fp = open(path, "rb")
    __pdf = Document(fp, password=password, space=space, _boss_id=boss)
    GLOBAL_DOC = boss


def _init_worker_buffer(
    boss: int, buffer: bytes, password: str = "", space: "DeviceSpace" = "screen"
) -> None:
    from playa.document import Document

    global __pdf, GLOBAL_DOC
    __pdf = Document(buffer, password=password, space=space, _boss_id=boss)
    GLOBAL_DOC = boss


def _set_document(doc: "Document", boss: int) -> None:
    """Call this in the worker process."""
    global __pdf, GLOBAL_DOC
    __pdf = doc
    GLOBAL_DOC = boss


def _get_document() -> Union["Document", None]:
    global __pdf
    return __pdf


def _ref_document(doc: "Document") -> DocumentRef:
    if in_worker():
        global GLOBAL_DOC
        assert GLOBAL_DOC != 0
        return GLOBAL_DOC
    else:
        docid = id(doc)
        if docid not in __bosses:
            __bosses[docid] = doc
        return docid


def _deref_document(ref: DocumentRef) -> "Document":
    if in_worker():
        doc = __pdf
    else:
        if ref not in __bosses:
            raise RuntimeError(f"Unknown or deleted document with ID {ref}!")
        doc = __bosses[ref]
    if doc is None:
        raise RuntimeError("Document no longer exists (or never existed)!")
    return doc


def _ref_page(page: "Page") -> PageRef:
    return page.docref, page.page_idx


def _deref_page(ref: PageRef) -> "Page":
    docref, idx = ref
    doc = _deref_document(docref)
    return doc.pages[idx]
