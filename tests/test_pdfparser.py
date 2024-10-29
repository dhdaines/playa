from pathlib import Path

from playa.parser import PDFParser

TESTDIR = Path(__file__).parent.parent / "samples"


class MockDoc:
    def __call__(self):
        return self

    decipher = None


def test_indirect_objects():
    """Verify that indirect objects are parsed properly."""
    with open(TESTDIR / "simple2.pdf", "rb") as infh:
        data = infh.read()
    doc = MockDoc()
    parser = PDFParser(data, doc)
    for obj in parser:
        print(obj)
