"""
Test various font-related things
"""

import json
from typing import List

import playa
import pytest
from playa.content import PathObject
from playa.font import Type3Font
from playa.pdftypes import Rect, dict_value
from playa.utils import get_bound_rects

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
    mildly exotic FontMatrix"""
    with playa.open(TESTDIR / "type3_fonts.pdf") as doc:
        font = doc.get_font(5, dict_value(doc[5]))
        assert font.basefont == "BAAAAA+Open-Sans-Light"
        assert font.fontname == "BAAAAA+Open-Sans-Light"
        # This font's BBox is really something
        assert font.bbox == (-164, 493, 1966, -1569)
        assert isinstance(font, Type3Font)
        assert font.matrix == (0.0004882813, 0, 0, -0.0004882813, 0, 0)
        page = doc.pages[0]
        textor = page.texts
        line1 = next(textor).bbox
        assert line1 == pytest.approx((25.0, 14.274413, 246.586937, 28.370118))
        boxes: List[Rect] = []
        for text in textor:
            bbox = text.bbox
            # They should be mostly adjacent and aligned
            if boxes:
                assert bbox[0] == pytest.approx(boxes[-1][2])
                assert bbox[1] == pytest.approx(boxes[-1][1])
                assert bbox[3] == pytest.approx(boxes[-1][3])
            boxes.append(bbox)
        line2 = get_bound_rects(boxes)
        assert line2 == pytest.approx(
            (25.0, 39.274413, 246.58691507160006, 53.3701175326)
        )


def test_exotic_type3_font_boxes() -> None:
    """Ensure that we get bounding boxes right for Type3 fonts with
    seriously exotic FontMatrix"""
    with playa.open(TESTDIR / "rotated_type3_fonts.pdf") as doc:
        page = doc.pages[0]
        f30 = page.fonts["F5R30"]
        assert f30.matrix == (
            0.000422864,
            -0.000244141,
            -0.000244141,
            -0.000422864,
            0,
            0,
        )
        f30r = page.fonts["F5RM30"]
        assert f30r.matrix == (
            0.000422864,
            0.000244141,
            0.000244141,
            -0.000422864,
            0,
            0,
        )
        # Ensure char bboxes take rotation into account (the fonts are
        # othewise the same)
        assert f30.char_bbox(0) != f30r.char_bbox(0)
        # Ensure TextObject bboxes take rotation into account
        boxes = list(t.bbox for t in page.texts)
        # Rotating backwards moves the left side backwards
        assert boxes[1][0] < boxes[0][0]
        # Rotating forwards moves the right side forwards
        assert boxes[0][2] > boxes[1][2]
        # Height remains (at least approximately) the same
        assert (boxes[0][3] - boxes[0][1]) == pytest.approx(boxes[1][3] - boxes[1][1])


@pytest.mark.parametrize(
    "name",
    ["vertical_writing", "vertical_writing_offset", "simple3", "character_spacing"],
)
def test_glyph_positioning(name: str) -> None:
    """Verify that various more or less exotic aspects of glyph
    positioning are handled correctly."""
    with open(TESTDIR / f"{name}_texts.json", encoding="utf-8") as infh:
        texts = json.load(infh)
    with open(TESTDIR / f"{name}_glyphs.json", encoding="utf-8") as infh:
        glyphs = json.load(infh)
    with playa.open(TESTDIR / f"{name}.pdf", space="default") as doc:
        page = doc.pages[0]
        for text, expected in zip(page.texts, texts):
            assert text.chars == expected["chars"]
            assert text.bbox == tuple(expected["bbox"])
        for glyph, expected in zip(page.glyphs, glyphs):
            assert glyph.text == expected["text"]
            assert glyph.bbox == tuple(expected["bbox"])


@pytest.mark.skipif(not CONTRIB.exists(), reason="contrib samples not present")
def test_fallback_type3_cid2unicode() -> None:
    """Verify that we fall back to standard encoding when a Type3 font
    has nonsense glyph names."""
    with playa.open(CONTRIB / "anonymous_type3_fonts.pdf") as doc:
        wtf = doc.pages[2].fonts["T3_0"]
        # Additionally verify that we correctly use Name as FontName
        # and (if not obviously subset) BaseFont for Type3 fonts
        assert wtf.basefont == "F47"
        assert wtf.fontname == "F47"
        assert list(wtf.decode(b"scienti\xaec")) == [
            (115, "s"),
            (99, "c"),
            (105, "i"),
            (101, "e"),
            (110, "n"),
            (116, "t"),
            (105, "i"),
            (174, "ﬁ"),
            (99, "c"),
        ]


def test_type3_charprocs() -> None:
    """Test iteration over Type3 font programs."""
    with playa.open(TESTDIR / "type3_fonts.pdf") as pdf:
        f5 = pdf.pages[0].fonts["F5"]
        assert isinstance(f5, Type3Font)
        assert f5.resources is None
        assert "g26" in f5.charprocs
        c = next(iter(pdf.pages[0].glyphs))
        assert c.cid == 38
        assert c.text == "C"
        p = next(iter(c))
        assert isinstance(p, PathObject)
        assert p.ctm == pytest.approx(
            (0.0068359382, 0.0, 0.0, 0.0068359382, 25.0, 25.0)
        )
        print(list(p.segments))


def test_bogus_metrics() -> None:
    """Verify that we fix bogus font descriptors with ascent = descent = 0."""
    with playa.open(TESTDIR / "pdf_structure.pdf") as pdf:
        for t in pdf.pages[0].texts:
            x0, y0, x1, y1 = t.bbox
            assert y1 > y0
