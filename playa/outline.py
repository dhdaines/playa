"""
Lazy interface to PDF document outline (PDF 1.7 sect 12.3.3).
"""

import logging
from dataclasses import dataclass
from typing import (
    TYPE_CHECKING,
    Dict,
    Final,
    Iterable,
    Iterator,
    List,
    Sequence,
    Type,
    Union,
)

from playa.parser import PDFObject, PSLiteral
from playa.pdftypes import (
    LIT,
    ObjRef,
    Point,
    Rect,
    dict_value,
    num_value,
    point_value,
    rect_value,
    resolve1,
)
from playa.structure import Element
from playa.utils import apply_matrix_pt, decode_text, normalize_rect, transform_bbox
from playa.worker import (
    DocumentRef,
    PageRef,
    _deref_page,
    _deref_document,
    _ref_document,
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
ACTION_GOTO = LIT("GoTo")


@dataclass
class Destination:
    """PDF destinations (PDF 1.7 sect 12.3.2)"""

    _pageref: PageRef
    display: Union[PSLiteral, None]
    coords: List[PDFObject]
    ncoords: int = 0

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
        pageobj, display, *coords = dest
        cls = DEST_CLASSES.get(display, cls)
        page = doc.pages[0]
        if isinstance(pageobj, int):
            # Not really sure if this is page number or page index...
            page = doc.pages[pageobj - 1]
        elif isinstance(pageobj, ObjRef):
            try:
                page = doc.pages.by_id(pageobj.objid)
            except KeyError:
                LOG.warning("Invalid page object in destination: %r", pageobj)
        else:
            LOG.warning("Unrecognized page in destination object: %r", pageobj)
        if not isinstance(display, PSLiteral):
            LOG.warning("Unknown display type: %r", display)
            display = None
        return cls(
            _pageref=page.pageref,
            display=display,
            coords=coords,
        )

    @property
    def page(self) -> "Page":
        """The page target of this destination."""
        return _deref_page(self._pageref)

    @property
    def doc(self) -> "Document":
        """The document containing this destination."""
        docref, _ = self._pageref
        return _deref_document(docref)

    @property
    def page_idx(self) -> int:
        return self.page.page_idx

    @property
    def top(self) -> Union[float, None]:
        """Top position for this destination, or None for unchanged."""
        return None

    @property
    def left(self) -> Union[float, None]:
        """Left position for this destination, or None for unchanged."""
        return None

    @property
    def pos(self) -> Point:
        """Position of this destination in device space.

        In the case where a coordinate is None (for "unchanged") it
        will default to the left or top edge of the page.
        """
        return apply_matrix_pt(self.page.ctm, (0, self.page.height))

    @property
    def bbox(self) -> Rect:
        """Rectangle in device space to zoom to for this destination.

        In the case where a coordinate is None (for "unchanged") it
        will default to the edge of the page.
        """
        left, top = self.pos
        right, bottom = apply_matrix_pt(self.page.ctm, (self.page.width, 0))
        return normalize_rect((left, top, right, bottom))

    @property
    def zoom(self) -> Union[float, None]:
        """Zoom factor of this destination, or None for unchanged."""
        return None


@dataclass
class DestinationXYZ(Destination):
    """Destination of type XYZ, with a (left, top) position and a zoom level."""

    ncoords: Final = 3

    @property
    def top(self) -> Union[float, None]:
        """Top position for this destination, or None for unchanged."""
        top = self.coords[1]
        if top is None:
            return None
        _, y = apply_matrix_pt(self.page.ctm, (0, num_value(top)))
        return y

    @property
    def left(self) -> Union[float, None]:
        """Left position for this destination, or None for unchanged."""
        left = self.coords[0]
        if left is None:
            return None
        x, _ = apply_matrix_pt(self.page.ctm, (num_value(left), 0))
        return x

    @property
    def pos(self) -> Point:
        """Position of this destination in device space.

        In the case where a coordinate is None (for "unchanged") it
        will default to the left or top edge of the page.
        """
        left, top = self.coords[0:2]
        # Give them some defaults in default user space
        if left is None:
            left = 0
        if top is None:
            top = self.page.height
        return apply_matrix_pt(self.page.ctm, point_value([left, top]))

    @property
    def zoom(self) -> Union[float, None]:
        """Zoom factor of this destination, or None for unchanged."""
        if not self.coords[2]:  # 0 and None are equivalent
            return None
        return num_value(self.coords[2])


@dataclass
class DestinationFitH(Destination):
    """Destination of type FitH or FitBH, with a top position."""

    ncoords: Final = 1

    @property
    def top(self) -> Union[float, None]:
        """Top position for this destination, or None for unchanged."""
        top = self.coords[0]
        if top is None:
            return None
        _, y = apply_matrix_pt(self.page.ctm, (0, num_value(top)))
        return y

    @property
    def left(self) -> Union[float, None]:
        """Left position for this destination (always None, unchanged)."""
        return None

    @property
    def pos(self) -> Point:
        """Position of this destination in device space.

        In the case where a coordinate is None (for "unchanged") it
        will default to the left or top edge of the page.
        """
        top = self.coords[0]
        left = 0
        if top is None:
            top = self.page.height
        return apply_matrix_pt(self.page.ctm, point_value([left, top]))


@dataclass
class DestinationFitV(Destination):
    """Destination of type FitV or FitBV, with a left position."""

    ncoords: Final = 1

    @property
    def top(self) -> Union[float, None]:
        """Top position for this destination (always None, unchanged)."""
        return None

    @property
    def left(self) -> Union[float, None]:
        """Left position for this destination, or None for unchanged."""
        left = self.coords[0]
        if left is None:
            return None
        x, _ = apply_matrix_pt(self.page.ctm, (num_value(left), self.page.height))
        return x

    @property
    def pos(self) -> Point:
        """Position of this destination in device space.

        In the case where a coordinate is None (for "unchanged") it
        will default to the left or top edge of the page.
        """
        left = self.coords[0]
        top = self.page.height
        if left is None:
            left = 0
        return apply_matrix_pt(self.page.ctm, point_value([left, top]))


@dataclass
class DestinationFitR(Destination):
    """Destination of type FitR, with a bounding box."""

    ncoords: Final = 4

    @property
    def top(self) -> Union[float, None]:
        """Top position for this destination, or None for unchanged."""
        top = self.coords[3]
        if top is None:
            return None
        _, y = self.pos
        return y

    @property
    def left(self) -> Union[float, None]:
        """Left position for this destination, or None for unchanged."""
        left = self.coords[0]
        if left is None:
            return None
        x, _ = self.pos
        return x

    @property
    def pos(self) -> Point:
        """Position of this destination in device space.

        In the case where a coordinate is None (for "unchanged") it
        will default to the left or top edge of the page.
        """
        left, _, _, top = self.coords
        # Give them some defaults in default user space
        if left is None:
            left = 0
        if top is None:
            top = self.page.height
        return apply_matrix_pt(self.page.ctm, point_value([left, top]))

    @property
    def bbox(self) -> Rect:
        """Rectangle in device space to zoom to for this destination.

        In the case where a coordinate is None (for "unchanged") it
        will default to the edge of the page.
        """
        left, bottom, right, top = self.coords
        if left is None:
            left = 0
        if bottom is None:
            bottom = 0
        if right is None:
            right = self.page.width
        if top is None:
            top = self.page.height
        return transform_bbox(self.doc.ctm, rect_value([left, bottom, right, top]))


DEST_CLASSES: Dict[PSLiteral, Type[Destination]] = {
    DISPLAY_XYZ: DestinationXYZ,
    DISPLAY_FIT: Destination,
    DISPLAY_FITH: DestinationFitH,
    DISPLAY_FITV: DestinationFitV,
    DISPLAY_FITR: DestinationFitR,
    DISPLAY_FITB: Destination,
    DISPLAY_FITBH: DestinationFitH,
    DISPLAY_FITBV: DestinationFitV,
}


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
        dest = resolve1(self.props.get("D"))
        if dest is None:
            return None
        elif not isinstance(dest, (PSLiteral, bytes, list)):
            LOG.warning("Unrecognized destination: %r", dest)
            return None
        return Destination.from_dest(self.doc, dest)


class Tree(Iterable["Item"]):
    """PDF document outline (PDF 1.7 sect 12.3.3)"""

    _docref: DocumentRef
    props: Dict[str, PDFObject]

    def __init__(self, doc: "Document") -> None:
        self._docref = _ref_document(doc)
        self.props = dict_value(doc.catalog["Outlines"])

    def __iter__(self) -> Iterator["Item"]:
        if "First" in self.props and "Last" in self.props:
            ref = self.props["First"]
            while ref is not None:
                if not isinstance(ref, ObjRef):
                    LOG.warning("Not an indirect object reference: %r", ref)
                    break
                out = Item(_docref=self._docref, props=dict_value(ref))
                ref = out.props.get("Next")
                yield out
                if ref is self.props["Last"]:
                    break

    @property
    def doc(self) -> "Document":
        """Get associated document if it exists."""
        return _deref_document(self._docref)


@dataclass
class Item(Iterable["Item"]):
    """PDF document outline item (PDF 1.7 sect 12.3.3)"""

    _docref: DocumentRef
    props: Dict[str, PDFObject]

    def __iter__(self) -> Iterator["Item"]:
        if "First" in self.props and "Last" in self.props:
            ref = self.props["First"]
            while ref is not None:
                if not isinstance(ref, ObjRef):
                    LOG.warning("Not an indirect object reference: %r", ref)
                    break
                out = Item(_docref=self._docref, props=dict_value(ref))
                ref = out.props.get("Next")
                yield out
                if ref is self.props["Last"]:
                    break

    @property
    def doc(self) -> "Document":
        """Get associated document if it exists."""
        return _deref_document(self._docref)

    @property
    def title(self) -> str:
        raw = resolve1(self.props.get("Title"))
        if raw is None:
            raise ValueError(f"Outline item has no title: {self.props!r}")
        if not isinstance(raw, bytes):
            raise ValueError(f"Outline item title is not a string: {raw!r}")
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
                if isinstance(dest, (PSLiteral, bytes, list)):
                    return Destination.from_dest(self.doc, dest)
            except KeyError:
                LOG.warning("Unknown named destination: %r", dest)
        # Fall through to try an Action instead
        action = self.action
        if action is None or action.type is not ACTION_GOTO:
            return None
        return action.destination

    @property
    def action(self) -> Union[Action, None]:
        try:
            return Action(self._docref, dict_value(self.props["A"]))
        except (KeyError, TypeError):
            return None

    @property
    def element(self) -> Union[Element, None]:
        """The structure element associated with this outline item, if
        any.

        Returns:
            structure element, if one exists.
        """
        try:
            return Element.from_dict(self.doc, dict_value(self.props["SE"]))
        except (KeyError, TypeError):
            return None

    @property
    def parent(self) -> Union["Item", "Tree"]:
        ref = self.props["Parent"]
        if not isinstance(ref, ObjRef):
            raise ValueError(f"Parent is not indirect object reference: {ref!r}")
        props = dict_value(ref)
        if "Parent" not in props:
            tree = self.doc.outline
            if tree is None:
                raise ValueError("Document apparently has no outline?!?")
        return Item(self._docref, props)
