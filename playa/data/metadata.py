"""Schemas for various metadata objects.

This module contains schemas (as TypedDict) for metadata from various
PLAYA objects.

"""

import logging
from typing import Any, Dict, List, Set, Tuple, Union

try:
    # We only absolutely need this when using Pydantic TypeAdapter
    from typing_extensions import TypedDict
except ImportError:
    from typing import TypedDict

from playa.data.asobj import asobj
from playa.document import Destinations as _Destinations
from playa.document import Document as _Document
from playa.font import Font as _Font
from playa.fontmetrics import FONT_METRICS
from playa.outline import Destination as _Destination
from playa.outline import Outline as _Outline
from playa.page import Annotation as _Annotation
from playa.page import Page as _Page
from playa.parser import IndirectObject as _IndirectObject
from playa.pdftypes import ContentStream as _ContentStream
from playa.pdftypes import resolve1, stream_value
from playa.structure import Tree as _Tree, Element as _Element
from playa.structure import ContentItem as _StructContentItem
from playa.structure import ContentObject as _StructContentObject
from playa.utils import Matrix, Rect, decode_text

log = logging.getLogger(__name__)


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


class StructContentObject(TypedDict, total=False):
    page_idx: int
    """Page index of content object."""
    props: dict
    """Properties of content object."""


class StructContentItem(TypedDict, total=False):
    page_idx: int
    """Page index of content object."""
    mcid: int
    """Marked content section ID."""
    stream: "StreamObject"
    """Content stream, if any."""


class StructElement(TypedDict, total=False):
    """Node in logical structure tree."""

    type: str
    """Type of structure element (or "StructTreeRoot" for root)."""
    page_idx: int
    """Page on which this structure element's content begins."""
    title: str
    """Title of structure element."""
    language: str
    """Language of structure element."""
    alternate_description: str
    """Alternate description."""
    abbreviation_expansion: str
    """Abbreviation expansion."""
    actual_text: str
    """Unicode text content."""
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


class XObject(TypedDict, total=False):
    subtype: str
    """Type of XObject."""
    xobject_id: int
    """Indirect object ID."""
    genno: int
    """Generation number."""
    length: int
    """Length of raw stream data."""
    filters: List[str]
    """List of filters."""
    params: List[dict]
    """Filter parameters."""
    resources: "Resources"
    """Resources specific to this XObject, if any."""


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
    cap_height: float
    """Top of capital letters, in glyph space units."""
    xheight: float
    """Top of flat nonascending lowercase letters, in glyph space units."""
    stem_v: float
    """Thickness of dominant vertical stems."""
    stem_h: float
    """Thickness of dominant horizontal stems."""
    avg_width: float
    """Average width of glyphs in glyph space units."""
    max_width: float
    """Maximum width of glyphs in glyph space units."""
    stretch: str
    """Font stretch value (e.g. Condensed, Expanded)."""
    weight: float
    """Numeric weight value (100, 200, 300... 900)"""
    flags: List[str]
    """Set of flags (e.g. FixedPitch, Script, etc) for this font."""
    bbox: Rect
    """Bounding box in glyph space units."""
    matrix: Matrix
    """Matrix mapping glyph space to text space (Type3 fonts only)."""
    cidfont: "Font"
    """Descendant CIDFont (Type0 fonts only)."""


FONT_FLAGS = {
    "FixedPitch": 1,
    "Serif": 2,
    "Symbolic": 3,
    "Script": 4,
    "Nonsymbolic": 6,
    "Italic": 7,
    "AllCap": 17,
    "SmallCap": 18,
    "ForceBold": 19,
}


def flags_to_list(flags: int) -> List[str]:
    return [k for k, v in FONT_FLAGS.items() if flags & (1 << v)]


FONT_ATTRS = {
    "ascent": "Ascent",
    "descent": "Descent",
    "italic_angle": "ItalicAngle",
    "default_width": "MissingWidth",
    "leading": "Leading",
    "cap_height": "CapHeight",
    "xheight": "XHeight",
    "stem_v": "StemV",
    "stem_h": "StemH",
    "avg_width": "AvgWidth",
    "max_width": "MaxWidth",
    "stretch": "FontStretch",
    "weight": "FontWeight",
}


def font_from_spec(spec: Dict[str, Any]) -> Font:
    basefont = asobj(resolve1(spec.get("BaseFont")))
    if basefont is None:
        basefont = asobj(resolve1(spec.get("Name")))
    font = Font(
        name=basefont,
        type=asobj(resolve1(spec.get("Subtype"))),
    )
    if basefont in FONT_METRICS:
        desc, _ = FONT_METRICS[basefont]
    else:
        desc = resolve1(spec.get("FontDescriptor"))
    if desc is not None:
        for attr in (
            "ascent",
            "descent",
            "italic_angle",
            "default_width",
            "leading",
            "cap_height",
            "xheight",
            "stem_v",
            "stem_h",
            "avg_width",
            "max_width",
            "stretch",
            "weight",
        ):
            key = FONT_ATTRS[attr]
            val = desc.get(key)
            if val:
                font[attr] = asobj(val)
        flags = resolve1(desc.get("Flags", 0))
        if flags:
            flaglist = flags_to_list(flags)
            if flaglist:
                font["flags"] = flaglist
    sub = resolve1(spec.get("DescendantFonts"))
    if sub and isinstance(sub, list) and sub[0] is not None:
        font["cidfont"] = font_from_spec(resolve1(sub[0]))
    return font


class Resources(TypedDict, total=False):
    ext_gstates: Dict[str, dict]
    """Extended graphic state dictionaries."""
    color_spaces: Dict[str, Any]
    """Color space descriptors."""
    patterns: Dict[str, Any]
    """Pattern objects."""
    shadings: Dict[str, dict]
    """Shading dictionaries."""
    xobjects: Dict[str, "XObject"]
    """XObject streams."""
    fonts: Dict[str, Font]
    """Font dictionaries."""
    procsets: List[str]
    """Procedure set names."""
    properties: Dict[str, dict]
    """property dictionaires."""


def xobject_from_stream(
    obj: _ContentStream, seen: Union[Set[int], None] = None
) -> XObject:
    if seen is None:
        seen = set()
    stream = stream_metadata(obj)
    seen.add(stream["stream_id"])
    xobj = XObject(
        xobject_id=stream["stream_id"],
        genno=stream["genno"],
        length=stream["length"],
        subtype=asobj(obj.attrs["Subtype"]),
    )
    if "filters" in stream:
        xobj["filters"] = stream["filters"]
    if "params" in stream:
        xobj["params"] = stream["params"]
    resources = resolve1(obj.attrs.get("Resources"))
    if resources:
        xobj["resources"] = resources_from_dict(resources, seen)
    return xobj


RESOURCE_DICTS = {
    "ext_gstates": "ExtGState",
    "color_spaces": "ColorSpace",
    "patterns": "Pattern",
    "shadings": "Shading",
    "properties": "Properties",
}


def resources_from_dict(
    resources: Dict[str, Any], seen: Union[Set[int], None] = None
) -> Resources:
    if seen is None:
        seen = set()
    res = Resources()
    for attr in "ext_gstates", "color_spaces", "patterns", "shadings", "properties":
        key = RESOURCE_DICTS[attr]
        d = resolve1(resources.get(key))
        if d and isinstance(d, dict):
            res[attr] = {k: asobj(resolve1(v)) for k, v in d.items()}
    d = resolve1(resources.get("XObject"))
    if d and isinstance(d, dict):
        xobjects = {}
        for k, v in d.items():
            try:
                stream = stream_value(v)
                # Use a reference if we've already seen it
                if stream.objid in seen:
                    xobjects[k] = asobj(v)
                    continue
                if stream.objid is not None:
                    seen.add(stream.objid)
                xobjects[k] = xobject_from_stream(stream, seen)
            except Exception as e:
                log.warning("Failed to get XObject %s: %s", k, e)
        if xobjects:
            res["xobjects"] = xobjects
    p = resolve1(resources.get("ProcSet"))
    if p and isinstance(p, list):
        res["procsets"] = asobj(p)
    d = resolve1(resources.get("Font"))
    if d and isinstance(d, dict):
        fonts = {}
        for k, v in d.items():
            spec = resolve1(v)
            if not isinstance(spec, dict):
                log.warning("Invalid font specification: %r", spec)
            else:
                fonts[k] = font_from_spec(spec)
        if fonts:
            res["fonts"] = fonts
    return res


def stream_metadata(obj: _ContentStream) -> StreamObject:
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
def asobj_page(obj: _Page) -> Page:
    page = Page(
        page_idx=obj.page_idx,
        page_label=obj.label,
        page_id=obj.pageid,
        mediabox=obj.mediabox,
        cropbox=obj.cropbox,
        rotate=obj.rotate,
        resources=resources_from_dict(obj.resources),
        annotations=[asobj(annot) for annot in obj.annotations],
    )
    contents = []
    for stream in obj.streams:
        try:
            contents.append(stream_metadata(stream))
        except Exception as e:
            log.warning("Failed to get stream metadata from %r: %s", stream, e)
    if contents:
        page["contents"] = contents
    return page


@asobj.register
def asobj_annotation(obj: _Annotation) -> Annotation:
    annot = Annotation(subtype=obj.subtype, rect=obj.rect)
    for attr in "contents", "name", "mtime":
        val = getattr(obj, attr)
        if val is not None:
            annot[attr] = asobj(val)
    return annot


# Note this is not actually used for font resources, since for the
# moment the Font class we inherited from pdfminer.six lacks various
# metadata.  It's here anyway in case you call asobj() on a Font.
@asobj.register
def asobj_font(obj: _Font) -> Font:
    font_type = obj.__class__.__name__
    if font_type != "CIDFont":
        font_type = font_type.replace("Font", "")
    font = Font(
        name=obj.fontname,
        type=font_type,
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
            font[attr] = asobj(val)
    if obj.bbox != (0, 0, 0, 0):
        font["bbox"] = obj.bbox
    return font


@asobj.register
def asobj_obj(obj: _IndirectObject) -> IndirectObject:
    return IndirectObject(
        objid=obj.objid,
        genno=obj.genno,
        type=type(obj.obj).__name__,
        obj=asobj(obj.obj),
    )


@asobj.register
def asobj_stream(obj: _ContentStream) -> Dict:
    meta = asobj(obj.attrs)
    meta["stream_id"] = obj.objid
    return meta


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
def asobj_content_item(obj: _StructContentItem) -> StructContentItem:
    item = StructContentItem(mcid=obj.mcid)
    page = obj.page
    if page is not None:
        item["page_idx"] = page.page_idx
    if obj.stream is not None:
        item["stream"] = stream_metadata(obj.stream)
    return item


@asobj.register
def asobj_content_object(obj: _StructContentObject) -> StructContentObject:
    item = StructContentObject(props=asobj(obj.props))
    page = obj.page
    if page is not None:
        item["page_idx"] = page.page_idx
    return item


@asobj.register
def asobj_structelement(obj: _Element) -> StructElement:
    el = StructElement()
    page = obj.page
    if page is not None:
        el["page_idx"] = page.page_idx
    if "T" in obj.props:
        el["title"] = decode_text(resolve1(obj.props["T"]))
    if "Lang" in obj.props:
        el["language"] = decode_text(resolve1(obj.props["Lang"]))
    if "Alt" in obj.props:
        el["alternate_description"] = decode_text(resolve1(obj.props["Alt"]))
    if "E" in obj.props:
        el["abbreviation_expansion"] = decode_text(resolve1(obj.props["E"]))
    if "ActualText" in obj.props:
        el["actual_text"] = decode_text(resolve1(obj.props["ActualText"]))
    children = [asobj(el) for el in obj]
    if children:
        el["children"] = children
    return el


@asobj.register
def asobj_structtree(obj: _Tree) -> StructTree:
    root = StructElement(type="StructTreeRoot", children=[asobj(el) for el in obj])
    return StructTree(root=root)


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
        if pdf.outline is not None:
            doc["outline"] = asobj(pdf.outline)
        dests = asobj(pdf.destinations)
        if dests:
            doc["destinations"] = dests
    if "structure" not in exclude and pdf.structure is not None:
        doc["structure"] = asobj(pdf.structure)

    return doc
