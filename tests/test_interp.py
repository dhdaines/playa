"""
Test the PDF content stream interpreter.
"""

import playa
from playa.interp import _make_fontmap
from .data import TESTDIR


def test_make_fontmap() -> None:
    """Test fontmap creation"""
    with playa.open(TESTDIR / "pdf_structure.pdf") as pdf:
        assert _make_fontmap([1, 2, 3], pdf) == {}
        fontmap = _make_fontmap(pdf.pages[0].resources["Font"], pdf)
        assert fontmap.keys() == {"F1", "F2"}
