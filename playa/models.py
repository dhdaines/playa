"""Metadata schemas for various objects.

This module contains TypedDict definitions for the dictionaries
produced by the `dict` method of various PLAYA layout and metadata
objects.
"""

from typing import List, TypedDict, Union

from playa.utils import Rect


class DocumentMetadata(TypedDict):
    pdf_version: str
    """Version of the PDF standard this document implements."""
    is_printable: bool
    """Should the user be allowed to print?"""
    is_modifiable: bool
    """Should the user be allowed to modify?"""
    is_extractable: bool
    """Should the user be allowed to extract text?"""
    pages: List["PageMetadata"]
    """Pages in this document."""
    objects: List["IndirectObjectMetadata"]
    """Indirect objects in this document."""


class PageMetadata(TypedDict):
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


class IndirectObjectMetadata(TypedDict):
    objid: int
    """Indirect object ID."""
    genno: int
    """Generation number."""
    type: str
    """Name of Python type to which this object was converted."""
