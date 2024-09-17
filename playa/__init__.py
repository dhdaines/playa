"""
PLAYA is a LAYout Analyzer.

Basic usage:

    pdf = playa.open(path)
"""

import io
from contextlib import contextmanager
from os import PathLike

from playa.pdfdocument import PDFDocument
from playa.pdfparser import PDFParser

__version__ = "0.0.1"


@contextmanager
def open(path: PathLike, password: str = "") -> PDFDocument:
    """Open a PDF document from a path on the filesystem."""
    with io.open(path, "rb") as infh:
        parser = PDFParser(infh)
        yield PDFDocument(parser, password)
