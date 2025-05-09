"""
Test various font-related things
"""

from typing import List

import playa
import pytest
from playa.pdftypes import dict_value
from playa.utils import get_bound, Point

from .data import CONTRIB, TESTDIR


def test_implicit_encoding_type1() -> None:
    """Test implicit encodings for Type1 fonts."""
    with playa.open(TESTDIR / "simple5.pdf") as doc:
        page = doc.pages[0]
        fonts = page.resources.get("Font")
        assert fonts is not None
        assert isinstance(fonts, dict)
        for name, desc in fonts.items():
            font = doc.get_font(desc.objid, desc.resolve())
            assert font is not None
            if 147 in font.encoding:
                assert font.encoding[147] == "quotedblleft"


def test_custom_encoding_core() -> None:
    """Test custom encodings for core fonts."""
    with playa.open(TESTDIR / "core_font_encodings.pdf") as doc:
        page = doc.pages[0]
        # Did we get the encoding right? (easy)
        assert (
            page.extract_text_untagged()
            == """\
Ç’est ça mon Bob
Un peu plus à droite"""
        )
        # Did we get the *glyphs* right? (harder)
        boxes = list(t.bbox for t in page.texts)
        assert boxes[0] == pytest.approx((100.0, 74.768, 289.408, 96.968))
        assert boxes[1] == pytest.approx((150.0, 110.768, 364.776, 132.968))


@pytest.mark.skipif(not CONTRIB.exists(), reason="contrib samples not present")
def test_implicit_encoding_cff() -> None:
    with playa.open(CONTRIB / "implicit_cff_encoding.pdf") as doc:
        page = doc.pages[0]
        fonts = page.resources.get("Font")
        assert fonts is not None
        assert isinstance(fonts, dict)
        for name, desc in fonts.items():
            font = doc.get_font(desc.objid, desc.resolve())
            assert font.encoding
        # Verify fallback to StandardEncoding
        t = page.extract_text()
        assert t.strip() == "Part I\nClick here to access Part II \non hp.com."


@pytest.mark.skipif(not CONTRIB.exists(), reason="contrib samples not present")
def test_implicit_encoding_cff_issue91() -> None:
    """Ensure that we can properly parse some CFF programs."""
    with playa.open(CONTRIB / "issue-91.pdf") as doc:
        page = doc.pages[0]
        fonts = page.resources.get("Font")
        assert fonts is not None
        assert isinstance(fonts, dict)
        for name, desc in fonts.items():
            font = doc.get_font(desc.objid, desc.resolve())
            # Font should have an encoding
            assert font.encoding
            # It should *not* be the standard encoding
            assert 90 not in font.encoding


def test_type3_font_boxes() -> None:
    """Ensure that we get bounding boxes right for Type3 fonts with
    mildly exotic FontMatrix (FIXME: it could be much more exotic than
    this)"""
    with playa.open(TESTDIR / "type3_fonts.pdf") as doc:
        font = doc.get_font(5, dict_value(doc[5]))
        # This font's BBox is really something
        assert font.bbox == (-164, 493, 1966, -1569)
        page = doc.pages[0]
        textor = page.texts
        line1 = next(textor).bbox
        assert line1 == pytest.approx(
            (25.0, 14.274413, 246.586937, 28.370118)
        )
        # Now for the individual characters
        points: List[Point] = []
        for text in textor:
            bbox = text.bbox
            # They should be mostly adjacent and aligned
            if points:
                assert bbox[0] == pytest.approx(points[-1][0])
                assert bbox[1] == pytest.approx(points[-2][1])
                assert bbox[3] == pytest.approx(points[-1][1])
            points.append((bbox[0], bbox[1]))
            points.append((bbox[2], bbox[3]))
        line2 = get_bound(points)
        assert line2 == pytest.approx(
            (25.0, 39.274413, 246.58691507160006, 53.3701175326)
        )
