"""
Test pdfminer.six replacement functionality.
"""

import playa
from playa.miner import extract_page, extract, LAParams, LTFigure
from pdfminer.converter import PDFPageAggregator
from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
from pdfminer.pdfpage import PDFPage
from pdfminer.high_level import extract_pages as pdfminer_extract_pages
from tests.data import CONTRIB
import pytest


@pytest.mark.skipif(not CONTRIB.exists(), reason="contrib samples not present")
def test_miner_extract():
    path = CONTRIB / "Rgl-1314-2021-Z-en-vigueur-20240823.pdf"
    with playa.open(path, space="page") as pdf:
        # OMFG as usual
        resource_manager = PDFResourceManager()
        device = PDFPageAggregator(resource_manager)
        interpreter = PDFPageInterpreter(resource_manager, device)
        for idx, (playa_page, pdfminer_page) in enumerate(
            zip(pdf.pages, PDFPage.get_pages(pdf._fp))
        ):
            # Otherwise pdfminer.six is just too darn slow
            if idx == 20:
                break
            paves_ltpage = extract_page(playa_page)
            interpreter.process_page(pdfminer_page)
            pdfminer_ltpage = device.get_result()
            for pv, pm in zip(paves_ltpage, pdfminer_ltpage):
                # Because in its infinite wisdom these have no __eq__
                assert str(pv) == str(pm)


@pytest.mark.skipif(not CONTRIB.exists(), reason="contrib samples not present")
def test_extract():
    path = CONTRIB / "Rgl-1314-2021-Z-en-vigueur-20240823.pdf"
    for idx, (paves_ltpage, pdfminer_ltpage) in enumerate(
        zip(extract(path, LAParams()), pdfminer_extract_pages(path))
    ):
        # Otherwise pdfminer.six is just too darn slow
        if idx == 20:
            break
        for pv, pm in zip(paves_ltpage, pdfminer_ltpage):
            # Because in its infinite wisdom these have no __eq__
            assert str(pv) == str(pm)


@pytest.mark.skipif(not CONTRIB.exists(), reason="contrib samples not present")
def test_serialization():
    """Ensure stuff is reserialized properly"""
    path = CONTRIB / "PSC_Station.pdf"
    pages = extract(path, LAParams())
    first = next(pages)
    for item in first:
        if isinstance(item, LTFigure):
            img = next(iter(item))
            # We have a image stream
            assert len(img.stream.buffer) == 52692
            assert img.colorspace.name == "ICCBased"
            # It has a colorspace, which has a stream as an indirect
            # object reference, which we can resolve
            icc = img.colorspace.spec[1].resolve()
            assert len(icc.buffer) == 3144
        # Probably we could test some other things too?


if __name__ == "__main__":
    test_extract()
