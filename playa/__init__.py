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
from os import PathLike
from typing import Union

from playa.document import Document, LayoutDict, schema as schema  # noqa: F401
from playa.page import DeviceSpace

__version__ = "0.2.1"

fieldnames = LayoutDict.__annotations__.keys()


def open(
    path: Union[PathLike, str], password: str = "", space: DeviceSpace = "screen"
) -> Document:
    """Open a PDF document from a path on the filesystem."""
    fp = builtins.open(path, "rb")
    pdf = Document(fp, password=password, space=space)
    pdf._fp = fp
    return pdf
