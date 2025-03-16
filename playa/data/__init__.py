"""PLAYA data API and schemas.

This module contains schemas (as TypedDict) and extractors for
metadata and content from various PLAYA objects, as well as a
single-dispatch function to extract said metadata from any object.

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
from typing import TypeVar

from playa.data.content import GraphicState, Tag, Text, TextState
from playa.data.metadata import (
    Dest,
    Document,
    Encryption,
    IndirectObject,
    Outlines,
    Page,
    StructElement,
    StructTree,
)
from playa.document import Document as _Document
from playa.page import Page as _Page
from playa.page import TextObject as _TextObject
from playa.parser import IndirectObject as _IndirectObject
from playa.parser import PSLiteral
from playa.pdftypes import ContentStream, ObjRef, literal_name
from playa.utils import decode_text

__all__ = [
    "GraphicState",
    "Tag",
    "Text",
    "TextState",
    "Dest",
    "Document",
    "Encryption",
    "IndirectObject",
    "Outlines",
    "Page",
    "StructElement",
    "StructTree",
]
VERSION = "1.0"


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
    doc = Document(
        pdf_version=pdf.pdf_version,
        is_printable=pdf.is_printable,
        is_modifiable=pdf.is_modifiable,
        is_extractable=pdf.is_extractable,
        pages=[asobj(page) for page in pdf.pages],
        objects=[asobj(obj) for obj in pdf.objects],
    )
    if pdf.encryption is not None:
        ids, encrypt = pdf.encryption
        ids = ["<%s>" % binascii.hexlify(b).decode("ascii") for b in ids]
        encrypt = encrypt.copy()
        for k, v in encrypt.items():
            # They aren't printable strings, do not try to decode them...
            if isinstance(v, bytes):
                encrypt[k] = "<%s>" % binascii.hexlify(v).decode("ascii")
        doc["encryption"] = Encryption(ids=ids, encrypt=asobj(encrypt))
    return doc


@asobj.register(_TextObject)
def asobj_text(text: _TextObject) -> Text:
    return Text(
        chars=text.chars,
        bbox=text.bbox,
        textstate=asobj(text.textstate),
        gstate=asobj(text.gstate),
        mcstack=[asobj(mcs) for mcs in text.mcstack],
    )
