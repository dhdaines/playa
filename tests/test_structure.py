from typing import Union

import pytest
import playa
from playa.structure import Element, Tree
from .data import ALLPDFS, TESTDIR, XFAILS


def walk_structure(el: Union[Tree, Element]):
    print(el)
    try:
        for k in el:
            walk_structure(k)
    except TypeError:
        pass


@pytest.mark.parametrize("path", ALLPDFS, ids=str)
def test_structure(path) -> None:
    """Verify that we can read structure trees when they exist."""
    if path.name in XFAILS:
        pytest.xfail("Intentionally corrupt file: %s" % path.name)
    with playa.open(path) as doc:
        st = doc.structure
        assert st.doc is doc
        assert st.page is None
        if st is not None:
            walk_structure(st)
        for page in doc.pages:
            st = page.structure
            assert st.doc is doc
            assert st.page is page
            if st is not None:
                for el in st:
                    pass


if __name__ == '__main__':
    test_structure(TESTDIR / "pdf_structure.pdf")
