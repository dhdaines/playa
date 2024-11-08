from pathlib import Path

from playa.parser import ObjectParser, ContentStream, LIT

TESTDIR = Path(__file__).parent.parent / "samples"


class MockDoc:
    def __call__(self):
        return self

    decipher = None


DATA = b"""
(foo)
1 0 obj <</Type/Catalog/Outlines 2 0 R >> endobj
2 0 obj << /Type /Outlines /Count 0 >> endobj
(bar) 42 /Baz
5 0 obj << /Length 22 >>
stream
150 250 m
150 350 l
S
endstream
endobj
"""


def test_indirect_objects():
    """Verify that indirect objects are parsed properly."""
    doc = MockDoc()
    parser = ObjectParser(DATA, doc)
    positions, objs = zip(*list(parser))
    assert len(objs) == 3
    assert objs[0].objid == 1
    assert isinstance(objs[0].obj, dict) and objs[0].obj["Type"] == LIT("Catalog")
    assert objs[1].objid == 2
    assert isinstance(objs[1].obj, dict) and objs[1].obj["Type"] == LIT("Outlines")
    assert objs[2].objid == 5
    assert isinstance(objs[2].obj, ContentStream)
