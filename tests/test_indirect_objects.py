from pathlib import Path

import pytest

from playa.parser import (
    LIT,
    ContentStream,
    IndirectObjectParser,
    ObjectStreamParser,
    PDFSyntaxError,
)

TESTDIR = Path(__file__).parent.parent / "samples"


DATA = b"""
(foo)
1 0 obj <</Type/Catalog/Outlines 2 0 R >> endobj
2 0 obj << /Type /Outlines /Count 0 >> endobj
(bar) 42 /Baz
5 0 obj << /Length 21 >>
stream
150 250 m
150 350 l
S
endstream
endobj
"""


def test_indirect_objects():
    """Verify that indirect objects are parsed properly."""
    parser = IndirectObjectParser(DATA)
    positions, objs = zip(*list(parser))
    assert len(objs) == 3
    assert objs[0].objid == 1
    assert isinstance(objs[0].obj, dict) and objs[0].obj["Type"] == LIT("Catalog")
    assert objs[1].objid == 2
    assert isinstance(objs[1].obj, dict) and objs[1].obj["Type"] == LIT("Outlines")
    assert objs[2].objid == 5
    assert isinstance(objs[2].obj, ContentStream)
    stream = objs[2].obj
    assert stream.rawdata == b"150 250 m\n150 350 l\nS\n"


DATA2 = b"""
5 0 obj << /Length 21 >>
stream
150 250 m
150 350 l
S
A BUNCH OF EXTRA CRAP!!!
endstream
endobj
"""

DATA2A = b"""
5 0 obj << /Length 21 >>
stream
150 250 m
150 350 l
Sendstream
endobj
"""


DATA2B = b"""
5 0 obj << /Length 22 >>
stream
150 250 m
150 350 l
S
endstream
endobj
"""


def test_streams():
    """Test the handling of content streams."""
    # sec 7.3.8.1: There should be an end-of-line
    # marker after the data and before endstream; this
    # marker shall not be included in the stream length.
    parser = IndirectObjectParser(DATA, strict=True)
    positions, objs = zip(*list(parser))
    assert isinstance(objs[2].obj, ContentStream)
    stream = objs[2].obj
    assert stream.rawdata == b"150 250 m\n150 350 l\nS"

    parser = IndirectObjectParser(DATA2)
    positions, objs = zip(*list(parser))
    assert isinstance(objs[0].obj, ContentStream)
    stream = objs[0].obj
    assert stream.rawdata == b"150 250 m\n150 350 l\nS\nA BUNCH OF EXTRA CRAP!!!\n"

    parser = IndirectObjectParser(DATA2, strict=True)
    with pytest.raises(PDFSyntaxError) as e:
        positions, objs = zip(*list(parser))
        assert "Integer" in e

    # Accept the case where there isn't an EOL before endstream
    parser = IndirectObjectParser(DATA2A, strict=True)
    positions, objs = zip(*list(parser))
    assert isinstance(objs[0].obj, ContentStream)
    stream = objs[0].obj
    assert stream.rawdata == b"150 250 m\n150 350 l\nS"

    # Accept the case where the EOL is included in the
    # stream length (it will be in the stream in that case)
    parser = IndirectObjectParser(DATA2B, strict=True)
    positions, objs = zip(*list(parser))
    assert isinstance(objs[0].obj, ContentStream)
    stream = objs[0].obj
    assert stream.rawdata == b"150 250 m\n150 350 l\nS\n"


DATA3 = rb"""18 0 obj
<</Type/ObjStm/N 9/First 60/Length 755>>
stream
16 0 19 50 20 100 15 236 11 303 12 393 13 637 14 659 17 673
<</P 15 0 R/S/P/Type/StructElem/K[ 0] /Pg 3 0 R>>
<</P 15 0 R/S/P/Type/StructElem/K[ 1] /Pg 3 0 R>>
<</P 15 0 R/S/Figure/Alt(pdfplumber on github\n\na screen capture of the github page for pdfplumber) /Type/StructElem/K[ 2] /Pg 3 0 R>>
<</P 11 0 R/S/Document/Type/StructElem/K[ 16 0 R 19 0 R 20 0 R] >>
<</Type/StructTreeRoot/RoleMap 12 0 R/ParentTree 13 0 R/K[ 15 0 R] /ParentTreeNextKey 1>>
<</Footnote/Note/Endnote/Note/Textbox/Sect/Header/Sect/Footer/Sect/InlineShape/Sect/Annotation/Sect/Artifact/Sect/Workbook/Document/Worksheet/Part/Macrosheet/Part/Chartsheet/Part/Dialogsheet/Part/Slide/Part/Chart/Sect/Diagram/Figure/Title/H1>>
<</Nums[ 0 17 0 R] >>
<</Names[] >>
[ 16 0 R 19 0 R 20 0 R]
endstream
endobj
"""

DATA4 = rb"""1 0 obj
<</Type/ObjStm/N 2/First 7/Length 17>>
stream
1 0 2 4
333

666
endstream
endobj
"""


def test_object_streams():
    """Test the parsing of object streams."""
    _, stmobj = next(IndirectObjectParser(DATA3))
    parser = ObjectStreamParser(stmobj.obj)
    objects = list(parser)
    assert all(obj.genno == 0 for _, obj in objects)
    objids = [obj.objid for _, obj in objects]
    assert objids == [16, 19, 20, 15, 11, 12, 13, 14, 17]
    assert objects[-2][1].obj == {"Names": []}

    # Offsets are slightly incorrect but we get the objects anyway!
    _, stmobj = next(IndirectObjectParser(DATA4))
    parser = ObjectStreamParser(stmobj.obj)
    objects = list(parser)
    assert objects[0][1].obj == 333
    assert objects[1][1].obj == 666
