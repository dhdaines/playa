"""
PLAYA is a LAYout Analyzer.

Basic usage:

    pdf = playa.open(path)
"""

import builtins
from contextlib import contextmanager
from os import PathLike
from typing import Iterator

from playa.pdfdocument import PDFDocument
from playa.pdfparser import PDFParser

__version__ = "0.0.1"


@contextmanager
def open(path: PathLike, password: str = "") -> Iterator[PDFDocument]:  # noqa: A001
    """Open a PDF document from a path on the filesystem."""
    with builtins.open(path, "rb") as infh:
        with PDFDocument(infh, password) as pdf:
            yield pdf
