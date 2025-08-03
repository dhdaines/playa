"""
Inadequately test EncodingDB and such.
"""

from playa.encodingdb import cid2unicode_from_encoding, name2unicode, EncodingDB
from playa.font import LITERAL_STANDARD_ENCODING


def test_name2unicode():
    """Verify various nooks and crannies of name2unicode algorithm."""
    # Explicit examples from the spec
    assert name2unicode("Lcommaaccent") == "\u013b"
    assert name2unicode("uni20AC0308") == "\u20ac\u0308"
    assert name2unicode("u1040C") == "\U0001040c"
    assert name2unicode("uniD801DC0C") == ""
    assert name2unicode("foo") == ""
    assert name2unicode(".notdef") == ""
    assert (
        name2unicode("Lcommaaccent_uni20AC0308_u1040C.alternate")
        == "\u013b\u20ac\u0308\U0001040c"
    )
    # We are more tolerant than the spec here
    assert name2unicode("uni20ac") == "\u20ac"
    # Make sure some specific things work
    assert name2unicode("fi") == "\ufb01"
    # Make sure suffixes are disregarded
    assert name2unicode("T.swash") == "T"
    # Make sure surrogates are ignored
    assert name2unicode("ud800") == ""


def test_get_encoding():
    """Briefly test that get_encoding works as expected."""
    standard = EncodingDB.get_encoding(LITERAL_STANDARD_ENCODING)
    assert standard[174] == "fi"
    standard_touni = cid2unicode_from_encoding(standard)
    assert standard_touni[174] == "ﬁ"
