"""
Test the actual parser.
"""

import logging

from playa.document import Document
from playa.parser import (
    InlineImage,
    Lexer,
    ObjectParser,
)
from playa.pdftypes import (
    KWD,
    LIT,
    ObjRef,
)

logger = logging.getLogger(__name__)

STREAMDATA = b"""
/Hello
<< /Type/Catalog/Outlines 2 0 R /Pages 3 0 R >>
[ 1 0 R ]
(foo (bar) baz...)
null null null
4 0 R
"""


def test_objects():
    """Test the basic object stream parser."""
    parser = ObjectParser(STREAMDATA)
    objects = list(parser)
    assert objects == [
        (1, LIT("Hello")),
        (
            8,
            {
                "Type": LIT("Catalog"),
                "Outlines": ObjRef(None, 2),
                "Pages": ObjRef(None, 3),
            },
        ),
        (56, [ObjRef(None, 1)]),
        (66, b"foo (bar) baz..."),
        (85, None),
        (90, None),
        (95, None),
        # Note unparsed indirect object reference
        (100, 4),
        (102, 0),
        (104, KWD(b"R")),
    ]


INLINEDATA1 = b"""
BI /L 42 ID
012345678901234567890123456789012345678901
EI
BI /Length 30 /Filter /A85 ID


<^BVT:K:=9<E)pd;BS_1:/aSV;ag~>



EI
BI
/Foo (bar)
ID
VARIOUS UTTER NONSENSE
EI
BI
/F /AHx
ID\r4f 4d 47575446\r\n\r\nEI
BI /F /AHx ID 4f4d47575446EI
BI ID(OMG)(WTF)
EI
BI
/F /A85
ID
<^BVT:K:=9<E)pd;BS_1:/aSV;ag~>
EI
BI
/F /A85
ID
<^BVT:K:=9<E)pd;BS_1:/aSV;ag~
>
EI
BI /F /A85 ID<^BVT:K:=9<E)pd;BS_1:/aSV;ag~>EI
BI
/OMG (WTF)
ID
BLAHEIBLAHBLAH\rEI
BI ID
OLD MACDONALD\rEIEIO
EI
BI ID OLDMACDONALDEIEIO EI
BI ID
OLDMACDONALDEIEIOEI
(hello world)
"""


def test_inline_images():
    parser = ObjectParser(INLINEDATA1)
    pos, img = next(parser)
    assert isinstance(img, InlineImage)
    assert img.buffer == b"012345678901234567890123456789012345678901"
    pos, img = next(parser)
    assert isinstance(img, InlineImage)
    assert img.buffer == b"VARIOUS UTTER NONSENSE"
    pos, img = next(parser)
    assert isinstance(img, InlineImage)
    assert img.attrs["Foo"] == b"bar"
    assert img.rawdata == b"VARIOUS UTTER NONSENSE"
    pos, img = next(parser)
    assert isinstance(img, InlineImage)
    assert img.buffer == b"OMGWTF"
    pos, img = next(parser)
    assert isinstance(img, InlineImage)
    assert img.buffer == b"OMGWTF"
    pos, img = next(parser)
    assert isinstance(img, InlineImage)
    assert img.buffer == b"(OMG)(WTF)"
    pos, img = next(parser)
    assert isinstance(img, InlineImage)
    assert img.buffer == b"VARIOUS UTTER NONSENSE"
    pos, img = next(parser)
    assert isinstance(img, InlineImage)
    assert img.buffer == b"VARIOUS UTTER NONSENSE"
    pos, img = next(parser)
    assert isinstance(img, InlineImage)
    assert img.buffer == b"VARIOUS UTTER NONSENSE"
    pos, img = next(parser)
    assert isinstance(img, InlineImage)
    assert img.buffer == b"BLAHEIBLAHBLAH"
    pos, img = next(parser)
    assert isinstance(img, InlineImage)
    assert img.buffer == b"OLD MACDONALD\rEIEIO"
    pos, img = next(parser)
    assert isinstance(img, InlineImage)
    assert img.buffer == b"OLDMACDONALDEIEIO"
    pos, img = next(parser)
    assert isinstance(img, InlineImage)
    assert img.buffer == b"OLDMACDONALDEIEIO"


def test_cached_inline_images():
    doc = Document(b"")
    first = list(ObjectParser(INLINEDATA1, doc, streamid=0))
    second = list(ObjectParser(INLINEDATA1, doc, streamid=0))
    assert first == second
    third = list(ObjectParser(INLINEDATA1, doc, streamid=1))
    assert first != third


def test_reverse_solidus():
    """Test the handling of useless backslashes that are not escapes."""
    parser = Lexer(rb"(OMG\ WTF \W \T\ F)")
    assert next(parser) == (0, b"OMG WTF W T F")


def test_number_syntax():
    """Verify that all types of number objects are accepted."""
    numbers = [1, 12, 1.2, 1.0, 0.2, 12.34, 12.0, 0.34]
    texts = b"1 12 1.2 1. .2 12.34 12. .34"
    objs = [obj for _, obj in Lexer(texts)]
    assert objs == numbers
    plus_texts = b" ".join((b"+" + x) for x in texts.split())
    objs = [obj for _, obj in Lexer(plus_texts)]
    assert objs == numbers
    minus_texts = b" ".join(b"-" + x for x in texts.split())
    objs = [-obj for _, obj in Lexer(minus_texts)]
    assert objs == numbers
