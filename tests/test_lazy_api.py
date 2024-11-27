"""
Test the ContentObject API for pages.
"""

from pathlib import Path

import pytest

import playa
from playa.color import PREDEFINED_COLORSPACE, Color
from playa.exceptions import PDFEncryptionError

TESTDIR = Path(__file__).parent.parent / "samples"
ALLPDFS = TESTDIR.glob("**/*.pdf")
PASSWORDS = {
    "base.pdf": ["foo"],
    "rc4-40.pdf": ["foo"],
    "rc4-128.pdf": ["foo"],
    "aes-128.pdf": ["foo"],
    "aes-128-m.pdf": ["foo"],
    "aes-256.pdf": ["foo"],
    "aes-256-m.pdf": ["foo"],
    "aes-256-r6.pdf": ["usersecret", "ownersecret"],
}
XFAILS = {
    "bogus-stream-length.pdf",
}


def test_content_objects():
    """Ensure that we can produce all the basic content objects."""
    with playa.open(TESTDIR / "2023-06-20-PV.pdf", space="page") as pdf:
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
        assert boxes == [
            [358, 896, 360, 905],
            [71, 681, 490, 895],
            [71, 667, 214, 679],
            [71, 615, 240, 653],
            [71, 601, 232, 613],
            [71, 549, 289, 587],
            [71, 535, 248, 547],
            [71, 469, 451, 521],
            [451, 470, 454, 481],
            [71, 79, 499, 467],
        ]


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
                        beach.append((obj.object_type, obj.bbox))
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


def test_rotated_glyphs() -> None:
    """Verify that we (unlike pdfminer) properly calculate the bbox
    for rotated text."""
    with playa.open(TESTDIR / "contrib" / "issue_495_pdfobjref.pdf") as pdf:
        chars = []
        for text in pdf.pages[0].texts:
            for glyph in text:
                if 1 not in glyph.textstate.line_matrix:
                    chars.append(glyph.text)
                    x0, y0, x1, y1 = glyph.bbox
                    width = x1 - x0
                    assert width > 6
        assert "".join(chars) == "R18,00"


if __name__ == "__main__":
    test_content_objects()
