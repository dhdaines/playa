"""Worker subprocess related functions and data."""

import weakref
from pathlib import Path
from typing import Union, TYPE_CHECKING

if TYPE_CHECKING:
    from playa.document import Document, DeviceSpace
    from playa.page import Page

# Type signature of document reference
DocumentRef = Union[weakref.ReferenceType["Document"], int]
# Type signature of page reference
PageRef = Union[weakref.ReferenceType["Page"], int]

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


def _add_boss(doc: "Document") -> None:
    """Call this in the parent process."""
    global __bosses
    assert not in_worker()
    __bosses[id(doc)] = doc


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
        return weakref.ref(doc)


def _deref_document(ref: DocumentRef) -> "Document":
    if in_worker():
        return __pdf
    if isinstance(ref, int):
        if ref not in __bosses:
            raise RuntimeError(f"Unknown or deleted document with ID {ref}!")
        return __bosses[ref]
    else:
        doc = ref()
        if doc is None:
            raise RuntimeError("Document no longer exists (or never existed)!")
        return doc


def _ref_page(page: "Page") -> PageRef:
    return weakref.ref(page) if __pdf is None else page.page_idx


def _deref_page(ref: PageRef) -> "Page":
    if isinstance(ref, int):
        if __pdf is None:
            raise RuntimeError("Not in a worker process, cannot retrieve document!")
        return __pdf.pages[ref]
    else:
        page = ref()
        if page is None:
            raise RuntimeError(f"Page {ref} no longer exists (or never existed)!")
        return page
