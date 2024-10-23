"""
PLAYA is a LAYout Analyzer.

Basic usage:

    pdf = playa.open(path)
"""

import builtins
from os import PathLike
from typing import Union

from playa.pdfdocument import PDFDocument

__version__ = "0.0.1"


def open(path: Union[PathLike, str], password: str = "") -> PDFDocument:
    """Open a PDF document from a path on the filesystem."""
    fp = builtins.open(path, "rb")
    pdf = PDFDocument(fp, password)
    pdf._fp = fp
    return pdf
