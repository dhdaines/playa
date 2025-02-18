from dataclasses import asdict
from typing import Union

import pytest
import playa
from playa.exceptions import PDFEncryptionError
from playa.structure import Element, Tree
from .data import ALLPDFS, TESTDIR, XFAILS, PASSWORDS


def walk_structure(el: Union[Tree, Element], indent=0):
    for k in el:
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
            pytest.skip("cryptography package not installed")


if __name__ == "__main__":
    test_structure(TESTDIR / "pdf_structure.pdf")
