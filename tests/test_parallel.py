"""Test parallel analysis."""

import operator
from typing import Dict, List

import playa
import pytest
from playa.pdftypes import PDFObject, PSLiteral, PSKeyword
from playa.page import Page, XObjectObject
from playa.worker import (
    _deref_document,
    _deref_page,
    _get_document,
    _init_worker,
    _init_worker_buffer,
    _ref_document,
    _ref_page,
    _set_document,
    in_worker,
)

from tests.data import CONTRIB, TESTDIR


def has_one_true_pdf() -> int:
    assert in_worker()
    doc = _get_document()
    assert doc is not None
    assert doc.space == "default"
    return len(doc.pages)


def test_open_parallel():
    with playa.open(
        TESTDIR / "pdf_structure.pdf", space="default", max_workers=4
    ) as pdf:
        future = pdf._pool.submit(has_one_true_pdf)
        assert future.result() == 1
    with playa.open(
        TESTDIR / "pdf_structure.pdf", space="default", max_workers=None
    ) as pdf:
        future = pdf._pool.submit(has_one_true_pdf)
        assert future.result() == 1


def test_parse_parallel():
    with open(TESTDIR / "pdf_structure.pdf", "rb") as infh:
        buffer = infh.read()
    with playa.parse(buffer, space="default", max_workers=4) as pdf:
        future = pdf._pool.submit(has_one_true_pdf)
        assert future.result() == 1
    with playa.parse(buffer, space="default", max_workers=None) as pdf:
        future = pdf._pool.submit(has_one_true_pdf)
        assert future.result() == 1


def test_parallel_references():
    with playa.open(
        TESTDIR / "pdf_structure.pdf", space="default", max_workers=2
    ) as pdf:
        # Force parallelism
        pdf._ncpus = 0
        (resources,) = pdf.pages.map(operator.attrgetter("resources"))
        desc = resources["Font"].resolve()  # should succeed!
        assert "F1" in desc  # should exist!
        assert "F2" in desc
        assert desc["F1"].resolve()["LastChar"] == 17


def get_props(page: Page) -> Dict[str, PDFObject]:
    element = page.structure[0]
    return {} if element is None else element.props


def get_contents(page: Page) -> List[PDFObject]:
    return list(page.contents)


def test_parallel_symbols():
    """Verify that literal/keyword symbols can be passed between processes."""
    with playa.open(
        TESTDIR / "pdf_structure.pdf", space="default", max_workers=2
    ) as pdf:
        # Force parallelism
        pdf._ncpus = 0
        props1 = [get_props(p) for p in pdf.pages]
        props2 = list(pdf.pages.map(get_props))
        assert isinstance(props1[0]["Type"], PSLiteral)
        assert props1[0]["Type"] is props2[0]["Type"]

        contents1 = [get_contents(p) for p in pdf.pages]
        contents2 = list(pdf.pages.map(get_contents))
        assert isinstance(contents1[0][3], PSKeyword)
        assert contents1[0][3] is contents2[0][3]


def get_xobjs(page: Page) -> List[XObjectObject]:
    return list(page.xobjects)


@pytest.mark.skipif(not CONTRIB.exists(), reason="contrib samples not present")
def test_parallel_xobjects():
    # Verify that page references (used in XObjects) also work
    with playa.open(CONTRIB / "basicapi.pdf", space="default", max_workers=2) as pdf:
        # Force parallelism
        pdf._ncpus = 0
        for page in pdf.pages:
            for xobj in page.xobjects:
                assert xobj.page.page_idx == page.page_idx
        for idx, xobjs in enumerate(pdf.pages.map(get_xobjs)):
            for xobj in xobjs:
                assert xobj.page.page_idx == idx


def get_text(page: Page) -> str:
    return " ".join(x.chars for x in page.texts)


def in_worker_page(page: Page) -> int:
    return in_worker()


def test_map_not_parallel():
    """Verify that we will not execute in parallel for a single page."""
    # This document has only one page
    with playa.open(
        TESTDIR / "pdf_structure.pdf", space="default", max_workers=2
    ) as pdf:
        in_workers = list(pdf.pages.map(in_worker_page))
        assert in_workers == [False]


@pytest.mark.skipif(not CONTRIB.exists(), reason="contrib samples not present")
def test_map_parallel():
    # Verify also that a longer document will execute in parallel!
    with playa.open(CONTRIB / "PSC_Station.pdf", space="default", max_workers=2) as pdf:
        in_workers = list(pdf.pages.map(in_worker_page))
        assert all(in_workers)
    with playa.open(CONTRIB / "PSC_Station.pdf", space="default", max_workers=2) as pdf:
        parallel_texts = list(pdf.pages.map(get_text))
    with playa.open(CONTRIB / "PSC_Station.pdf", space="default") as pdf:
        texts = list(pdf.pages.map(get_text))
    assert texts == parallel_texts
    with playa.open(CONTRIB / "PSC_Station.pdf", space="default", max_workers=2) as pdf:
        parallel_texts = list(pdf.pages[3:8].map(get_text))
        print(parallel_texts)
        assert parallel_texts != texts


def test_worker():
    """Ensure coverage of worker functions (even though they are tested above)."""
    _init_worker(123456, TESTDIR / "pdf_structure.pdf", "", {})
    pdf1 = _get_document()
    assert pdf1
    assert in_worker()
    docref = _ref_document(pdf1)
    assert docref == 123456
    assert _deref_document(docref) is pdf1
    pageref = _ref_page(pdf1.pages[0])
    assert pageref == (123456, 0)
    assert _deref_page(pageref) is pdf1.pages[0]
    _set_document(None, 0)
    assert not in_worker()
    with pytest.raises(RuntimeError):
        _deref_document(docref)
    with playa.open(TESTDIR / "image_structure.pdf") as pdf2:
        _set_document(pdf2, 654321)
        assert _get_document() is pdf2
    with open(TESTDIR / "image_structure.pdf", "rb") as fh:
        _init_worker_buffer(654321, fh.read(), "", {})
        assert _get_document()
    _set_document(None, 0)
    pdf3 = playa.open(TESTDIR / "image_structure.pdf")
    docref = _ref_document(pdf3)
    assert _deref_document(docref) is pdf3
    del pdf3
    with pytest.raises(RuntimeError):
        _deref_document(docref)


if __name__ == "__main__":
    test_parallel_xobjects()
