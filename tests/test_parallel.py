"""Test parallel analysis."""

import pytest

import playa
import playa.document
from playa.page import Page
from tests.data import TESTDIR, CONTRIB


def has_one_true_pdf() -> int:
    assert playa.document.__pdf is not None
    assert playa.document.__pdf.space == "default"
    return len(playa.document.__pdf.pages)


def test_open_parallel():
    with playa.open(
        TESTDIR / "pdf_structure.pdf", space="default", max_workers=4
    ) as pdf:
        future = pdf._pool.submit(has_one_true_pdf)
        assert future.result() == 1


def get_text(page: Page) -> str:
    return " ".join(x.chars for x in page.texts)


@pytest.mark.skipif(not CONTRIB.exists(), reason="contrib samples not present")
def test_map_parallel():
    with playa.open(CONTRIB / "PSC_Station.pdf", space="default", max_workers=2) as pdf:
        parallel_texts = list(pdf.pages.map(get_text))
    with playa.open(CONTRIB / "PSC_Station.pdf", space="default") as pdf:
        texts = list(pdf.pages.map(get_text))
    assert texts == parallel_texts
