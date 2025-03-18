"""Schemas for various metadata objects.

This module contains schemas (as TypedDict) for metadata from various
PLAYA objects.

"""

from typing import Any, Dict, List, Set, Tuple, Union

try:
    # We only absolutely need this when using Pydantic TypeAdapter
    from typing_extensions import TypedDict
except ImportError:
    from typing import TypedDict

from playa.data.asobj import asobj
from playa.document import Document as _Document, Destinations as _Destinations
from playa.font import Font as _Font
from playa.page import Page as _Page, Annotation as _Annotation
from playa.document import DeviceSpace
from playa.outline import Outline as _Outline, Destination as _Destination
from playa.parser import IndirectObject as _IndirectObject
from playa.pdftypes import ContentStream as _ContentStream, resolve1, ObjRef
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

    page_idx: int
    """0-based page number."""
    page_label: Union[str, None]
    """Page label (could be roman numerals, letters, etc)."""
    page_id: int
    """Indirect object ID."""
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


class Annotation(TypedDict, total=False):
    subtype: str
    """Type of annotation."""
    rect: Rect
    """Annotation rectangle in default user space."""
    contents: str
    """Text contents."""
    name: str
    """Annotation name, uniquely identifying this annotation."""
    mtime: str
    """String describing date and time when annotation was most recently
    modified."""


class StreamObject(TypedDict, total=False):
    stream_id: int
    """Indirect object ID."""
    genno: int
    """Generation number."""
    length: int
    """Length of raw stream data."""
    filters: List[str]
    """List of filters."""
    params: List[dict]
    """Filter parameters."""


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
    name: str
    """Font name."""
    type: str
    """Font type (Type1, Type0, TrueType, Type3, etc)."""
    vertical: bool
    """Uses vertical writing mode."""
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


RESOURCE_DICTS = {
    "ext_gstates": "ExtGState",
    "color_spaces": "ColorSpace",
    "patterns": "Pattern",
    "shadings": "Shading",
    "properties": "Properties",
}


class Resources(TypedDict, total=False):
    ext_gstates: Dict[str, dict]
    """Extended graphic state dictionaries."""
    color_spaces: Dict[str, Any]
    """Color space descriptors."""
    patterns: Dict[str, Any]
    """Pattern objects."""
    shadings: Dict[str, dict]
    """Shading dictionaries."""
    xobjects: Dict[str, "StreamObject"]
    """XObject streams."""
    fonts: Dict[str, "Font"]
    """Font dictionaries."""
    procsets: List[str]
    """Procedure set names."""
    properties: Dict[str, dict]
    """property dictionaires."""


def resources_from_page(page: _Page) -> Resources:
    res = Resources()
    for attr in "ext_gstates", "color_spaces", "patterns", "shadings", "properties":
        key = RESOURCE_DICTS[attr]
        d = resolve1(page.resources.get(key))
        if d and isinstance(d, dict):
            res[attr] = {k: asobj(resolve1(v)) for k, v in d.items()}
    d = resolve1(page.resources.get("XObject"))
    if d and isinstance(d, dict):
        res["xobjects"] = {k: asobj(resolve1(v)) for k, v in d.items()}
    p = resolve1(page.resources.get("ProcSet"))
    if p and isinstance(p, list):
        res["procsets"] = asobj(p)
    d = resolve1(page.resources.get("Font"))
    if d and isinstance(d, dict):
        fonts = {}
        for k, v in d.items():
            if not isinstance(v, ObjRef):
                continue
            spec = resolve1(v)
            if not isinstance(spec, dict):
                continue
            font = page.doc.get_font(v.objid, spec)
            fonts[k] = asobj(font)
        if fonts:
            res["fonts"] = fonts
    return res


@asobj.register
def asobj_page(page: _Page) -> Page:
    return Page(
        page_idx=page.page_idx,
        page_label=page.label,
        page_id=page.pageid,
        mediabox=page.mediabox,
        cropbox=page.cropbox,
        rotate=page.rotate,
        resources=resources_from_page(page),
        annotations=[asobj(annot) for annot in page.annotations],
        contents=[asobj(stream) for stream in page.streams],
    )


@asobj.register
def asobj_annotation(obj: _Annotation) -> Annotation:
    annot = Annotation(subtype=obj.subtype, rect=obj.rect)
    for attr in "contents", "name", "mtime":
        val = getattr(obj, attr)
        if val is not None:
            annot[attr] = asobj(val)
    return annot


@asobj.register
def asobj_font(obj: _Font) -> Font:
    font = Font(
        name=obj.fontname,
        type=obj.__class__.__name__.replace("Font", ""),
        vertical=obj.vertical,
    )
    for attr in (
        "ascent",
        "descent",
        "italic_angle",
        "default_width",
        "leading",
        "matrix",
    ):
        val = getattr(obj, attr, None)
        if val:
            font[attr] = val
    if obj.bbox != (0, 0, 0, 0):
        font["bbox"] = obj.bbox
    return font


@asobj.register
def asobj_stream(obj: _ContentStream) -> StreamObject:
    # These really cannot be None!
    assert obj.objid is not None
    assert obj.genno is not None
    length = resolve1(obj.attrs["Length"])
    cs = StreamObject(stream_id=obj.objid, genno=obj.genno, length=length)
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
