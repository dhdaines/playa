"""
Inadequately test CMap parsing and such.
"""

from pathlib import Path

import pytest

import playa
from playa.cmapdb import parse_encoding, parse_tounicode
from playa.font import Type1FontHeaderParser

from .data import TESTDIR

THISDIR = Path(__file__).parent
BOGUS = rb"""begincmap
1 begincodespacerange
<0001> <0002>
endcodespacerange
2 begincidchar
<0001> 65
<0002> 66
endcidchar
endcmap
"""


def test_parse_tounicode():
    # A correct ToUnicode map
    with open(THISDIR / "cmap-tounicode.txt", "rb") as infh:
        data = infh.read()
    cmap = parse_tounicode(data)
    assert cmap.bytes2unicode == {
        b"\x01": "x",
        b"\x02": "̌",
        b"\x03": "u",
        b"\x6f": "ç",
        b"\x70": "é",
        b"\x71": "è",
        b"\x72": "ê",
    }
    assert "".join(cmap.decode(b"\x01\x02\x03")) == "x̌u"
    # A bogus ToUnicode map that uses cidrange instead of bfrange
    with open(THISDIR / "issue9367-tounicode.txt", "rb") as infh:
        data = infh.read()
    cmap = parse_tounicode(data)
    assert cmap.bytes2unicode[b"\x00\x28"] == "E"
    assert "".join(cmap.decode(b"\x00\x27\x00\x28")) == "DE"

    # Another bogus ToUnicode map that uses cidchar instead of bfchar
    cmap = parse_tounicode(BOGUS)
    assert cmap.bytes2unicode == {
        b"\x00\x01": "A",
        b"\x00\x02": "B",
    }

    # A rather complex (but valid) ToUnicode map for UTF-8
    with open(THISDIR / "issue18117-tounicode.txt", "rb") as infh:
        data = infh.read()
    cmap = parse_tounicode(data)
    uni = "abc\u3001" + bytes.fromhex("d862df46").decode("utf-16be")
    txt = uni.encode("utf-8")
    assert "".join(cmap.decode(txt)) == uni


def test_parse_encoding():
    # A basic encoding map
    with open(THISDIR / "cmap-encoding.txt", "rb") as infh:
        data = infh.read()
    cmap = parse_encoding(data)
    cids = [cid for _, cid in cmap.decode("hello world".encode("UTF-16-BE"))]
    assert cids == [ord(x) for x in "hello world"]
    cids = [cid for _, cid in cmap.decode(b"\x00W \x00T \x00F")]
    assert cids == [87, 229, 84, 229, 70]

    # A rather complex (but valid) Encoding map for UTF-8
    with open(THISDIR / "issue18117-encoding.txt", "rb") as infh:
        data = infh.read()
    cmap = parse_encoding(data)
    uni = "abc\u3001" + bytes.fromhex("d862df46").decode("utf-16be")
    txt = uni.encode("utf-8")
    assert [cid for _, cid in cmap.decode(txt)] == [12, 13, 14, 38, 41]


# Basically the sort of stuff we try to find in a Type 1 font
TYPE1DATA = b"""
%!PS-AdobeFont-1.0: MyBogusFont 0.1
/FontName /MyBogusFont def
/Encoding 256 array
0 1 255 {1 index exch /.notdef put} for
dup 48 /zero put
dup 49 /one put
readonly def
"""


def test_t1header_parser():
    parser = Type1FontHeaderParser(TYPE1DATA)
    assert parser.get_encoding() == {
        48: "0",
        49: "1",
    }


TOUNICODES = [
    ("utf8_tounicode.pdf", "abc defghijklmno pqrstuvw xyz0123456789 𨧀、𨭎、𨨏、𨭆"),
    ("utf16_tounicode.pdf", "Cina, il Grande"),
    ("ascii_tounicode.pdf", "Lorem ipsum"),
    ("duplicate_encoding_tounicode.pdf", " ISSUE 9915 "),
    ("pdf_structure.pdf", "Titre du document"),
    ("sampleOneByteIdentityEncode.pdf", "abc"),
]


@pytest.mark.parametrize("name,text", TOUNICODES, ids=str)
def test_various_tounicode(name, text):
    """Test complex ToUnicode cases, mostly taken from pdf.js"""
    with playa.open(TESTDIR / name) as pdf:
        assert next(pdf.pages[0].texts).chars == text
    with playa.open(TESTDIR / "simple3.pdf") as pdf:
        text = "".join(x.chars for x in pdf.pages[0].texts)
        assert text == "HelloHelloあいうえおあいうえおWorldWorld"
