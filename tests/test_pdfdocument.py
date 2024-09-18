"""
Test the classes in pdfdocument.py
"""

from io import BytesIO
from pathlib import Path

import pytest

import playa
import playa.settings
from playa.exceptions import PDFSyntaxError
from playa.pdfdocument import read_header

playa.settings.STRICT = True

TESTDIR = Path(__file__).parent.parent / "samples"


def test_read_header():
    """Verify reading header."""
    with pytest.raises(PDFSyntaxError):
        read_header(BytesIO(b"NOT-A-PDF!!!"))
    with pytest.raises(PDFSyntaxError):
        read_header(BytesIO(b"%PDF"))
    with pytest.raises(PDFSyntaxError) as e:
        read_header(BytesIO("%PDF-ÅÖÜ".encode("latin1")))
    assert "ASCII" in str(e)
    with pytest.raises(PDFSyntaxError) as e:
        read_header(BytesIO(b"%PDF-OMG"))
    assert "invalid" in str(e)
    assert read_header(BytesIO(b"%PDF-1.7")) == "1.7"


def test_page_labels():
    with playa.open(TESTDIR / "contrib" / "pagelabels.pdf") as doc:
        labels = [label for _, label in zip(range(10), doc.get_page_labels())]
        assert labels == ["iii", "iv", "1", "2", "1", "2", "3", "4", "5", "6"]
