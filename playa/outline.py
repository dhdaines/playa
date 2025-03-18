"""
Lazy interface to PDF document outline (PDF 1.7 sect 12.3.3).
"""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, Iterator, Sequence, Tuple, Union

from playa.parser import PDFObject, PSLiteral
from playa.pdftypes import LIT, ObjRef, dict_value, resolve1
from playa.structure import Element
from playa.utils import decode_text
from playa.worker import (
    DocumentRef,
    _deref_document,
    _ref_document,
)

if TYPE_CHECKING:
    from playa.document import Document

LOG = logging.getLogger(__name__)
DISPLAY_XYZ = LIT("XYZ")
DISPLAY_FIT = LIT("Fit")
DISPLAY_FITH = LIT("FitH")
DISPLAY_FITV = LIT("FitV")
DISPLAY_FITR = LIT("FitR")
DISPLAY_FITB = LIT("FitB")
DISPLAY_FITBH = LIT("FitBH")
DISPLAY_FITBV = LIT("FitBV")
ACTION_GOTO = LIT("GoTo")


@dataclass
class Destination:
    """PDF destinations (PDF 1.7 sect 12.3.2)"""

    _docref: DocumentRef
    page_idx: Union[int, None]
    display: Union[PSLiteral, None]
    coords: Tuple[Union[float, None], ...]

    @classmethod
    def from_dest(
        cls, doc: "Document", dest: Union[PSLiteral, bytes, list]
    ) -> "Destination":
        if isinstance(dest, (bytes, PSLiteral)):
            return doc.destinations[dest]
        elif isinstance(dest, list):
            return cls.from_list(doc, dest)
        else:
            raise TypeError("Unknown destination type: %r", dest)

    @classmethod
    def from_list(cls, doc: "Document", dest: Sequence) -> "Destination":
        pageobj, display, *args = dest
        page_idx: Union[int, None] = None
        if isinstance(pageobj, int):
            # Not really sure if this is page number or page index...
            page_idx = pageobj - 1
        elif isinstance(pageobj, ObjRef):
            try:
                page_idx = doc.pages.by_id(pageobj.objid).page_idx
            except KeyError:
                LOG.warning("Invalid page object in destination: %r", pageobj)
        else:
            LOG.warning("Unrecognized page in destination object: %r", pageobj)
        if not isinstance(display, PSLiteral):
            LOG.warning("Unknown display type: %r", display)
            display = None
        coords = tuple(x if isinstance(x, (int, float)) else None for x in args)
        return Destination(
            _docref=_ref_document(doc),
            page_idx=page_idx,
            display=display,
            coords=coords,
        )


@dataclass
class Action:
    """PDF actions (PDF 1.7 sect 12.6)"""

    _docref: DocumentRef
    props: Dict[str, PDFObject]

    @property
    def type(self) -> PSLiteral:
        assert isinstance(self.props["S"], PSLiteral)
        return self.props["S"]

    @property
    def doc(self) -> "Document":
        """Get associated document if it exists."""
        return _deref_document(self._docref)

    @property
    def destination(self) -> Union[Destination, None]:
        """Destination of this action, if any."""
        if "D" not in self.props:
            return None
        return Destination.from_dest(self.doc, resolve1(self.props["D"]))


class Outline:
    """PDF document outline (PDF 1.7 sect 12.3.3)"""

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
        raw = resolve1(self.props.get("Title"))
        if raw is None:
            return None
        if not isinstance(raw, bytes):
            LOG.warning("Title is not a string: %r", raw)
            return None
        return decode_text(raw)

    @property
    def destination(self) -> Union[Destination, None]:
        """Destination for this outline item.

        Note: Special case of `GoTo` actions.
            Since internal `GoTo` actions (PDF 1.7 sect 12.6.4.2) in
            outlines and links are entirely equivalent to
            destinations, if one exists, it will be returned here as
            well.

        Returns:
            destination, if one exists.
        """
        dest = resolve1(self.props.get("Dest"))
        if dest is not None:
            try:
                return Destination.from_dest(self.doc, dest)
            except KeyError:
                return None
        action = self.action
        if action is None or action.type is not ACTION_GOTO:
            return None
        return action.destination

    @property
    def action(self) -> Union[Action, None]:
        action = resolve1(self.props.get("A"))
        if action is None:
            return None
        return Action(self._docref, dict_value(action))

    @property
    def element(self) -> Union[Element, None]:
        """The structure element associated with this outline item, if
        any.

        Returns:
            structure element, if one exists.
        """
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
