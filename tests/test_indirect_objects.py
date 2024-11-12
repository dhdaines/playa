from pathlib import Path

import pytest

from playa.parser import LIT, ContentStream, IndirectObjectParser

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
    with pytest.raises(TypeError) as e:
        positions, objs = zip(*list(parser))
        assert "Integer" in e
