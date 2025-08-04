from typing import Union

import pytest

import playa
from playa.exceptions import PDFEncryptionError
from playa.page import Annotation, ImageObject
from playa.pdftypes import BBOX_NONE
from playa.structure import Element, Tree, ContentItem, ContentObject

from .data import ALLPDFS, CONTRIB, PASSWORDS, TESTDIR, XFAILS


def test_specific_structure():
    with playa.open(TESTDIR / "pdf_structure.pdf") as pdf:
        tables = list(pdf.structure.find_all("Table"))
        assert len(tables) == 1
        assert playa.asobj(tables[0])["type"] == "Table"
        lis = list(pdf.structure.find_all("LI"))
        assert len(lis) == 4
        assert playa.asobj(lis[0])["type"] == "LI"
        assert len(list(lis[0].find_all())) == 2
        assert lis[0].find().type == "LBody"
        assert lis[0].find().find().type == "Text body"
        assert lis[0].find().find().role == "P"
        p = pdf.structure.find("P")
        assert p is not None
        assert p.role == "P"
        table = pdf.structure.find("Table")
        assert table
        assert playa.asobj(table)["type"] == "Table"
        trs = list(table.find_all("TR"))
        assert len(trs) == 3
        assert playa.asobj(trs[0])["type"] == "TR"


def walk_structure(el: Union[Tree, Element], indent=0):
    for idx, k in enumerate(el):
        # Limit depth to avoid taking forever
        if indent >= 6:
            break
        # Limit number to avoid going forever
        if idx == 10:
            break
        if isinstance(k, Element):
            walk_structure(k, indent + 2)


@pytest.mark.parametrize("path", ALLPDFS, ids=str)
def test_structure(path) -> None:
    """Verify that we can read structure trees when they exist."""
    if path.name in XFAILS:
        pytest.xfail("Intentionally corrupt file: %s" % path.name)
    passwords = PASSWORDS.get(path.name, [""])
    for password in passwords:
        try:
            with playa.open(path, password=password) as doc:
                st = doc.structure
                if st is not None:
                    assert st.doc is doc
                    walk_structure(st)
        except PDFEncryptionError:
            pytest.skip("password incorrect or cryptography package not installed")


@pytest.mark.skipif(not CONTRIB.exists(), reason="contrib samples not present")
def test_annotations() -> None:
    """Verify that we can create annotations from ContentObjects."""
    with playa.open(CONTRIB / "Rgl-1314-2021-DM-Derogations-mineures.pdf") as pdf:
        assert pdf.structure is not None
        for link in pdf.structure.find_all("Link"):
            for kid in link:
                if isinstance(kid, ContentObject):
                    assert isinstance(kid.obj, Annotation)
                    assert kid.bbox is not BBOX_NONE


def test_content_xobjects() -> None:
    """Verify that we can get XObjects from OBJRs (even though it
    seems this never, ever happens in real PDFs, since it is utterly
    useless)."""
    with playa.open(TESTDIR / "structure_xobjects.pdf") as pdf:
        assert pdf.structure is not None
        top = pdf.structure.find("Document")
        assert top is not None
        kids = list(top)
        assert len(kids) == 4
        (img,) = kids[3]
        assert isinstance(img, ContentObject)
        obj = img.obj
        assert isinstance(obj, ImageObject)
        assert obj.bbox == pytest.approx((25, 154, 237, 275))


def test_xobject_mcids() -> None:
    """Verify that we can access marked content sections inside Form
    XObjects (ark) using marked-content reference dictionaries."""
    with playa.open(TESTDIR / "structure_xobjects.pdf") as pdf:
        assert pdf.structure is not None
        top = pdf.structure.find("Document")
        assert top is not None
        p1, p2, p3, fig = top
        assert isinstance(p1, Element)
        assert isinstance(p2, Element)
        assert isinstance(p3, Element)
        assert isinstance(fig, Element)
        (item,) = p1
        assert isinstance(item, ContentItem)
        assert item.text == "Hello world"
        assert item.bbox == p1.bbox
        (item,) = p2
        assert isinstance(item, ContentItem)
        assert item.text == "Goodbye now"
        assert item.bbox == p2.bbox
        (item,) = p3
        assert isinstance(item, ContentItem)
        assert item.text == "Hello again"
        assert item.bbox == p3.bbox
        xobj = next(pdf.pages[0].xobjects)
        for obj in xobj:
            assert obj.parent is not None
            (item,) = obj.parent.contents
            assert isinstance(item, ContentItem)
            assert item.mcid == obj.mcid
            assert item.bbox == obj.bbox
            assert item.stream is not None
            assert item.stream.objid == xobj.stream.objid
        img = next(pdf.pages[0].images)
        assert img.parent is not None
        (cobj,) = img.parent
        assert isinstance(cobj, ContentObject)
        assert cobj.bbox == img.bbox
        assert cobj.bbox == fig.bbox


def test_image_in_mcs() -> None:
    """Verify that we can access images both through marked content
    sections and OBJRs."""
    with playa.open(TESTDIR / "structure_xobjects_2.pdf") as pdf:
        img1, img2 = pdf.pages[0].images
        assert img1.parent is not None
        (item,) = img1.parent
        assert isinstance(item, ContentItem)
        assert item.bbox == img1.bbox
        assert img2.parent is not None
        (cobj,) = img2.parent
        assert isinstance(cobj, ContentObject)
        assert cobj.bbox == img2.bbox


def test_mcid_texts() -> None:
    """Verify that we can get text from marked content sections."""
    with playa.open(TESTDIR / "structure_xobjects.pdf") as pdf:
        page = pdf.pages[0]
        assert page.mcid_texts == {0: ["Hello again"]}
        xobj = next(page.xobjects)
        assert xobj.mcid_texts == {0: ["Hello world"], 1: ["Goodbye now"]}


def test_structure_bbox() -> None:
    """Verify that we can get the bounding box of structure elements."""
    with playa.open(TESTDIR / "pdf_structure.pdf") as pdf:
        assert pdf.structure is not None
        table = pdf.structure.find("Table")
        assert table is not None
        assert table.bbox is not BBOX_NONE
        li = pdf.structure.find("LI")
        assert li is not None
        assert li.bbox is not BBOX_NONE
        for item in li.contents:
            assert item.bbox is not BBOX_NONE
    with playa.open(TESTDIR / "image_structure.pdf") as pdf:
        assert pdf.structure is not None
        figure = pdf.structure.find("Figure")
        assert figure is not None
        assert figure.bbox is not BBOX_NONE
        for item in figure.contents:
            assert item.bbox is not BBOX_NONE


def test_content_structure() -> None:
    """Verify that we can access structure elements from content objects."""
    with playa.open(TESTDIR / "pdf_structure.pdf") as pdf:
        for obj in pdf.pages[0]:
            if obj.object_type == "path":
                assert obj.parent is None
            else:
                assert obj.parent is not None
                assert obj.parent.role in ("P", "H1", "H2", "H3")


def test_element_hash():
    with playa.open(TESTDIR / "pdf_structure.pdf") as pdf:
        elements = set(pdf.structure.find_all())
        page = pdf.pages[0]
        for element in page.structure:
            if element is not None:
                if element.parent is not None:
                    sibs = set(element.parent)
                    assert element in sibs
                    # Make sure that we can test for inequality too
                    if len(sibs) > 1:
                        assert sum(1 for sib in sibs if sib == element) < len(sibs)
                assert element in elements
                assert element == element


def test_page_structure() -> None:
    with playa.open(TESTDIR / "pdf_structure.pdf") as pdf:
        assert pdf.structure is not None
        elements = set(pdf.structure.find_all("Table"))
        assert len(elements) == 1
        page = pdf.pages[0]
        count = 0
        for element in page.structure.find_all("Table"):
            assert element in elements
            count += 1
        assert count == 1
        assert list(page.structure[0:5].find_all("Table")) == []
        assert len(list(page.structure[-5:].find_all("Table"))) == 1


if __name__ == "__main__":
    test_specific_structure()
