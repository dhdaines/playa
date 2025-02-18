from dataclasses import asdict
from typing import Union

import pytest
import playa
from playa.structure import Element, Tree
from .data import ALLPDFS, TESTDIR, XFAILS


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
    with playa.open(path) as doc:
        st = doc.structure
        if st is not None:
            assert st.doc is doc
            assert st.page is None
            walk_structure(st)
        for page in doc.pages:
            st = page.structure
            if st is None:
                continue
            assert st.doc is doc
            assert st.page is page
            walk_structure(st)


if __name__ == "__main__":
    test_structure(TESTDIR / "pdf_structure.pdf")
