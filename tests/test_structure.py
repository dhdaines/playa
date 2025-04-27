from typing import Union

import pytest

import playa
from playa.exceptions import PDFEncryptionError
from playa.page import Annotation, XObjectObject, TextObject
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


def test_content_xobjects() -> None:
    """Verify that we can get XObjects from OBJRs (even though it
    seems this never, ever happens in real PDFs, since it is utterly
    useless)."""
    with playa.open(TESTDIR / "structure_xobjects.pdf") as pdf:
        assert pdf.structure is not None
        section = pdf.structure.find("Document")
        assert section is not None
        xobj, mcs = section
        assert isinstance(xobj, ContentObject)
        xobjobj = xobj.obj
        assert isinstance(xobjobj, XObjectObject)
        (text,) = xobjobj
        assert isinstance(text, TextObject)
        assert text.chars == "Hello world"
        assert isinstance(mcs, ContentItem)
        assert mcs.mcid == 1


if __name__ == "__main__":
    test_specific_structure()
