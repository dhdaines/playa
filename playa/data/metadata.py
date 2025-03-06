"""Schemas for various metadata objects.

This module contains schemas (as TypedDict) for metadata from various
PLAYA objects.

"""

from typing import Dict, List, Tuple, TypedDict, Union

from playa.document import DeviceSpace
from playa.utils import Rect, Matrix


class Document(TypedDict, total=False):
    """Metadata for a PDF document."""

    pdf_version: str
    """Version of the PDF standard this document implements."""
    is_printable: bool
    """Should the user be allowed to print?"""
    is_modifiable: bool
    """Should the user be allowed to modify?"""
    is_extractable: bool
    """Should the user be allowed to extract text?"""
    space: DeviceSpace
    """Device space for this document."""
    encryption: "Encryption"
    """Encryption information for this document."""
    outlines: "Outlines"
    """Outline hierarchy for this document."""
    destinations: Dict[str, "Dest"]
    """Named destinations for this document."""
    structure: "StructTree"
    """Logical structure for this document.."""
    pages: List["Page"]
    """Pages in this document."""
    objects: List["IndirectObject"]
    """Indirect objects in this document."""


class Encryption(TypedDict, total=False):
    """Encryption information."""

    ids: Tuple[str, str]
    """ID values for encryption."""
    encrypt: dict
    """Encryption properties."""


class Outlines(TypedDict, total=False):
    """Outline hierarchy for a PDF document."""

    title: str
    """Title of this outline entry."""
    destination: "Dest"
    """Destination (or target of GoTo action)."""
    element: "StructElement"
    """Structure element asociated with this entry."""
    children: List["Outlines"]
    """Children of this entry."""


class Dest(TypedDict, total=False):
    """Destination for an outline entry or annotation."""


class StructElement(TypedDict, total=False):
    """Element or root node of logical structure tree.

    Contrary to the PDF standard, we create a root node to make
    navigation over the tree easier.
    """

    type: str
    """Type of structure element (or "StructTreeRoot" for root)"""


class StructTree(TypedDict, total=False):
    """Logical structure tree for a PDF document."""

    root: StructElement
    """Root node of the tree."""


class Page(TypedDict, total=False):
    """Metadata for a PDF page."""

    objid: int
    """Indirect object ID."""
    index: int
    """0-based page number."""
    label: Union[str, None]
    """Page label (could be roman numerals, letters, etc)."""
    mediabox: Rect
    """Extent of physical page, in base units (1/72 inch)."""
    cropbox: Rect
    """Extent of visible area, in base units (1/72 inch)."""
    rotate: int
    """Page rotation in degrees."""
    resources: "Resources"
    """Page resources."""
    annotations: "Annotations"
    """Page annotations."""
    contents: List["ContentStream"]
    """Metadata for content streams."""


class Resources(TypedDict, total=False):
    pass


class Annotations(TypedDict, total=False):
    pass


class ContentStream(TypedDict, total=False):
    pass


class IndirectObject(TypedDict, total=False):
    objid: int
    """Indirect object ID."""
    genno: int
    """Generation number."""
    type: str
    """Name of Python type to which this object was converted."""
    obj: Union[float, int, str, bool, bytes, dict, list]
    """Object metadata (or data, for simple objects)."""


class Font(TypedDict, total=False):
    """Font"""

    name: str
    """Font name."""
    type: str
    """Font type (Type1, Type0, TrueType, Type3, etc)."""
    vertical: bool
    multibyte: bool
    ascent: float
    descent: float
    italic_angle: float
    default_width: float
    leading: float
    bbox: Rect
    matrix: Matrix
