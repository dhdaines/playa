"""
Test the varieties of cross-reference table as implemented in playa.xref
"""

from pathlib import Path

import playa
import pytest
from playa.exceptions import PDFSyntaxError
from playa.parser import IndirectObjectParser, ObjectParser
from playa.xref import XRefFallback, XRefStream, XRefTable

from .data import CONTRIB, TESTDIR

THISDIR = Path(__file__).parent


def test_read_xref():
    """Verify we can read the xref table if there is junk before the header."""
    with playa.open(TESTDIR / "junk_before_header.pdf") as pdf:
        # Not a fallback, we got the right one
        assert isinstance(pdf.xrefs[0], XRefTable)


@pytest.mark.skipif(not CONTRIB.exists(), reason="contrib samples not present")
def test_root_damage() -> None:
    """Fail gracefully if the document root is damaged (issue #154)"""
    with playa.open(CONTRIB / "issue-154.pdf") as doc:
        assert isinstance(doc[827], playa.ContentStream)


def test_multi_xrefs(caplog) -> None:
    """Verify that we correctly read multi-segment xref tables."""
    with playa.open(TESTDIR / "multi-xrefs.pdf"):
        assert not caplog.records


# OMGFU GIT AND YOUR CRLF TRANSLATION
GOOD_XREF1 = (
    b"0 3\n"
    b"0000000000 65535 f \n"
    b"0000000010 00000 n \n"
    b"0000000020 00000 n \n"
    b"5 2\n"
    b"0000000030 00000 n \n"
    b"0000000040 00000 n \n"
    b"trailer\n"
    b"<</Size 7 /Root 1 0 R>>\n"
    b"startxref\n"
    b"0\n"
    b"%%EOF\n"
)


def test_xref_tables() -> None:
    """Verify that we can read valid xref tables."""
    x = XRefTable(ObjectParser(GOOD_XREF1))
    assert repr(x)
    crlf = GOOD_XREF1.replace(b" \n", b"\r\n")
    XRefTable(ObjectParser(crlf))
    cr = GOOD_XREF1.replace(b" \n", b" \r")
    XRefTable(ObjectParser(cr))


# EOF before trailer (no trailer = fallback)
BAD_XREF1 = (
    b"0 3\n"
    b"0000000000 65535 f \n"
    b"0000000010 00000 n \n"
    b"0000000020 00000 n \n"
    b"5 2\n"
    b"0000000030 00000 n \n"
    b"0000000040 00000 n \n"
)


# EOF in table
BAD_XREF2 = b"0 5\n0000000000 65535 f \n0000000010 00000 n \n0000000020 00000 n \n"


# Junk in table
BAD_XREF3 = (
    b"0 5\n0000000000 65535 f FOOBIE\n0000000010 00000 n BLETCH\n0000000020 00000 n \n"
)


# Missing "trailer"
BAD_XREF4 = (
    b"0 3\n"
    b"0000000000 65535 f \n"
    b"0000000010 00000 n \n"
    b"0000000020 00000 n \n"
    b"5 2\n"
    b"0000000030 00000 n \n"
    b"0000000040 00000 n \n"
    b"not_a_trailer\n"
    b"<</Size 7 /Root 1 0 R>>\n"
    b"startxref\n"
    b"0\n"
    b"%%EOF\n"
)


def test_bad_xref_tables() -> None:
    """Verify that we fail on fatally flawed xref tables."""
    with pytest.raises(StopIteration):
        XRefTable(ObjectParser(BAD_XREF1))
    with pytest.raises(StopIteration):
        XRefTable(ObjectParser(BAD_XREF2))
    with pytest.raises(PDFSyntaxError):
        XRefTable(ObjectParser(BAD_XREF3))
    with pytest.raises(PDFSyntaxError):
        XRefTable(ObjectParser(BAD_XREF4))
    with pytest.raises(PDFSyntaxError):
        x = XRefTable(ObjectParser(GOOD_XREF1))
        x._load_trailer(ObjectParser(b"not_a_trailer"))


# F***ed up whitespace but still readable
UGLY_XREF1 = (
    b"0 3 0000000000 65535 f\n"
    b"\n"
    b"0000000010 00000 n\n"
    b"\n"
    b"0000000020 00000 n\n"
    b"\n"
    b"5 2 0000000030 00000 n\n"
    b"0000000040 00000 n\n"
    b"trailer\n"
    b"<</Size 7 /Root 1 0 R>>\n"
    b"startxref\n"
    b"0\n"
    b"%%EOF\n"
)
# FIXME: Don't yet handle the case of 20-byte records with no newlines

# Object count is greater than number of records
UGLY_XREF2 = (
    b"0 5\n"
    b"0000000000 65535 f \n"
    b"0000000010 00000 n \n"
    b"0000000020 00000 n \n"
    b"trailer\n"
    b"<</Size 3 /Root 1 0 R>>\n"
    b"startxref\n"
    b"0\n"
    b"%%EOF\n"
)
# FIXME: Don't yet handle the case of too small nobjs


def test_robust_xref_tables() -> None:
    """Verify that we can read slightly invalid xref tables."""
    nospace = GOOD_XREF1.replace(b" \n", b"\n")
    x = XRefTable(ObjectParser(nospace))
    assert list(x.objids) == [1, 2, 5, 6]
    x = XRefTable(ObjectParser(UGLY_XREF1))
    assert list(x.objids) == [1, 2, 5, 6]
    x = XRefTable(ObjectParser(UGLY_XREF2))
    assert list(x.objids) == [1, 2]
    assert x.get_pos(2).pos == 20


XREF_STREAM1 = b"""1 0 obj
<</Type/XRef/Size 5/W[1 3 2]/Filter[/ASCIIHexDecode]/Length 75>>
stream
00 ffffff 0000
01 000010 0000
01 000020 0000
01 000030 0000
01 000040 0000
endstream
endobj
"""


def test_xref_streams() -> None:
    """Verify that we can read xref streams."""
    s = XRefStream(IndirectObjectParser(XREF_STREAM1))
    assert repr(s)
    assert list(s.objids) == [1, 2, 3, 4]
    assert s.get_pos(2).pos == 32
    with pytest.raises(KeyError):
        s.get_pos(0)


BAD_XREF_STREAM1 = b"""1 0 obj
<</Type/Other/Size 5/W[1 3 2]/Filter[/ASCIIHexDecode]/Length 75>>
stream
00 ffffff 0000
01 000010 0000
01 000020 0000
01 000030 0000
01 000040 0000
endstream
endobj
"""


BAD_XREF_STREAM2 = b"""1 0 obj
<</Type/XRef/Size 5/Index[0 5 3]/W[1 3 2]/Filter[/ASCIIHexDecode]/Length 75>>
stream
00 ffffff 0000
01 000010 0000
01 000020 0000
01 000030 0000
01 000040 0000
endstream
endobj
"""


def test_bad_xref_streams() -> None:
    """Verify that we reject bad xref streams."""
    with pytest.raises(ValueError):
        XRefStream(IndirectObjectParser(BAD_XREF_STREAM1))
    with pytest.raises(PDFSyntaxError):
        XRefStream(IndirectObjectParser(BAD_XREF_STREAM2))


def test_xref_fallback() -> None:
    """Reconstruct xref table from a test document."""

    class FakeDoc:
        def decipher(self, _objid, _genno, data, *args, **kwargs):
            return data

    data = (THISDIR / "fallback-xref.pdf").read_bytes()
    f = XRefFallback(IndirectObjectParser(data, FakeDoc()))  # type: ignore[arg-type]
    assert repr(f)
    pos2 = f.get_pos(2)
    assert pos2.genno == 1
    assert data[pos2.pos :].startswith(b"2 1 obj")
    assert list(f.objids) == [1, 2, 3, 4, 7, 6, 5]
    pos7 = f.get_pos(7)
    assert pos7.streamid == 3
    assert f.trailer == {"Root": 1, "Size": 7}
    f = XRefFallback(
        IndirectObjectParser(data, FakeDoc(), strict=True)  # type: ignore[arg-type]
    )
