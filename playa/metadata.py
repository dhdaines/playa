"""Schemas for various metadata and content objects.

This module contains schemas (as TypedDict) and extractors for
metadata from various PLAYA objects, as well as a single-dispatch
function to extract said metadata from any object.

This is not done by methods on the classes in question as the
metadata schema, which has its own version (`playa.metadata.VERSION`),
should not depend on the particular implementation of those objects.

The other reason this is separate is because this is an entirely
non-lazy API.  It is provided here because the PLAYA CLI uses it, and
to prevent users of the library from reimplementing it themselves.
"""

import binascii
import dataclasses
import functools
from typing import List, Tuple, TypedDict, TypeVar, Union

from playa.document import Document as _Document, DeviceSpace
from playa.page import Page as _Page, TextObject as _TextObject
from playa.parser import IndirectObject as _IndirectObject, PSLiteral
from playa.pdftypes import literal_name, ContentStream, ObjRef
from playa.utils import Rect, decode_text

VERSION = "1.0"


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
    """Outline hierarchy for this document.."""
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


class IndirectObject(TypedDict, total=False):
    objid: int
    """Indirect object ID."""
    genno: int
    """Generation number."""
    type: str
    """Name of Python type to which this object was converted."""
    obj: Union[float, int, str, bool, bytes, dict, list]
    """Object metadata (or data, for simple objects)."""


class TextObject(TypedDict, total=False):
    """Text object on a page."""

    chars: str
    """Unicode string representation of text."""
    bbox: Rect
    """Bounding rectangle for all glyphs in text."""
    textstate: "TextState"
    """Text state."""
    gstate: "GraphicState"
    """Graphic state."""
    mcstack: List["MarkedContent"]
    """Stack of enclosing marked content sections."""


class TextState(TypedDict, total=False):
    """Text state."""


class GraphicState(TypedDict, total=False):
    """Graphic state."""


class MarkedContent(TypedDict, total=False):
    """Marked content section."""


@functools.singledispatch
def asobj(obj):
    """JSON serializable representation of PDF object metadata."""
    # Catch dataclasses that don't have a specific serializer
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {k: asobj(v) for k, v in obj.__dict__.items()}
    # Catch NamedTuples that don't have a specific serializer
    if hasattr(obj, "_asdict"):
        return {k: asobj(v) for k, v in obj._asdict().items()}
    return repr(obj)


_S = TypeVar("_S", int, float, bool, str)


def asobj_simple(obj: _S) -> _S:
    return obj


# Have to list these all for Python <3.11 where
# functools.singledispatch doesn't support Union
asobj.register(int, asobj_simple)
asobj.register(float, asobj_simple)
asobj.register(bool, asobj_simple)
asobj.register(str, asobj_simple)
asobj.register(tuple, asobj_simple)


@asobj.register(bytes)
def asobj_string(obj: bytes) -> str:
    return decode_text(obj)


@asobj.register(PSLiteral)
def asobj_literal(obj: PSLiteral) -> str:
    return literal_name(obj)


@asobj.register(dict)
def asobj_dict(obj: dict) -> dict:
    return {k: asobj(v) for k, v in obj.items()}


@asobj.register(list)
def asobj_list(obj: list) -> list:
    return [asobj(v) for v in obj]


@asobj.register(ContentStream)
def asobj_stream(obj: ContentStream) -> dict:
    return asobj(obj.attrs)


@asobj.register(ObjRef)
def asobj_ref(obj: ObjRef) -> str:
    # This is the same as repr() but we want it defined separately
    return f"<ObjRef:{obj.objid}>"


@asobj.register(_Page)
def asobj_page(page: _Page) -> Page:
    return Page(
        objid=page.pageid,
        index=page.page_idx,
        label=page.label,
        mediabox=page.mediabox,
        cropbox=page.cropbox,
        rotate=page.rotate,
    )


@asobj.register(_IndirectObject)
def asobj_obj(obj: _IndirectObject) -> IndirectObject:
    return IndirectObject(
        objid=obj.objid,
        genno=obj.genno,
        type=type(obj.obj).__name__,
        obj=asobj(obj.obj),
    )


@asobj.register(_Document)
def asobj_document(pdf: _Document) -> Document:
    doc = {
        "pdf_version": pdf.pdf_version,
        "is_printable": pdf.is_printable,
        "is_modifiable": pdf.is_modifiable,
        "is_extractable": pdf.is_extractable,
        "pages": [asobj(page) for page in pdf.pages],
        "objects": [asobj(obj) for obj in pdf.objects],
    }
    if pdf.encryption is not None:
        ids, encrypt = pdf.encryption
        ids = ["<%s>" % binascii.hexlify(b).decode('ascii') for b in ids]
        encrypt = encrypt.copy()
        for k, v in encrypt.items():
            # They aren't printable strings, do not try to decode them...
            if isinstance(v, bytes):
                encrypt[k] = "<%s>" % binascii.hexlify(v).decode('ascii')
        doc["encryption"] = Encryption(ids=ids, encrypt=asobj(encrypt))
    return doc


@asobj.register(_TextObject)
def asobj_text(text: _TextObject) -> TextObject:
    return TextObject(
        chars=text.chars,
        bbox=text.bbox,
        textstate=asobj(text.textstate),
        gstate=asobj(text.gstate),
        mcstack=[asobj(mcs) for mcs in text.mcstack],
    )
