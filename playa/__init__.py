"""
PLAYA ain't a LAYout Analyzer... but it can help you get stuff
out of PDFs.

Basic usage:

    with playa.open(path) as pdf:
        for page in pdf.pages:
            print(f"page {page.label}:")
            for obj in page:
                print(f"    {obj.object_type} at {obj.bbox}")
                if obj.object_type == "text":
                    print(f"        chars: {obj.chars}")
"""

import builtins
from concurrent.futures import ProcessPoolExecutor
from multiprocessing.context import BaseContext
from os import PathLike
from typing import Union

from playa._version import __version__
from playa.color import Color, ColorSpace
from playa.data import asobj
from playa.document import Document, PageList
from playa.exceptions import PDFEncryptionError, PDFException, PDFPasswordIncorrect
from playa.page import (
    ContentObject,
    DeviceSpace,
    GraphicState,
    MarkedContent,
    Page,
    PathSegment,
    TextState,
)
from playa.parser import Token
from playa.pdftypes import ContentStream, ObjRef
from playa.pdftypes import resolve1 as resolve
from playa.pdftypes import resolve_all
from playa.utils import Matrix, Point, Rect
from playa.worker import _init_worker, _init_worker_buffer

__all__ = [
    "Document",
    "Page",
    "PageList",
    "DeviceSpace",
    "Color",
    "ColorSpace",
    "ContentObject",
    "ContentStream",
    "GraphicState",
    "MarkedContent",
    "Matrix",
    "Point",
    "Rect",
    "PathSegment",
    "TextState",
    "Token",
    "ObjRef",
    "PDFEncryptionError",
    "PDFException",
    "PDFPasswordIncorrect",
    "asobj",
    "resolve",
    "resolve_all",
    "__version__",
]


def open(
    path: Union[PathLike, str],
    *,
    password: str = "",
    space: DeviceSpace = "screen",
    max_workers: Union[int, None] = 1,
    mp_context: Union[BaseContext, None] = None,
) -> Document:
    """Open a PDF document from a path on the filesystem.

    Args:
        path: Path to the document to open.
        space: Device space to use ("screen" for screen-like
               coordinates, "page" for pdfminer.six-like coordinates, "default" for
               default user space with no rotation or translation)
        max_workers: Number of worker processes to use for parallel
                     processing of pages (if 1, no workers are spawned)
        mp_context: Multiprocessing context to use for worker
                    processes, see [Contexts and Start
                    Methods](https://docs.python.org/3/library/multiprocessing.html#contexts-and-start-methods)
                    for more information.
    """
    fp = builtins.open(path, "rb")
    pdf = Document(fp, password=password, space=space)
    pdf._fp = fp
    if max_workers is None or max_workers > 1:
        pdf._pool = ProcessPoolExecutor(
            max_workers=max_workers,
            mp_context=mp_context,
            initializer=_init_worker,  # type: ignore[arg-type]
            initargs=(id(pdf), path, password, space),  # type: ignore[arg-type]
        )
    return pdf


def parse(
    buffer: bytes,
    *,
    password: str = "",
    space: DeviceSpace = "screen",
    max_workers: Union[int, None] = 1,
    mp_context: Union[BaseContext, None] = None,
) -> Document:
    """Read a PDF document from binary data.

    Note: Potential slowness
        When using multiple processes, this results in the entire
        buffer being copied to the worker processes for the moment,
        which may cause some overhead.  It is preferable to use `open`
        on a filesystem path if possible, since that uses
        memory-mapped I/O.

    Args:
        buffer: Buffer containing PDF data.
        space: Device space to use ("screen" for screen-like
               coordinates, "page" for pdfminer.six-like coordinates, "default" for
               default user space with no rotation or translation)
        max_workers: Number of worker processes to use for parallel
                     processing of pages (if 1, no workers are spawned)
        mp_context: Multiprocessing context to use for worker
                    processes, see [Contexts and Start
                    Methods](https://docs.python.org/3/library/multiprocessing.html#contexts-and-start-methods)
                    for more information.

    """
    pdf = Document(buffer, password=password, space=space)
    if max_workers is None or max_workers > 1:
        pdf._pool = ProcessPoolExecutor(
            max_workers=max_workers,
            mp_context=mp_context,
            initializer=_init_worker_buffer,  # type: ignore[arg-type]
            initargs=(id(pdf), buffer, password, space),  # type: ignore[arg-type]
        )
    return pdf
