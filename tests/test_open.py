"""
Test basic opening and navigation of PDF documents.
"""

from pathlib import Path

import pytest

import playa

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
def test_open(path: Path) -> None:
    """Open all the documents and compare with pdfplumber"""
    from pdfminer.converter import PDFPageAggregator
    from pdfminer.pdfdocument import PDFDocument
    from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
    from pdfminer.pdfpage import PDFPage
    from pdfminer.pdfparser import PDFParser

    def convert_miner(layout):
        for ltitem in layout:
            itype = type(ltitem).__name__.lower()[2:]
            if itype == "figure":
                yield from convert_miner(ltitem)
            else:
                yield ((itype, ltitem.bbox))

    passwords = PASSWORDS.get(path.name, [""])
    for password in passwords:
        miner = []
        with open(path, "rb") as infh:
            try:
                rsrc = PDFResourceManager()
                agg = PDFPageAggregator(rsrc, pageno=1)
                interp = PDFPageInterpreter(rsrc, agg)
                pdf = PDFDocument(PDFParser(infh), password=password)
                for pdfpage in PDFPage.create_pages(pdf):
                    interp.process_page(pdfpage)
                    layout = agg.result
                    if layout is not None:
                        miner.extend(convert_miner(layout))
            except Exception:
                continue

        beach = []
        with playa.open(path, password=password) as doc:
            for page in doc.pages:
                for item in page.layout:
                    bbox = (item["x0"], item["y0"], item["x1"], item["y1"])
                    beach.append((item["object_type"], bbox))

        assert beach == miner


def test_inline_data() -> None:
    with playa.open(TESTDIR / "contrib" / "issue-1008-inline-ascii85.pdf") as doc:
        page = doc.pages[0]
        items = list(page.layout)
        assert len(items) == 456


def test_multiple_contents() -> None:
    with playa.open(TESTDIR / "jo.pdf") as doc:
        page = doc.pages[0]
        assert len(page.contents) > 1
        items = list(page.layout)
        assert len(items) == 898


def test_xobjects() -> None:
    with playa.open(TESTDIR / "encryption/aes-256.pdf", password="foo") as doc:
        for page in doc.pages:
            for item in page.layout:
                print(item)


def test_weakrefs() -> None:
    """Verify that PDFDocument really gets deleted even if we have
    PDFObjRefs hanging around."""
    with playa.open(TESTDIR / "simple5.pdf") as doc:
        ref = doc.catalog["Pages"]
    del doc
    with pytest.raises(RuntimeError):
        _ = ref.resolve()


if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.DEBUG)
    test_xobjects()
