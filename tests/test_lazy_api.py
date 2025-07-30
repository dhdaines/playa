"""
Test the ContentObject API for pages.
"""

from pathlib import Path
from typing import Iterable

import playa
import pytest
from playa.color import PREDEFINED_COLORSPACE, Color
from playa.content import ContentObject
from playa.exceptions import PDFEncryptionError
from playa.utils import get_bound
from playa.image import get_one_image

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
            # We cannot directly iterate over path segments becuase
            # they aren't ContentObjects
            assert len(obj) == 0
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
        assert boxes[0] == [358, 896, 360, 909]
        assert boxes[-1] == [99, 79, 102, 94]
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
                if 1 not in text.line_matrix:
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


def test_text_displacement() -> None:
    with playa.open(TESTDIR / "text_displacement.pdf") as pdf:
        x, y = (100.0, 200.0)
        for text in pdf.pages[0].texts:
            cx, cy = text.origin
            assert cx == pytest.approx(x)
            assert cy == pytest.approx(y)
            dx, dy = text.displacement
            print(text.chars, cx, cy, dx, dy)
            x += dx
            y += dy
        x, y = (100.0, 200.0)
        for glyph in pdf.pages[0].glyphs:
            cx, cy = glyph.origin
            assert cx == pytest.approx(x)
            assert cy == pytest.approx(y)
            dx, dy = glyph.displacement
            print(glyph.text, cx, cy, dx, dy)
            x += dx
            y += dy


TEXTOBJS = [
    {
        "chars": "foo",
        "bbox": [0.0, -4.968, 33.36, 17.232],
    },
    {
        "chars": "A",
        "bbox": [50.0, 95.032, 66.00800000000001, 117.232],
    },
    {
        "chars": "B",
        "bbox": [99.012, 142.548, 123.024, 175.848],
    },
    {
        "chars": "C",
        "bbox": [184.536, 213.822, 223.524, 263.772],
    },
    {
        "chars": "D",
        "bbox": [223.524, 213.822, 262.51200000000006, 263.772],
    },
    {
        "chars": "BAR",
        "bbox": [262.51200000000006, 213.822, 373.53600000000006, 263.772],
    },
    {
        "chars": "FOO",
        "bbox": [0.0, -11.178, 117.01799999999999, 38.772],
    },
    {
        "chars": "Hello World",
        "bbox": [0.0, 370.032, 124.00800000000004, 392.23199999999997],
    },
]


def test_operators_in_text() -> None:
    """Verify that other operators are properly ordered in text objects."""
    # Verify consistent handling of graphics state and text state
    with playa.open(
        TESTDIR / "graphics_state_in_text_object.pdf", space="default"
    ) as pdf:
        page = pdf.pages[0]
        for text, obj in zip(page.texts, TEXTOBJS):
            assert text.chars == obj["chars"]
            assert text.bbox == pytest.approx(obj["bbox"])
            if text.chars == "B":
                assert text.ctm[0] == 1.5
                assert text.gstate.ncs.name == "DeviceRGB"
                assert text.gstate.ncolor.values == (0.75, 0.25, 0.25)

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


def test_broken_xobjects() -> None:
    """Verify that we tolerate missing attributes on XObjects."""
    with playa.open(TESTDIR / "broken_xobjects.pdf") as doc:
        page = doc.pages[0]
        for img in page.images:
            assert img.srcsize == (1, 1)
            assert img.bbox == (25.0, 154.0, 237.0, 275.0)
        for xobj in page.xobjects:
            assert xobj.bbox == page.cropbox


@pytest.mark.skipif(not CONTRIB.exists(), reason="contrib samples not present")
def test_glyph_bboxes() -> None:
    """Verify that we don't think all fonts are 1000 units high."""
    with playa.open(CONTRIB / "issue-79" / "test.pdf") as doc:
        page = doc.pages[0]
        texts = page.texts
        t = next(texts)
        _, zh_y0, _, zh_y1 = t.bbox
        t = next(texts)
        _, en_y0, _, en_y1 = t.bbox
        assert en_y0 <= zh_y0
        assert en_y1 >= zh_y1


@pytest.mark.parametrize("name", ["rotated.pdf", "character_spacing.pdf"])
def test_glyph_properties(name: str) -> None:
    """Check that the newfangled glyph properties do what they should."""
    # Ensure that origin and displacement reflect actual positions
    for space in "default", "page", "screen":
        with playa.open(TESTDIR / name, space=space) as pdf:
            for text in pdf.pages[0].texts:
                next_origin = text.origin
                for glyph in text:
                    assert glyph.origin == pytest.approx(next_origin)
                    gx, gy = glyph.origin
                    dx, dy = glyph.displacement
                    next_origin = (gx + dx, gy + dy)
                    assert glyph.size > 0
                assert text.size > 0


@pytest.mark.skipif(not CONTRIB.exists(), reason="contrib samples not present")
def test_jbig2(tmp_path) -> None:
    """Verify that we can extract JBIG2 images."""
    with playa.open(CONTRIB / "pdf-with-jbig2.pdf") as pdf:
        img = next(pdf.pages[0].images)
        hyppath = tmp_path / "XIPLAYER0"
        hyppath = get_one_image(img.stream, hyppath)
        assert hyppath.suffix == ".jb2"
        refdata = (CONTRIB / "XIPLAYER0.jb2").read_bytes()
        hypdata = hyppath.read_bytes()
        assert refdata == hypdata


@pytest.mark.skipif(not CONTRIB.exists(), reason="contrib samples not present")
def test_indexed_images(tmp_path) -> None:
    """Verify that we can extract (at least some) Indexed images
    correctly."""
    with playa.open(CONTRIB / "issue-1062-filters.pdf") as pdf:
        (img,) = pdf.pages[0].images
        outpath = tmp_path / "page1"
        outpath = get_one_image(img.stream, outpath)
        assert outpath.suffix == ".ppm"
        refpath = CONTRIB / "page1-0-00005.ppm"
        hyp = outpath.read_bytes()
        ref = refpath.read_bytes()
        # Testing equality is ABSURDLY STUPIDLY SLOW when it fails
        assert len(hyp) == len(ref)
    with playa.open(CONTRIB / "inline-indexed-images.pdf") as pdf:
        imgs = list(pdf.pages[0].images)
        assert len(imgs) == 7


@pytest.mark.skipif(not CONTRIB.exists(), reason="contrib samples not present")
def test_ccitt(tmp_path) -> None:
    """Verify that we can extract CCITT compressed images correctly."""
    for name in "ccitt-default-k.pdf", "ccitt_EndOfBlock_false.pdf":
        with playa.open(CONTRIB / name) as pdf:
            for img in pdf.pages[0].images:
                get_one_image(img.stream, tmp_path / img.xobjid)
                with open(CONTRIB / "ccitt" / f"{img.xobjid}.pbm", "rb") as fh:
                    ref = fh.read()
                with open(tmp_path / f"{img.xobjid}.pbm", "rb") as fh:
                    hyp = fh.read()
                assert ref == hyp


def test_finalize() -> None:
    """At least minimally verify that finalize() does something useful."""
    with playa.open(TESTDIR / "graphics_state_in_text_object.pdf") as pdf:

        def compare_objects(page: playa.Page, objects: Iterable[ContentObject]):
            for ref, hyp in zip(page, objects):
                for ref_child, hyp_child in zip(ref, hyp):
                    assert ref_child == hyp_child
                # Do this after as we need internal properties
                # (_next_glyph_offset) to exist
                assert ref == hyp

        # First demonstrate "DO NOT do this" from README.md
        with pytest.raises(AssertionError):
            compare_objects(pdf.pages[0], list(pdf.pages[0]))
        # All clear!
        compare_objects(pdf.pages[0], [obj.finalize() for obj in pdf.pages[0]])
