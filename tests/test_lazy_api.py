"""
Test the ContentObject API for pages.
"""

import itertools
from pathlib import Path
from typing import cast

import pytest

import playa
from playa.color import PREDEFINED_COLORSPACE, Color
from playa.exceptions import PDFEncryptionError
from playa.utils import Matrix, apply_matrix_pt, get_bound, get_transformed_bound

from .data import ALLPDFS, CONTRIB, PASSWORDS, TESTDIR, XFAILS


@pytest.mark.skipif(not CONTRIB.exists(), reason="contrib samples not present")
def test_content_objects():
    """Ensure that we can produce all the basic content objects."""
    with playa.open(CONTRIB / "2023-06-20-PV.pdf", space="page") as pdf:
        page = pdf.pages[0]
        img = next(page.images)
        assert img.colorspace.name == "ICCBased"
        assert img.colorspace.ncomponents == 3
        ibbox = [round(x) for x in img.bbox]
        assert ibbox == [254, 899, 358, 973]
        mcs_bbox = img.mcs.props["BBox"]
        # Not quite the same, for Reasons!
        assert mcs_bbox == [254.25, 895.5023, 360.09, 972.6]
        for obj in page.paths:
            assert obj.object_type == "path"
            assert len(obj) == 1
            assert len(list(obj)) == 1
        rect = next(obj for obj in page.paths)
        ibbox = [round(x) for x in rect.bbox]
        assert ibbox == [85, 669, 211, 670]
        boxes = []
        texts = []
        for obj in page.texts:
            assert obj.object_type == "text"
            ibbox = [round(x) for x in obj.bbox]
            boxes.append(ibbox)
            texts.append(obj.chars)
            assert len(obj) == sum(1 for glyph in obj)
        # Now there are ... a lot of text objects
        assert boxes[0] == [358, 896, 360, 905]
        assert boxes[-1] == [99, 79, 102, 90]
        assert len(boxes) == 204


@pytest.mark.parametrize("path", ALLPDFS, ids=str)
def test_open_lazy(path: Path) -> None:
    """Open all the documents"""
    if path.name in XFAILS:
        pytest.xfail("Intentionally corrupt file: %s" % path.name)
    passwords = PASSWORDS.get(path.name, [""])
    for password in passwords:
        beach = []
        try:
            with playa.open(path, password=password) as doc:
                for page in doc.pages:
                    for obj in page:
                        try:
                            beach.append((obj.object_type, obj.bbox))
                        except ValueError as e:
                            if "not enough values" in str(e):
                                continue
                            raise e
        except PDFEncryptionError:
            pytest.skip("cryptography package not installed")


def test_uncoloured_tiling() -> None:
    """Verify that we handle uncoloured tiling patterns correctly."""
    with playa.open(TESTDIR / "uncoloured-tiling-pattern.pdf") as pdf:
        paths = pdf.pages[0].paths
        path = next(paths)
        assert path.gstate.ncs == PREDEFINED_COLORSPACE["DeviceRGB"]
        assert path.gstate.ncolor == Color((1.0, 1.0, 0.0), None)
        path = next(paths)
        assert path.gstate.ncolor == Color((0.77, 0.2, 0.0), "P1")
        path = next(paths)
        assert path.gstate.ncolor == Color((0.2, 0.8, 0.4), "P1")
        path = next(paths)
        assert path.gstate.ncolor == Color((0.3, 0.7, 1.0), "P1")
        path = next(paths)
        assert path.gstate.ncolor == Color((0.5, 0.2, 1.0), "P1")


@pytest.mark.skipif(not CONTRIB.exists(), reason="contrib samples not present")
def test_rotated_glyphs() -> None:
    """Verify that we (unlike pdfminer) properly calculate the bbox
    for rotated text."""
    with playa.open(CONTRIB / "issue_495_pdfobjref.pdf") as pdf:
        chars = []
        for text in pdf.pages[0].texts:
            for glyph in text:
                if 1 not in glyph.textstate.line_matrix:
                    if glyph.text is not None:
                        chars.append(glyph.text)
                    x0, y0, x1, y1 = glyph.bbox
                    width = x1 - x0
                    assert width > 6
        assert "".join(chars) == "R18,00"


def test_rotated_text_objects() -> None:
    """Verify specializations of bbox for text."""
    with playa.open(TESTDIR / "rotated.pdf") as pdf:
        # Ensure that the text bbox is the same as the bounds of the
        # glyph bboxes (this will also ensure no side effects)
        for text in pdf.pages[0].texts:
            bbox = text.bbox
            points = []
            for glyph in text:
                x0, y0, x1, y1 = glyph.bbox
                print(glyph.text, ":", glyph.bbox)
                points.append((x0, y0))
                points.append((x1, y1))
            assert bbox == pytest.approx(get_bound(points))


def test_rotated_bboxes() -> None:
    """Verify that rotated bboxes are correctly calculated."""
    points = ((0, 0), (0, 100), (100, 100), (100, 0))
    bbox = (0, 0, 100, 100)
    # Test all possible sorts of CTM
    vals = (-1, -0.5, 0, 0.5, 1)
    for matrix in itertools.product(vals, repeat=4):
        ctm = cast(Matrix, (*matrix, 0, 0))
        gtb = get_transformed_bound(ctm, bbox)
        bound = get_bound((apply_matrix_pt(ctm, p) for p in points))
        assert gtb == bound


def test_operators_in_text() -> None:
    """Verify that other operators are properly ordered in text objects."""
    with playa.open(TESTDIR / "graphics_state_in_text_object.pdf") as pdf:
        page = pdf.pages[0]
        itor = iter(page.texts)
        text = next(itor)
        # Initial CTM
        assert text.ctm[0] == 1.0
        gitor = iter(text)
        a = next(gitor)
        assert a.text == "A"
        assert a.ctm[0] == 1.0
        text = next(itor)
        gitor = iter(text)
        b = next(gitor)
        assert b.text == "B"
        assert b.ctm[0] == 1.5
        assert b.gstate.ncs.name == "DeviceRGB"
        assert b.gstate.ncolor.values == (0.75, 0.25, 0.25)
        text = next(itor)
        gitor = iter(text)
        c = next(gitor)
        assert c.text == "C"

        text = next(itor)
        # Text isn't lazy anymore, the gstate was reset
        assert text.ctm[0] == 1.0
        assert text.chars == "Hello World"
    # Also verify that calling TJ with no actual text still does something
    with playa.open(TESTDIR / "text_side_effects.pdf") as pdf:
        boxes = [[g.bbox for g in t] for t in pdf.pages[0].texts]
        # there was a -5000 that moved it right
        assert boxes[0][0][0] >= 170
        # and a -1000 that moved it right some more
        assert boxes[1][0][0] >= 210
    # Also verify that we get the right ActualText and MCID
    with playa.open(TESTDIR / "actualtext.pdf") as pdf:
        for t in pdf.pages[0].texts:
            if t.mcs and "ActualText" in t.mcs.props:
                assert isinstance(t.mcs.props["ActualText"], bytes)
                assert t.mcs.props["ActualText"].decode("utf-16") == "x̌"
            assert t.mcid == 0
