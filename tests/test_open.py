"""
Test basic opening and navigation of PDF documents.
"""

import pytest

try:
    import pdfminer
except ImportError:
    pdfminer = None  # type: ignore
import playa

from .data import CONTRIB, TESTDIR


def test_weakrefs() -> None:
    """Verify that PDFDocument really gets deleted even if we have
    PDFObjRefs hanging around."""
    with playa.open(TESTDIR / "simple5.pdf") as doc:
        ref = doc.catalog["Pages"]
    del doc
    with pytest.raises(RuntimeError):
        _ = ref.resolve()


@pytest.mark.skipif(not CONTRIB.exists(), reason="contrib samples not present")
def test_spaces() -> None:
    """Test different coordinate spaces."""
    with playa.open(CONTRIB / "issue-1181.pdf", space="page") as doc:
        page = doc.pages[0]
        page_box = next(iter(page)).bbox
    with playa.open(CONTRIB / "issue-1181.pdf", space="default") as doc:
        page = doc.pages[0]
        user_box = next(iter(page)).bbox
    assert page_box[1] == pytest.approx(user_box[1] - page.mediabox[1])
    with playa.open(CONTRIB / "issue-1181.pdf", space="screen") as doc:
        page = doc.pages[0]
        screen_box = next(iter(page)).bbox
    # BBoxes are normalied, so top is 1 for screen and 3 for page
    assert screen_box[3] == pytest.approx(page.height - page_box[1])
    assert screen_box[3] == pytest.approx(page.height - page_box[1])


def test_tiff_predictor() -> None:
    with playa.open(TESTDIR / "test_pdf_with_tiff_predictor.pdf") as doc:
        image = next(doc.pages[0].images)
        # Decoded TIFF: 600 x 600 + a header
        assert len(image.stream.buffer) == 360600
