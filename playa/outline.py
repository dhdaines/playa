"""
Lazy interface to PDF document outline (PDF 1.7 sect 12.3.3).
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, Iterator, Union

from playa.parser import PDFObject, PSLiteral
from playa.pdftypes import dict_value, ObjRef, LIT
from playa.structure import Element
from playa.utils import decode_text
from playa.worker import (
    DocumentRef,
    PageRef,
    _ref_document,
    _deref_page,
)

if TYPE_CHECKING:
    from playa.document import Document
    from playa.page import Page

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
    left: Union[float, None] = None
    top: Union[float, None] = None
    right: Union[float, None] = None
    bottom: Union[float, None] = None
    zoom: Union[float, None] = None

    @property
    def page(self) -> "Page":
        """Containing page for this destination."""
        return _deref_page(self._pageref)

    @classmethod
    def from_outline(cls, doc: "Document", obj: PDFObject) -> "Destination":
        pass


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
    def title(self) -> Union[str, None]:
        raw = self.props.get("Title")
        if raw is None:
            return None
        return decode_text(raw)

    @property
    def destination(self) -> Union[Destination, None]:
        dest = self.props.get("Dest")
        if dest is None:
            return None
        return Destination.from_outline(self.doc, dest)

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
        return self._from_ref(ref)
