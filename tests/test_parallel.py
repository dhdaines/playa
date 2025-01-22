"""Test parallel analysis."""

import pytest

import playa
import playa.document
from playa.page import Page
from playa.worker import in_worker, _get_document
from tests.data import TESTDIR, CONTRIB


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


def get_resources(page: Page) -> dict:
    assert in_worker()
    return page.resources


def test_parallel_references():
    with playa.open(
        TESTDIR / "pdf_structure.pdf", space="default", max_workers=2
    ) as pdf:
        resources, = list(pdf.pages.map(get_resources))
        desc = resources["Font"].resolve()  # should succeed!
        assert "F1" in desc  # should exist!
        assert "F2" in desc
        assert desc["F1"].resolve()["LastChar"] == 17


def get_text(page: Page) -> str:
    return " ".join(x.chars for x in page.texts)


@pytest.mark.skipif(not CONTRIB.exists(), reason="contrib samples not present")
def test_map_parallel():
    with playa.open(CONTRIB / "PSC_Station.pdf", space="default", max_workers=2) as pdf:
        parallel_texts = list(pdf.pages.map(get_text))
    with playa.open(CONTRIB / "PSC_Station.pdf", space="default") as pdf:
        texts = list(pdf.pages.map(get_text))
    assert texts == parallel_texts


if __name__ == '__main__':
    test_parallel_references()
