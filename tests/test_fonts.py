"""
Test various font-related things
"""

from .data import CONTRIB, TESTDIR

import pytest

import playa


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
        assert boxes[0] == pytest.approx((100.0, 72.968, 289.408, 96.968))
        assert boxes[1] == pytest.approx((150.0, 108.968, 364.776, 132.968))


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
