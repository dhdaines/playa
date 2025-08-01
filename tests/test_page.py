"""
Page-related tests
"""

import pytest

import playa
from .data import TESTDIR


def test_rotation() -> None:
    datadir = TESTDIR / "rotation"
    with playa.open(datadir / "0.pdf") as pdf:
        hello = next(pdf.pages[0].texts)
        assert hello.bbox == pytest.approx((100, 74.768, 224.008, 96.968))
    with playa.open(datadir / "90.pdf") as pdf:
        hello = next(pdf.pages[0].texts)
        assert hello.bbox == pytest.approx((792 - 96.968, 100, 792 - 74.768, 224.008))
    with playa.open(datadir / "180.pdf") as pdf:
        hello = next(pdf.pages[0].texts)
        assert hello.bbox == pytest.approx(
            (612 - 224.008, 792 - 96.968, 612 - 100, 792 - 74.768)
        )
    with playa.open(datadir / "270.pdf") as pdf:
        hello = next(pdf.pages[0].texts)
        assert hello.bbox == pytest.approx((74.768, 612 - 224.008, 96.968, 612 - 100))
        # And verify that we can update the rotation
        pdf.pages[0].set_initial_ctm("screen", 0)
        hello = next(pdf.pages[0].texts)
        assert hello.bbox == pytest.approx((100, 74.768, 224.008, 96.968))
        # And verify that rotation is normalized
        pdf.pages[0].set_initial_ctm("screen", -90)
        hello = next(pdf.pages[0].texts)
        assert hello.bbox == pytest.approx((74.768, 612 - 224.008, 96.968, 612 - 100))


def test_translation() -> None:
    datadir = TESTDIR / "rotation"
    with playa.open(datadir / "0mb.pdf") as pdf:
        hello = next(pdf.pages[0].texts)
        # screen device space so no effect on Y coords
        assert hello.bbox == pytest.approx((90, 74.768, 214.008, 96.968))
    with playa.open(datadir / "0.pdf", space="page") as pdf:
        hello = next(pdf.pages[0].texts)
        assert hello.bbox == pytest.approx((100, 695.032, 224.008, 717.232))
    with playa.open(datadir / "0mb.pdf", space="page") as pdf:
        hello = next(pdf.pages[0].texts)
        assert hello.bbox == pytest.approx((90, 675.032, 214.008, 697.232))
    with playa.open(datadir / "90mb.pdf") as pdf:
        hello = next(pdf.pages[0].texts)
        # Just trust me, these are correct
        assert hello.bbox == pytest.approx((675.032, 90, 697.232, 214.008))
    with playa.open(datadir / "180mb.pdf") as pdf:
        hello = next(pdf.pages[0].texts)
        # Just trust me, these are correct
        assert hello.bbox == pytest.approx((387.992, 675.032, 512, 697.232))
    with playa.open(datadir / "270mb.pdf") as pdf:
        hello = next(pdf.pages[0].texts)
        # No change here because we cropped the other corner
        assert hello.bbox == pytest.approx((74.768, 612 - 224.008, 96.968, 612 - 100))
