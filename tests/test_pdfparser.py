"""
Test the PDF parser
"""

from io import BufferedReader, BytesIO

import pytest

from playa.exceptions import PSEOF, PDFSyntaxError
from playa.pdfparser import read_header
from playa.psparser import KEYWORD_DICT_BEGIN, KEYWORD_DICT_END, KWD, LIT, PSBaseParser


def test_read_header():
    """Verify reading header."""
    with pytest.raises(PDFSyntaxError):
        read_header(BytesIO(b"NOT-A-PDF!!!"))
    with pytest.raises(PDFSyntaxError):
        read_header(BytesIO(b"%PDF"))
    with pytest.raises(PDFSyntaxError) as e:
        read_header(BytesIO("%PDF-ÅÖÜ".encode("latin1")))
    assert "ASCII" in str(e)
    with pytest.raises(PDFSyntaxError) as e:
        read_header(BytesIO(b"%PDF-OMG"))
    assert "invalid" in str(e)
    assert read_header(BytesIO(b"%PDF-1.7")) == "1.7"


TESTDATA = b"""
ugh
foo\r
bar\rbaz
quxx
bog"""
EXPECTED = [
    (0, b"\n"),
    (1, b"ugh\n"),
    (5, b"foo\r\n"),
    (10, b"bar\r"),
    (14, b"baz\n"),
    (18, b"quxx\n"),
    (23, b"bog"),
]


def test_nextline():
    """Verify that we replicate the old nextline method."""
    parser = PSBaseParser(BufferedReader(BytesIO(TESTDATA)))
    lines = []
    while True:
        try:
            linepos, line = parser.nextline()
        except PSEOF:
            break
        lines.append((linepos, line))
    assert lines == EXPECTED


def test_revreadlines():
    """Verify that we replicate the old revreadlines method."""
    parser = PSBaseParser(BufferedReader(BytesIO(TESTDATA)))
    lines = list(parser.revreadlines())
    assert lines == list(reversed([line for pos, line in EXPECTED]))


SIMPLE1 = b"""1 0 obj
<<
 /Type /Catalog
 /Outlines 2 0 R
 /Pages 3 0 R
>>
endobj
"""
SIMPLETOK = [
    1,
    0,
    KWD(b"obj"),
    KEYWORD_DICT_BEGIN,
    LIT("Type"),
    LIT("Catalog"),
    LIT("Outlines"),
    2,
    0,
    KWD(b"R"),
    LIT("Pages"),
    3,
    0,
    KWD(b"R"),
    KEYWORD_DICT_END,
    KWD(b"endobj"),
]


def test_new_parser():
    parser = PSBaseParser(BufferedReader(BytesIO(SIMPLE1 * 10000)))
    tokens = [tok for pos, tok in list(parser)]
    assert tokens == SIMPLETOK * 10000


def test_new_parser_eof():
    parser = PSBaseParser(BufferedReader(BytesIO(SIMPLE1[:-1])))
    tokens = [tok for pos, tok in list(parser)]
    assert tokens == SIMPLETOK


PAGE17 = b"""
    /A;Name_With-Various***Characters?
    /lime#20Green
    /paired#28#29parentheses
"""


def test_new_parser1():
    parser = PSBaseParser(BufferedReader(BytesIO(b"123.456")))
    assert list(parser) == [(0, 123.456)]
    parser = PSBaseParser(BufferedReader(BytesIO(b"+.013")))
    assert list(parser) == [(0, 0.013)]
    parser = PSBaseParser(BufferedReader(BytesIO(b"123")))
    assert list(parser) == [(0, 123)]
    parser = PSBaseParser(BufferedReader(BytesIO(b"true false")))
    assert list(parser) == [(0, True), (5, False)]
    parser = PSBaseParser(BufferedReader(BytesIO(b"(foobie bletch)")))
    assert list(parser) == [(0, b"foobie bletch")]
    parser = PSBaseParser(BufferedReader(BytesIO(b"(foo")))  # Invalid string
    assert list(parser) == []


def test_new_parser_names():
    # Examples from PDF 1.7 page 17
    parser = PSBaseParser(BufferedReader(BytesIO(PAGE17)))
    tokens = list(parser)
    assert tokens == [
        (5, LIT("A;Name_With-Various***Characters?")),
        (44, LIT("lime Green")),
        (62, LIT("paired()parentheses")),
    ]


def test_new_parser_strings():
    parser = PSBaseParser(
        BufferedReader(
            BytesIO(
                rb"( Strings may contain balanced parentheses ( ) and "
                rb"special characters ( * ! & } ^ % and so on ) . )"
            )
        )
    )
    assert list(parser) == [
        (
            0,
            rb" Strings may contain balanced parentheses ( ) and "
            rb"special characters ( * ! & } ^ % and so on ) . ",
        )
    ]
    parser = PSBaseParser(BufferedReader(BytesIO(b"()")))
    assert list(parser) == [(0, b"")]
    parser = PSBaseParser(
        BufferedReader(
            BytesIO(
                rb"""( These \
two strings \
are the same . )
    """
            )
        )
    )
    assert list(parser) == [(0, b" These two strings are the same . ")]
    parser = PSBaseParser(BufferedReader(BytesIO(b"(foo\rbar)")))
    assert list(parser) == [(0, b"foo\nbar")]
    parser = PSBaseParser(BufferedReader(BytesIO(b"(foo\r)")))
    assert list(parser) == [(0, b"foo\n")]
    parser = PSBaseParser(BufferedReader(BytesIO(b"(foo\r\nbaz)")))
    assert list(parser) == [(0, b"foo\nbaz")]
    parser = PSBaseParser(BufferedReader(BytesIO(b"(foo\n)")))
    assert list(parser) == [(0, b"foo\n")]
    parser = PSBaseParser(
        BufferedReader(
            BytesIO(rb"( This string contains \245two octal characters\307 . )")
        )
    )
    assert list(parser) == [
        (0, b" This string contains \245two octal characters\307 . ")
    ]
    parser = PSBaseParser(BufferedReader(BytesIO(rb"(\0053 \053 \53)")))
    assert list(parser) == [(0, b"\0053 \053 +")]
    parser = PSBaseParser(
        BufferedReader(BytesIO(rb"< 4E6F762073686D6F7A206B6120706F702E >"))
    )
    assert list(parser) == [(0, b"Nov shmoz ka pop.")]
    parser = PSBaseParser(BufferedReader(BytesIO(rb"<73 686 D6F7A2>")))
    assert list(parser) == [(0, b"shmoz ")]
    parser = PSBaseParser(BufferedReader(BytesIO(rb"(\400)")))
    assert list(parser) == [(0, b"")]


def test_invalid_strings_eof():
    parser = PSBaseParser(BufferedReader(BytesIO(rb"(\00")))
    assert list(parser) == []
    parser = PSBaseParser(BufferedReader(BytesIO(rb"(abracadab")))
    assert list(parser) == []
    parser = PSBaseParser(BufferedReader(BytesIO(rb"<73686")))
    assert list(parser) == []
