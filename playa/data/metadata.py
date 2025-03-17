"""Schemas for various metadata objects.

This module contains schemas (as TypedDict) for metadata from various
PLAYA objects.

"""

from typing import Dict, List, Set, Tuple, Union

try:
    # We only absolutely need this when using Pydantic TypeAdapter
    from typing_extensions import TypedDict
except ImportError:
    from typing import TypedDict

from playa.data.asobj import asobj
from playa.document import Document as _Document, Destinations as _Destinations
from playa.page import Page as _Page, Annotation as _Annotation
from playa.document import DeviceSpace
from playa.outline import Outline as _Outline, Destination as _Destination
from playa.parser import IndirectObject as _IndirectObject
from playa.pdftypes import ContentStream as _ContentStream
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
    outline: "Outline"
    """Outline hierarchy for this document."""
    destinations: Dict[str, "Destination"]
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


class Outline(TypedDict, total=False):
    """Outline hierarchy for a PDF document."""

    title: str
    """Title of this outline entry."""
    destination: "Destination"
    """Destination (or target of GoTo action)."""
    element: "StructElement"
    """Structure element asociated with this entry."""
    children: List["Outline"]
    """Children of this entry."""


class Destination(TypedDict, total=False):
    """Destination for an outline entry or annotation."""
    page_idx: int
    """Zero-based index of destination page."""
    display: str
    """How to display the destination on that page."""
    coords: List[Union[float, None]]
    """List of coordinates (meaning depends on display)."""


class StructElement(TypedDict, total=False):
    """Node in logical structure tree."""

    type: str
    """Type of structure element (or "StructTreeRoot" for root)"""
    children: List["StructElement"]
    """Children of this node."""


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
    annotations: List["Annotation"]
    """Page annotations."""
    contents: List["StreamObject"]
    """Metadata for content streams."""


class Resources(TypedDict, total=False):
    pass


class Annotation(TypedDict, total=False):
    subtype: str
    """Type of annotation."""
    rect: Rect
    """Annotation rectangle in default user space."""
    contents: str
    """Text contents."""
    attrs: Dict
    """Other attributes."""


class StreamObject(TypedDict, total=False):
    objid: int
    """Indirect object ID."""
    genno: int
    """Generation number."""
    filters: List[str]
    """List of filters."""
    params: List[dict]
    """Filter parameters."""
    attrs: dict
    """Other attributes."""


class IndirectObject(TypedDict, total=False):
    objid: int
    """Indirect object ID."""
    genno: int
    """Generation number."""
    type: str
    """Name of Python type to which this object was converted."""
    obj: Union[float, int, str, bool, dict, list]
    """Object metadata (for streams) or data (otherwise)."""


class Font(TypedDict, total=False):
    """Font"""

    name: str
    """Font name."""
    type: str
    """Font type (Type1, Type0, TrueType, Type3, etc)."""
    vertical: bool
    """Uses vertical writing mode."""
    multibyte: bool
    """Uses multi-byte characters (actually this is always true for CID fonts)."""
    ascent: float
    """Ascent in glyph space units."""
    descent: float
    """Descent in glyph space units."""
    italic_angle: float
    """Italic angle."""
    default_width: float
    """Default character width in glyph space units."""
    leading: float
    """Leading in glyph space units."""
    bbox: Rect
    """Bounding box in glyph space units."""
    matrix: Matrix
    """Matrix mapping glyph space to text space (Type3 fonts only)."""


@asobj.register
def asobj_page(page: _Page) -> Page:
    return Page(
        objid=page.pageid,
        index=page.page_idx,
        label=page.label,
        mediabox=page.mediabox,
        cropbox=page.cropbox,
        rotate=page.rotate,
        resources=asobj(page.resources),
        annotations=[asobj(annot) for annot in page.annotations],
        contents=[asobj(stream) for stream in page.streams],
    )


@asobj.register
def asobj_annotation(obj: _Annotation) -> Annotation:
    annot = Annotation(subtype=obj.subtype,
                       rect=obj.rect)
    for attr in "contents", "name", "mtime":
        val = getattr(obj, attr)
        if val is not None:
            annot[attr] = asobj(val)
    return annot


@asobj.register
def asobj_stream(obj: _ContentStream) -> StreamObject:
    # These really cannot be None!
    assert obj.objid is not None
    assert obj.genno is not None
    cs = StreamObject(objid=obj.objid, genno=obj.genno, attrs=asobj(obj.attrs))
    fps = obj.get_filters()
    if fps:
        filters, params = zip(*fps)
        if any(filters):
            cs["filters"] = asobj(filters)
        if any(params):
            cs["params"] = asobj(params)
    return cs


@asobj.register
def asobj_obj(obj: _IndirectObject) -> IndirectObject:
    return IndirectObject(
        objid=obj.objid,
        genno=obj.genno,
        type=type(obj.obj).__name__,
        obj=asobj(obj.obj),
    )


@asobj.register
def asobj_outline(obj: _Outline) -> Outline:
    out = Outline()
    for attr in "title", "destination", "element":
        val = getattr(obj, attr)
        if val is not None:
            out[attr] = asobj(val)
    children = list(obj)
    if children:
        out["children"] = asobj(children)
    return out


@asobj.register
def asobj_destinations(obj: _Destinations) -> Dict[str, Destination]:
    return {name: asobj(dest) for name, dest in obj.items()}


@asobj.register
def asobj_destination(obj: _Destination) -> Destination:
    dest = Destination()
    if obj.page_idx is not None:
        dest["page_idx"] = obj.page_idx
    if obj.display is not None:
        dest["display"] = asobj(obj.display)
    if obj.coords:
        dest["coords"] = asobj(obj.coords)
    return dest


@asobj.register
def asobj_document(pdf: _Document, exclude: Set[str] = set()) -> Document:
    doc = Document(
        pdf_version=pdf.pdf_version,
        is_printable=pdf.is_printable,
        is_modifiable=pdf.is_modifiable,
        is_extractable=pdf.is_extractable,
    )
    if pdf.encryption is not None:
        ids, encrypt = pdf.encryption
        a, b = ids
        doc["encryption"] = Encryption(ids=asobj(ids), encrypt=asobj(encrypt))
    if "pages" not in exclude:
        doc["pages"] = [asobj(page) for page in pdf.pages]
    if "objects" not in exclude:
        doc["objects"] = [asobj(obj) for obj in pdf.objects]
    if "outline" not in exclude:
        doc["outline"] = asobj(pdf.outline)
        doc["destinations"] = asobj(pdf.destinations)
    if "structure" not in exclude:
        doc["structure"] = asobj(pdf.structure)

    return doc
