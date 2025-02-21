"""
Lazy interface to PDF document outline (PDF 1.7 sect 12.3.3).
"""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, Iterator, Sequence, Tuple, Union

from playa.parser import PDFObject, PSLiteral
from playa.pdftypes import dict_value, ObjRef, LIT, resolve1, num_value
from playa.structure import Element
from playa.utils import decode_text
from playa.worker import (
    DocumentRef,
    PageRef,
    _ref_document,
    _ref_page,
    _deref_document,
    _deref_page,
)

if TYPE_CHECKING:
    from playa.document import Document
    from playa.page import Page

LOG = logging.getLogger(__name__)
DISPLAY_XYZ = LIT("XYZ")
DISPLAY_FIT = LIT("Fit")
DISPLAY_FITH = LIT("FitH")
DISPLAY_FITV = LIT("FitV")
DISPLAY_FITR = LIT("FitR")
DISPLAY_FITB = LIT("FitB")
DISPLAY_FITBH = LIT("FitBH")
DISPLAY_FITBV = LIT("FitBV")


@dataclass
class Destination:
    _pageref: PageRef
    display: PSLiteral
    coords: Tuple[float, ...]

    @property
    def page(self) -> "Page":
        """Containing page for this destination."""
        return _deref_page(self._pageref)

    @classmethod
    def from_outline(cls, outline: "Outline") -> Union["Destination", None]:
        dest = resolve1(outline.props.get("Dest"))
        if dest is None:
            return None
        elif isinstance(dest, bytes):
            return outline.doc.destinations[dest]
        elif isinstance(dest, list):
            return cls.from_list(outline.doc, dest)
        LOG.warning("Unknown destination type: %r", dest)
        return None

    @classmethod
    def from_list(cls, doc: "Document", dest: Sequence) -> "Destination":
        pageobj, display, *args = dest
        pages = doc.pages
        if isinstance(pageobj, int):
            page = pages[pageobj + 1]
        elif isinstance(pageobj, ObjRef):
            page = pages.by_id(pageobj.objid)
        else:
            LOG.warning("Unknown page type: %r", pageobj)
            page = pages[0]
        if not isinstance(display, PSLiteral):
            LOG.warning("Unknown display type: %r", display)
            display = LIT("WTF")
        coords = tuple(num_value(x) for x in args)
        return Destination(_pageref=_ref_page(page), display=display, coords=coords)


@dataclass
class Action:
    _docref: DocumentRef
    props: Dict[str, PDFObject]


class Outline:
    _docref: DocumentRef
    props: Dict[str, PDFObject]

    def __init__(self, doc: "Document") -> None:
        self._docref = _ref_document(doc)
        self.props = dict_value(doc.catalog["Outlines"])

    def __iter__(self) -> Iterator["Outline"]:
        if "First" in self.props and "Last" in self.props:
            ref = self.props["First"]
            while ref is not None:
                if not isinstance(ref, ObjRef):
                    LOG.warning("Not an indirect object reference: %r", ref)
                    break
                out = self._from_ref(ref)
                ref = out.props.get("Next")
                yield out
                if ref is self.props["Last"]:
                    break

    def _from_ref(self, ref: ObjRef) -> "Outline":
        out = Outline.__new__(Outline)
        out._docref = self._docref
        out.props = dict_value(ref)
        return out

    @property
    def doc(self) -> "Document":
        """Get associated document if it exists."""
        return _deref_document(self._docref)

    @property
    def title(self) -> Union[str, None]:
        raw = self.props.get("Title")
        if raw is None:
            return None
        if not isinstance(raw, bytes):
            LOG.warning("Title is not a string: %r", raw)
            return None
        return decode_text(raw)

    @property
    def destination(self) -> Union[Destination, None]:
        return Destination.from_outline(self)

    @property
    def action(self) -> Union[Action, None]:
        action = self.props.get("A")
        if action is None:
            return None
        return Action(self._docref, dict_value(action))

    @property
    def element(self) -> Union[Element, None]:
        """The structure element associated with this outline item, if
        any."""
        el = self.props.get("SE")
        if el is None:
            return None
        return Element.from_dict(self.doc, dict_value(el))

    @property
    def parent(self) -> Union["Outline", None]:
        ref = self.props.get("Parent")
        if ref is None:
            return None
        if not isinstance(ref, ObjRef):
            LOG.warning("Parent is not indirect object reference: %r", ref)
            return None
        return self._from_ref(ref)
