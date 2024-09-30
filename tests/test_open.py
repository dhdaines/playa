"""
Test basic opening and navigation of PDF documents.
"""

from pathlib import Path

import pytest

import playa
from playa.converter import PDFPageAggregator

# These APIs will go away soon
from playa.pdfinterp import PDFPageInterpreter, PDFResourceManager

TESTDIR = Path(__file__).parent.parent / "samples"
ALLPDFS = TESTDIR.glob("**/*.pdf")
PASSWORDS = {
    "base.pdf": ["foo"],
    "rc4-40.pdf": ["foo"],
    "rc4-128.pdf": ["foo"],
    "aes-128.pdf": ["foo"],
    "aes-128-m.pdf": ["foo"],
    "aes-256.pdf": ["foo"],
    "aes-256-m.pdf": ["foo"],
    "aes-256-r6.pdf": ["usersecret", "ownersecret"],
}


@pytest.mark.parametrize("path", ALLPDFS, ids=str)
def test_open(path: Path):
    """Open all the documents"""
    passwords = PASSWORDS.get(path.name, [""])
    for password in passwords:
        with playa.open(TESTDIR / path, password=password) as pdf:
            pass
        assert pdf.parser.doc is None


def test_inline_data():
    # No, there's no easy way to unit test PDFContentParser directly.
    # The necessary mocking would be useless considering that I will
    # shortly demolish these redundant and confusing APIs.
    with playa.open(TESTDIR / "contrib" / "issue-1008-inline-ascii85.pdf") as doc:
        # Seriously WTF is all this... just to get a page... OMG
        rsrc = PDFResourceManager()
        agg = PDFPageAggregator(rsrc, pageno=1)
        interp = PDFPageInterpreter(rsrc, agg)
        page = next(doc.get_pages())
        interp.process_page(page)


def test_multiple_contents():
    # See above...
    with playa.open(TESTDIR / "jo.pdf") as doc:
        rsrc = PDFResourceManager()
        agg = PDFPageAggregator(rsrc, pageno=1)
        interp = PDFPageInterpreter(rsrc, agg)
        page = next(doc.get_pages())
        assert len(page.contents) > 1
        interp.process_page(page)


if __name__ == "__main__":
    test_open(TESTDIR / "simple5.pdf")
