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
from os import PathLike
from multiprocessing.context import BaseContext
from pathlib import Path
from typing import Union

import playa.document
from playa.document import Document, LayoutDict, schema as schema  # noqa: F401
from playa.page import DeviceSpace
from playa._version import __version__  # noqa: F401

fieldnames = LayoutDict.__annotations__.keys()


def init_worker(path: Path, password: str = "", space: DeviceSpace = "screen") -> None:
    playa.document.__pdf = open(path, password=password, space=space)


def open(
    path: Union[PathLike, str],
    *,
    password: str = "",
    space: DeviceSpace = "screen",
    max_workers: int = 1,
    mp_context: Union[BaseContext, None] = None,
) -> Document:
    """Open a PDF document from a path on the filesystem."""
    fp = builtins.open(path, "rb")
    pdf = Document(fp, password=password, space=space)
    pdf._fp = fp
    if max_workers > 1:
        pdf._pool = ProcessPoolExecutor(
            max_workers=max_workers,
            mp_context=mp_context,
            initializer=init_worker,  # type: ignore[arg-type]
            initargs=(path, password, space),  # type: ignore[arg-type]
        )
    return pdf
