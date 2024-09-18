"""
Test the PDF parser
"""

import tempfile

from playa.exceptions import PSEOF
from playa.psparser import (
    KEYWORD_DICT_BEGIN,
    KEYWORD_DICT_END,
    KWD,
    LIT,
    PSFileParser,
    PSInMemoryParser,
)

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


def run_parsers(data: bytes, expected: list, makefunc):
    """Test stuff on both BytesIO and BinaryIO."""
    bp = PSInMemoryParser(data)
    output = []
    func = makefunc(bp)
    while True:
        try:
            output.append(func())
        except PSEOF:
            break
    assert output == expected
    with tempfile.NamedTemporaryFile() as tf:
        with open(tf.name, "wb") as outfh:
            outfh.write(data)
        with open(tf.name, "rb") as infh:
            fp = PSFileParser(infh)
            func = makefunc(fp)
            output = []
            while True:
                try:
                    output.append(func())
                except PSEOF:
                    break
            assert output == expected


def test_nextline():
    """Verify that we replicate the old nextline method."""
    run_parsers(TESTDATA, EXPECTED, lambda foo: foo.nextline)


def test_revreadlines():
    """Verify that we replicate the old revreadlines method."""
    expected = list(reversed([line for pos, line in EXPECTED]))

    def make_next(parser):
        itor = parser.revreadlines()

        def nextor():
            try:
                line = next(itor)
            except StopIteration:
                raise PSEOF
            return line

        return nextor

    run_parsers(TESTDATA, expected, make_next)


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


def list_parsers(data: bytes, expected: list, discard_pos=False):
    bp = PSInMemoryParser(data)
    if discard_pos:
        tokens = [tok for pos, tok in list(bp)]
    else:
        tokens = list(bp)
    assert tokens == expected
    with tempfile.NamedTemporaryFile() as tf:
        with open(tf.name, "wb") as outfh:
            outfh.write(data)
        with open(tf.name, "rb") as infh:
            fp = PSFileParser(infh)
            if discard_pos:
                tokens = [tok for pos, tok in list(fp)]
            else:
                tokens = list(fp)
            assert tokens == expected


def test_new_parser():
    # Do a lot of them to make sure buffering works correctly
    list_parsers(SIMPLE1 * 100, SIMPLETOK * 100, discard_pos=True)


def test_new_parser_eof():
    # Make sure we get a keyword at eof
    list_parsers(SIMPLE1[:-1], SIMPLETOK, discard_pos=True)


PAGE17 = b"""
    /A;Name_With-Various***Characters?
    /lime#20Green
    /paired#28#29parentheses
"""


def test_new_parser1():
    list_parsers(b"123.456", [(0, 123.456)])
    list_parsers(b"+.013", [(0, 0.013)])
    list_parsers(b"123", [(0, 123)])
    list_parsers(b"true false", [(0, True), (5, False)])
    list_parsers(b"(foobie bletch)", [(0, b"foobie bletch")])
    list_parsers(b"(foo", [])


def test_new_parser_names():
    # Examples from PDF 1.7 page 17
    list_parsers(
        PAGE17,
        [
            (5, LIT("A;Name_With-Various***Characters?")),
            (44, LIT("lime Green")),
            (62, LIT("paired()parentheses")),
        ],
    )


def test_new_parser_strings():
    list_parsers(
        rb"( Strings may contain balanced parentheses ( ) and "
        rb"special characters ( * ! & } ^ % and so on ) . )",
        [
            (
                0,
                rb" Strings may contain balanced parentheses ( ) and "
                rb"special characters ( * ! & } ^ % and so on ) . ",
            )
        ],
    )
    list_parsers(b"()", [(0, b"")])
    list_parsers(
        rb"""( These \
two strings \
are the same . )
    """,
        [(0, b" These two strings are the same . ")],
    )
    list_parsers(b"(foo\rbar)", [(0, b"foo\nbar")])
    list_parsers(b"(foo\r)", [(0, b"foo\n")])
    list_parsers(b"(foo\r\nbaz)", [(0, b"foo\nbaz")])
    list_parsers(b"(foo\n)", [(0, b"foo\n")])
    list_parsers(
        rb"( This string contains \245two octal characters\307 . )",
        [(0, b" This string contains \245two octal characters\307 . ")],
    )
    list_parsers(rb"(\0053 \053 \53)", [(0, b"\0053 \053 +")])
    list_parsers(
        rb"< 4E6F762073686D6F7A206B6120706F702E >", [(0, b"Nov shmoz ka pop.")]
    )
    list_parsers(rb"<73 686 D6F7A2>", [(0, b"shmoz ")])
    list_parsers(rb"(\400)", [(0, b"")])


def test_invalid_strings_eof():
    list_parsers(rb"(\00", [])
    list_parsers(rb"(abracadab", [])


def inline_parsers(
    data: bytes, expected: tuple, target=b"EI", nexttoken=None, blocksize=16
):
    bp = PSInMemoryParser(data)
    assert bp.get_inline_data(target=target, blocksize=blocksize) == expected
    if nexttoken is not None:
        assert bp.nexttoken() == nexttoken
    with tempfile.NamedTemporaryFile() as tf:
        with open(tf.name, "wb") as outfh:
            outfh.write(data)
        with open(tf.name, "rb") as infh:
            fp = PSFileParser(infh)
            assert fp.get_inline_data(target=target, blocksize=blocksize) == expected
            if nexttoken is not None:
                assert fp.nexttoken() == nexttoken


def test_get_inline_data():
    kwd_eio = KWD(b"EIO")
    kwd_omg = KWD(b"OMG")
    inline_parsers(b"""0123456789""", (-1, b""))
    inline_parsers(b"""0123456789EI""", (10, b"0123456789EI"))
    inline_parsers(
        b"""0123456789EIEIO""", (10, b"0123456789EI"), nexttoken=(12, kwd_eio)
    )
    inline_parsers(b"""012EIEIO""", (3, b"012EI"), nexttoken=(5, kwd_eio), blocksize=4)
    inline_parsers(
        b"""0123012EIEIO""", (7, b"0123012EI"), nexttoken=(9, kwd_eio), blocksize=4
    )
    for blocksize in range(1, 8):
        inline_parsers(
            b"""012EIEIOOMG""",
            (
                3,
                b"012EIEIO",
            ),
            target=b"EIEIO",
            nexttoken=(8, kwd_omg),
            blocksize=blocksize,
        )
