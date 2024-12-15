"""
Inadequately test CMap parsing and such.
"""

from pathlib import Path

from playa.cmapdb import parse_tounicode, parse_encoding
from playa.font import Type1FontHeaderParser

THISDIR = Path(__file__).parent


def test_parse_tounicode():
    with open(THISDIR / "cmap-tounicode.txt", "rb") as infh:
        data = infh.read()
    cmap = parse_tounicode(data)
    assert cmap.cid2unichr == {
        1: "x",
        2: "̌",
        3: "u",
        111: "ç",
        112: "é",
        113: "è",
        114: "ê",
    }


def test_parse_encoding():
    with open(THISDIR / "cmap-encoding.txt", "rb") as infh:
        data = infh.read()
    cmap = parse_encoding(data)
    cids = list(cmap.decode("hello world".encode("UTF-16-BE")))
    assert cids == [ord(x) for x in "hello world"]
    cids = list(cmap.decode(b"\x00W \x00T \x00F"))
    assert cids == [87, 229, 84, 229, 70]


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
