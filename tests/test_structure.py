from dataclasses import asdict
from typing import Union

import pytest

import playa
from playa.exceptions import PDFEncryptionError
from playa.structure import Element, Tree

from .data import ALLPDFS, PASSWORDS, TESTDIR, XFAILS


def test_specific_structure():
    with playa.open(TESTDIR / "pdf_structure.pdf") as pdf:
        tables = list(pdf.structure.find_all("Table"))
        assert len(tables) == 1
        lis = list(pdf.structure.find_all("LI"))
        assert len(lis) == 4
        table = pdf.structure.find("Table")
        assert table
        trs = list(table.find_all("TR"))
        assert len(trs) == 3


def walk_structure(el: Union[Tree, Element], indent=0):
    for idx, k in enumerate(el):
        # Limit depth to avoid taking forever
        if indent >= 6:
            break
        # Limit number to avoid going forever
        if idx == 10:
            break
        print(" " * indent, asdict(k))
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


if __name__ == "__main__":
    test_specific_structure()
