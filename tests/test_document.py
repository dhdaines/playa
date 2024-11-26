"""
Test the classes in pdfdocument.py
"""

from io import BytesIO
from pathlib import Path

import pytest

import playa
from playa.data_structures import NameTree
from playa.document import read_header
from playa.exceptions import PDFSyntaxError
from playa.parser import LIT
from playa.utils import decode_text

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


def test_tokens():
    with playa.open(TESTDIR / "simple1.pdf") as doc:
        tokens = list(doc.tokens)
        assert len(tokens) == 190
        assert LIT("Helvetica") in tokens


def test_objects():
    with playa.open(TESTDIR / "simple1.pdf") as doc:
        doc7 = doc[7]
        assert doc7["Type"] == LIT("Font")
        doc1 = doc[1]
        assert doc1["Type"] == LIT("Catalog")
        objects = list(doc)
        assert len(objects) == 7
        # Note that they don't have to be in order
        assert objects[0].obj == doc[1]
        assert objects[2].obj == doc[3]
        # FIXME: this should also be the case but is not as it gets reparsed:
        # assert objects[0].obj is doc[1]


def test_page_labels():
    with playa.open(TESTDIR / "contrib" / "pagelabels.pdf") as doc:
        labels = [label for _, label in zip(range(10), doc.page_labels)]
        assert labels == ["iii", "iv", "1", "2", "1", "2", "3", "4", "5", "6"]
        assert doc.pages["iii"] is doc.pages[0]
        assert doc.pages["iv"] is doc.pages[1]
        assert doc.pages["2"] is doc.pages[3]
    with playa.open("samples/2023-06-20-PV.pdf") as doc:
        assert doc.pages["1"] is doc.pages[0]
        with pytest.raises(KeyError):
            _ = doc.pages["3"]
        with pytest.raises(IndexError):
            _ = doc.pages[2]


def test_pages():
    with playa.open(TESTDIR / "contrib" / "PSC_Station.pdf") as doc:
        page_objects = list(doc.pages)
        assert len(page_objects) == 15
        objects = list(page_objects[2].contents)
        assert LIT("Artifact") in objects
        tokens = list(page_objects[2].tokens)
        assert b"diversit\xe9 " in tokens


def test_names():
    with playa.open(TESTDIR / "contrib" / "issue-625-identity-cmap.pdf") as doc:
        ef = NameTree(doc.names["EmbeddedFiles"])
        # Because yes, they can be UTF-16... (the spec says nothing
        # about this but it appears some authoring tools assume that
        # the names here are equivalent to the `UF` entries in a file
        # specification dictionary)
        names = [decode_text(name) for name, _ in ef]
        # FIXME: perhaps we want to have an iterator over NameTrees
        # that decodes text strings for you
        assert names == ["382901691/01_UBL.xml", "382901691/02_EAN_UCC.xml"]


def test_dests():
    with playa.open(TESTDIR / "pdf.js" / "issue620f.pdf") as doc:
        names = [name for name, _ in doc.dests]
        assert names == ["Page.1", "Page.2"]


def test_outlines():
    with playa.open(
        "samples/2023-04-06-ODJ et Résolutions-séance xtra 6 avril 2023.pdf"
    ) as doc:
        titles = [o.title for o in doc.outlines]
        assert titles == [
            "2023-04-06-ODJ_xtra-6 avril 2023.pdf",
            "1.1 - Réso - Adop ODJ-6 avril 2023",
            "6.1 - Réso - Aut signature-PRACIM",
            "11.1 - Réso - Adop du règlement 1330-1",
            "15 - Résolution - Levée de la séance",
        ]


def test_xobjects() -> None:
    with playa.open(TESTDIR / "pdf.js" / "basicapi.pdf") as doc:
        page = doc.pages[0]
        xobj = next(page.xobjects)
        assert xobj.object_type == "xobject"
        assert len(list(xobj.layout)) == 2
        assert len(list(xobj)) == 2
