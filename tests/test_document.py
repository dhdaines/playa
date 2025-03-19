"""
Test the classes in pdfdocument.py
"""

from io import BytesIO

import pytest

import playa
from playa.data_structures import NameTree
from playa.document import Document, XRefTable, _open_input
from playa.page import TextObject
from playa.parser import LIT
from playa.utils import decode_text

from .data import CONTRIB, TESTDIR


def test_read_header():
    """Verify reading header."""
    version, offset, buffer = _open_input(BytesIO(b"NOT-A-PDF!!!"))
    assert version == "1.0"
    version, offset, buffer = _open_input(BytesIO(b"%PDF"))
    assert version == "1.0"
    version, offset, buffer = _open_input(BytesIO("%PDF-ÅÖÜ".encode("latin1")))
    assert version == "1.0"
    version, offset, buffer = _open_input(BytesIO(b"%PDF-OMG"))
    version, offset, buffer = _open_input(BytesIO(b"%PDF-1.7"))
    assert version == "1.7"
    assert offset == 0
    with open(TESTDIR / "junk_before_header.pdf", "rb") as infh:
        version, pos, buffer = _open_input(infh)
        assert version == "1.4"
        assert pos == 86


def test_read_xref():
    """Verify we can read the xref table if there is junk before the header."""
    with playa.open(TESTDIR / "junk_before_header.pdf") as pdf:
        # Not a fallback, we got the right one
        assert isinstance(pdf.xrefs[0], XRefTable)


def test_bytes():
    """Verify we can read input from a `bytes` buffer."""
    with open(TESTDIR / "simple1.pdf", "rb") as fh:
        buffer = fh.read()
        doc = Document(buffer)
        tokens = list(doc.tokens)
        assert len(tokens) == 190
        assert LIT("Helvetica") in tokens


def test_tokens():
    with playa.open(TESTDIR / "simple1.pdf") as doc:
        tokens = list(doc.tokens)
        assert len(tokens) == 190
        assert LIT("Helvetica") in tokens


def test_objects():
    with playa.open(TESTDIR / "simple1.pdf") as doc:
        # See note in Document.__getitem__ - this is not standards
        # compliant but since returning None would inevitably lead to
        # a TypeError down the line we signal it right away for the
        # moment.
        with pytest.raises(IndexError):
            _ = doc[12345]
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

    with playa.open(TESTDIR / "simple5.pdf") as doc:
        # Ensure robustness to missing space after `endobj`
        assert doc[43]


def test_object_streams():
    """Test iterating inside object streams."""
    with playa.open(TESTDIR / "simple5.pdf") as doc:
        objs = list(doc.objects)
        assert len(objs) == 53


@pytest.mark.skipif(not CONTRIB.exists(), reason="contrib samples not present")
def test_page_labels():
    with playa.open(CONTRIB / "pagelabels.pdf") as doc:
        labels = [label for _, label in zip(range(10), doc.page_labels)]
        assert labels == ["iii", "iv", "1", "2", "1", "2", "3", "4", "5", "6"]
        assert doc.pages["iii"] is doc.pages[0]
        assert doc.pages["iv"] is doc.pages[1]
        assert doc.pages["2"] is doc.pages[3]
    with playa.open(CONTRIB / "2023-06-20-PV.pdf") as doc:
        assert doc.pages["1"] is doc.pages[0]
        with pytest.raises(KeyError):
            _ = doc.pages["3"]
        with pytest.raises(IndexError):
            _ = doc.pages[2]


@pytest.mark.skipif(not CONTRIB.exists(), reason="contrib samples not present")
def test_pages():
    with playa.open(CONTRIB / "PSC_Station.pdf") as doc:
        page_objects = list(doc.pages)
        assert len(page_objects) == 15
        objects = list(page_objects[2].contents)
        assert LIT("Artifact") in objects
        tokens = list(page_objects[2].tokens)
        assert b"diversit\xe9 " in tokens
        assert page_objects[2].doc is doc
        twopages = doc.pages[2:4]
        assert len(twopages) == 2
        assert [p.label for p in twopages] == ["3", "4"]
        threepages = doc.pages["2", 2, 3]
        assert [p.label for p in threepages] == ["2", "3", "4"]
        threepages = doc.pages[["2", 2, 3]]
        assert [p.label for p in threepages] == ["2", "3", "4"]
        assert threepages.doc is doc


@pytest.mark.skipif(not CONTRIB.exists(), reason="contrib samples not present")
def test_names():
    with playa.open(CONTRIB / "issue-625-identity-cmap.pdf") as doc:
        ef = NameTree(doc.names["EmbeddedFiles"])
        # Because yes, they can be UTF-16... (the spec says nothing
        # about this but it appears some authoring tools assume that
        # the names here are equivalent to the `UF` entries in a file
        # specification dictionary)
        names = [decode_text(name) for name, _ in ef]
        # FIXME: perhaps we want to have an iterator over NameTrees
        # that decodes text strings for you
        assert names == ["382901691/01_UBL.xml", "382901691/02_EAN_UCC.xml"]


@pytest.mark.skipif(not CONTRIB.exists(), reason="contrib samples not present")
def test_destinations():
    with playa.open(CONTRIB / "issue620f.pdf") as doc:
        assert "Page.1" in doc.destinations
        assert "Page.2" in doc.destinations
    with playa.open(CONTRIB / "issue620f.pdf") as doc:
        names = list(doc.destinations)
        assert names == ["Page.1", "Page.2"]


@pytest.mark.skipif(not CONTRIB.exists(), reason="contrib samples not present")
def test_xobjects() -> None:
    with playa.open(CONTRIB / "basicapi.pdf") as doc:
        page = doc.pages[0]
        xobj = next(page.xobjects)
        assert xobj.object_type == "xobject"
        assert len(list(xobj)) == 2

        for obj in page.flatten():
            assert obj.object_type != "xobject"

        boxes = []
        for obj in page.flatten(TextObject):
            assert isinstance(obj, TextObject)
            boxes.append(tuple(round(x) for x in obj.bbox))
        # Make sure they are in the right place!
        assert boxes == [
            (136, 16, 136, 17),
            (238, 80, 358, 96),
            (45, 119, 116, 131),
            (118, 118, 550, 130),
            (61, 134, 142, 145),
            (147, 133, 550, 145),
            (389, 816, 546, 828),
        ]


def test_annotations() -> None:
    with playa.open(TESTDIR / "simple5.pdf") as doc:
        page = doc.pages[0]
        for annot in page.annotations:
            assert annot.page is page


def test_is_tagged() -> None:
    with playa.open(TESTDIR / "simple1.pdf") as doc:
        assert not doc.is_tagged
    with playa.open(TESTDIR / "pdf_structure.pdf") as doc:
        assert doc.is_tagged


def test_objects_decrypted() -> None:
    with playa.open(TESTDIR / "encryption" / "rc4-40.pdf", password="foo") as doc:
        info = None
        for obj in doc.objects:
            if obj.objid == 10:
                info = obj
        assert info is not None
        # Make sure strings are decrypted in both cases
        assert info.obj == doc[10]
        assert isinstance(info.obj, dict)
        assert info.obj["CreationDate"] == b"D:20140509193727+02'00'"
