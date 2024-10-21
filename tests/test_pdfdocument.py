"""
Test the classes in pdfdocument.py
"""

from io import BytesIO
from pathlib import Path

import pytest

import playa
import playa.settings
from playa.data_structures import NameTree
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
        labels = [label for _, label in zip(range(10), doc.page_labels)]
        assert labels == ["iii", "iv", "1", "2", "1", "2", "3", "4", "5", "6"]


def test_pages():
    with playa.open(TESTDIR / "contrib" / "PSC_Station.pdf") as doc:
        page_objects = list(doc.pages)
        assert len(page_objects) == 15


def test_names():
    with playa.open(TESTDIR / "contrib" / "issue-625-identity-cmap.pdf") as doc:
        ef = NameTree(doc.names["EmbeddedFiles"])
        # Because yes, they can be UTF-16...
        names = [name.decode("UTF-16") for name, _ in ef]
        assert names == ["382901691/01_UBL.xml", "382901691/02_EAN_UCC.xml"]


def test_dests():
    with playa.open(TESTDIR / "pdf_js_issue620f.pdf") as doc:
        names = [name for name, _ in doc.dests]
        assert names == [b"Page.1", b"Page.2"]
