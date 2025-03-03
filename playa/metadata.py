"""Metadata schemas for various objects.

This module contains schemas (as TypedDict) and extractors for
metadata from various PLAYA objects, as well as a single-dispatch
function to extract said metadata from any object.

This is not done by methods on the classes in question as the
metadata schema, which has its own version (`playa.models.VERSION`),
should not depend on the particular implementation of those objects.
"""

import functools
from typing import List, TypedDict, Union

from playa.document import Document as _Document, DeviceSpace
from playa.page import Page as _Page, TextObject as _TextObject
from playa.parser import IndirectObject as _IndirectObject, PDFObject, PSLiteral
from playa.pdftypes import literal_name, ContentStream, ObjRef
from playa.utils import Rect, decode_text

VERSION = "1.0"


class Document(TypedDict):
    """Metadata for a PDF document."""

    pdf_version: str
    """Version of the PDF standard this document implements."""
    is_printable: bool
    """Should the user be allowed to print?"""
    is_modifiable: bool
    """Should the user be allowed to modify?"""
    is_extractable: bool
    """Should the user be allowed to extract text?"""
    pages: List["Page"]
    """Pages in this document."""
    objects: List["IndirectObject"]
    """Indirect objects in this document."""
    space: DeviceSpace
    """Device space for this document."""
    encryption: "Encryption"
    """Encryption information for this document."""
    outlines: "Outlines"
    """Outline hierarchy for this document.."""


class Encryption(TypedDict):
    """Encryption information."""


class Outlines(TypedDict):
    """Outline hierarchy for a PDF document."""


class Page(TypedDict):
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


class IndirectObject(TypedDict):
    objid: int
    """Indirect object ID."""
    genno: int
    """Generation number."""
    type: str
    """Name of Python type to which this object was converted."""
    obj: Union[float, int, str, bool, bytes, dict, list]
    """Object metadata (or data, for simple objects)."""


class TextObject(TypedDict):
    """Text object on a page."""


@functools.singledispatch
def asdict(obj):
    return {}


@asdict.register(_Document)
def document_asdict(pdf: _Document) -> Document:
    """Dictionary representation of a document."""
    return Document(
        pdf_version=pdf.pdf_version,
        is_printable=pdf.is_printable,
        is_modifiable=pdf.is_modifiable,
        is_extractable=pdf.is_extractable,
        pages=[page_asdict(page) for page in pdf.pages],
        objects=[obj_asdict(obj) for obj in pdf.objects],
    )


@asdict.register(_Page)
def page_asdict(page: _Page) -> Page:
    """Dictionary representation of a page."""
    return Page(
        objid=page.pageid,
        index=page.page_idx,
        label=page.label,
        mediabox=page.mediabox,
        cropbox=page.cropbox,
        rotate=page.rotate,
    )


@asdict.register(_IndirectObject)
def obj_asdict(obj: _IndirectObject) -> IndirectObject:
    return IndirectObject(
        objid=obj.objid,
        genno=obj.genno,
        type=type(obj.obj).__name__,
        obj=asobj(obj.obj),
    )


@asdict.register(_TextObject)
def text_asdict(text: _TextObject) -> TextObject:
    tstate = text.textstate
    # Prune these objects somewhat (FIXME: need a method that will
    # serialize only non-default values and run _asdict as needed)
    textstate = {
        "line_matrix": tstate.line_matrix,
        "fontsize": tstate.fontsize,
        "render_mode": tstate.render_mode,
    }
    if tstate.font is not None:
        textstate["font"] = {
            "fontname": tstate.font.fontname,
            "vertical": tstate.font.vertical,
        }
    gstate = {
        "scs": text.gstate.scs._asdict(),
        "scolor": text.gstate.scolor._asdict(),
        "ncs": text.gstate.ncs._asdict(),
        "ncolor": text.gstate.ncolor._asdict(),
    }
    obj = {
        "chars": text.chars,
        "bbox": text.bbox,
        "textstate": textstate,
        "gstate": gstate,
        "mcstack": [mcs._asdict() for mcs in text.mcstack],
    }
    return obj


@functools.singledispatch
def asobj(obj: PDFObject):
    return repr(obj)


@asobj.register(Union[int, float, bool, str])
def asobj_simple(
    obj: Union[int, float, bool, str]
) -> Union[int, float, bool, str]:
    return obj


@asobj.register(bytes)
def asobj_string(
    obj: bytes
) -> str:
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
