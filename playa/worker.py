"""Worker subprocess related functions and data."""

import weakref
from typing import Union, TYPE_CHECKING

if TYPE_CHECKING:
    from playa.document import Document
    from playa.page import Page

# Type signature of document reference
DocumentRef = Union[weakref.ReferenceType["Document"], str]
# Type signature of page reference
PageRef = Union[weakref.ReferenceType["Page"], int]

# A global PDF object used in worker processes
__pdf: Union["Document", None] = None
# Flag used to signal that we should look at the global document
GLOBAL_DOC = "[citation needed]"


def in_worker() -> bool:
    """Are we currently in a worker process?"""
    return __pdf is not None


def _set_document(doc: "Document") -> None:
    global __pdf
    __pdf = doc


def _get_document() -> Union["Document", None]:
    global __pdf
    return __pdf


def _ref_document(doc: "Document") -> DocumentRef:
    return weakref.ref(doc) if __pdf is None else GLOBAL_DOC


def _deref_document(ref: DocumentRef) -> "Document":
    doc = __pdf
    if isinstance(ref, weakref.ReferenceType):
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
            raise RuntimeError("Page no longer exists!")
        return page
