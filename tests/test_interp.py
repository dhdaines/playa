"""
Test the PDF content stream interpreter.
"""

import logging
from pathlib import Path

import playa
from playa.document import LITERAL_TYPE1
from playa.interp import _make_fontmap

from .data import TESTDIR

THISDIR = Path(__file__).parent


def test_make_fontmap(caplog) -> None:
    """Test fontmap creation"""
    with playa.open(TESTDIR / "pdf_structure.pdf") as pdf:
        assert _make_fontmap([1, 2, 3], pdf) == {}
        fonts = pdf.pages[0].resources["Font"].resolve()
        fontmap = _make_fontmap(fonts, pdf)
        assert fontmap.keys() == {"F1", "F2"}
        fontmap = _make_fontmap(
            {"F1": {"Subtype": LITERAL_TYPE1, "FontDescriptor": 42}}, pdf
        )
        assert "Invalid font dictionary" in caplog.text


def test_init_resources(caplog) -> None:
    with playa.open(THISDIR / "bad_resources.pdf") as pdf:
        for _ in pdf.pages[0]:
            pass
        assert "Missing" in caplog.text
        assert "not a dict" in caplog.text


def test_iter(caplog) -> None:
    caplog.set_level(logging.DEBUG)
    with playa.open(THISDIR / "bad_operators.pdf") as pdf:
        for _ in pdf.pages[0]:
            pass
        for _ in pdf.pages[0].texts:
            pass
    assert "Insufficient arguments" in caplog.text
    assert "Incorrect type" in caplog.text
    assert "Invalid offset" in caplog.text
    assert "Unknown operator" in caplog.text
    assert "Undefined xobject" in caplog.text
    assert "invalid xobject" in caplog.text
    assert "Unsupported XObject" in caplog.text
    assert "Undefined Font" in caplog.text
    assert "is not a name object" in caplog.text
    assert "Missing property list" in caplog.text
