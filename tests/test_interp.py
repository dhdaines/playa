"""
Test the PDF content stream interpreter.
"""

import logging
from pathlib import Path

import playa
from playa.document import LITERAL_TYPE1
from playa.interp import FontMapping, Type3Interpreter
from playa.parser import IndirectObjectParser

from .data import TESTDIR

THISDIR = Path(__file__).parent


def test_make_fontmap(caplog) -> None:
    """Test fontmap creation"""
    with playa.open(TESTDIR / "pdf_structure.pdf") as pdf:
        assert len(FontMapping([1, 2, 3], pdf)) == 0
        assert "not a dict" in caplog.text
        fonts = playa.resolve(pdf.pages[0].resources["Font"])
        fontmap = FontMapping(fonts, pdf)
        assert fontmap.keys() == {"F1", "F2"}
        fontmap = FontMapping(
            {"F1": {"Subtype": LITERAL_TYPE1, "FontDescriptor": 42}}, pdf
        )


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
    assert "Insufficient arguments" in caplog.text
    assert "Incorrect type" in caplog.text
    assert "Undefined xobject" in caplog.text
    assert "invalid xobject" in caplog.text
    assert "Unsupported XObject" in caplog.text
    assert "Undefined Font" in caplog.text
    assert "is not a name object" in caplog.text
    assert "Missing property list" in caplog.text


TYPE3_CHAR1 = b"""
99 0 obj
<</Length 0>>
stream
850 0 0 -200 1000 800 d1
% execute some color operators which do nothing
/Foo sh
0.5 scn
0.5 SCN
0.1 0.1 0.1 0.1 k
0.1 0.1 0.1 0.1 K
0.5 0.8 0.6 rg
0.5 0.8 0.6 RG
0.9 g
0.9 G
/DeviceRGB cs
/DeviceGray CS
/ReverseColorimetric ri
endstream
endobj
"""
TYPE3_CHAR2 = b"""
99 0 obj
<</Length 0>>
stream
800 0 d0
endstream
endobj
"""


def test_type3_interp() -> None:
    with playa.open(TESTDIR / "simple1.pdf") as pdf:
        _, obj = next(IndirectObjectParser(TYPE3_CHAR1))
        interp = Type3Interpreter(pdf.pages[0], [obj.obj])
        for _ in interp:
            pass
        assert interp.width == 850
        _, obj = next(IndirectObjectParser(TYPE3_CHAR2))
        interp = Type3Interpreter(pdf.pages[0], [obj.obj])
        for _ in interp:
            pass
        assert interp.width == 800
        # To get coverage
        assert interp.pop(0) == []
