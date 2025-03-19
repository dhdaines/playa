"""Serializers for PDF metadata."""

import base64
import dataclasses
import functools
from typing import TypeVar, Union

from playa.parser import PSLiteral
from playa.pdftypes import ObjRef, literal_name


@functools.singledispatch
def asobj(obj):
    """JSON serializable representation of PDF object metadata."""
    # functools.singledispatch can't register None
    if obj is None:
        return None
    # Catch dataclasses that don't have a specific serializer
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {k: asobj(v) for k, v in obj.__dict__.items()}
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


@asobj.register
def asobj_bytes(obj: bytes) -> str:
    # Reimplement decode_text here as we want to be stricter about
    # what we consider a text string.  PDFDocEncoding is impossible to
    # detect so should only be used when we *know* it's a text string
    # according to the PDF standard.
    if obj.startswith(b"\xfe\xff"):
        return obj.decode("UTF-16")
    try:
        return obj.decode("ascii")
    except UnicodeDecodeError:
        # FIXME: This may be subject to change...
        return "base64:" + base64.b64encode(obj).decode("ascii")


@asobj.register
def asobj_literal(obj: PSLiteral) -> str:
    return literal_name(obj)


@asobj.register
def asobj_dict(obj: dict) -> dict:
    return {k: asobj(v) for k, v in obj.items()}


@asobj.register
def asobj_list(obj: list) -> list:
    return [asobj(v) for v in obj]


@asobj.register(tuple)
def asobj_tuple(obj: tuple) -> Union[list, dict]:
    # Catch NamedTuples that don't have a specific serializer
    if hasattr(obj, "_asdict"):
        return {k: asobj(v) for k, v in obj._asdict().items()}
    return [asobj(v) for v in obj]


@asobj.register
def asobj_ref(obj: ObjRef) -> str:
    # This is the same as repr() but we want it defined separately
    return f"<ObjRef:{obj.objid}>"
