"""
Test the ContentObject API for pages.
"""

from pathlib import Path

import pytest

import playa

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


def test_content_objects():
    """Ensure that we can produce all the basic content objects."""
    with playa.open(TESTDIR / "2023-06-20-PV.pdf") as pdf:
        page = pdf.pages[0]
        img = next(obj for obj in page.objects if obj.object_type == "image")
        assert tuple(img.colorspace[0]) == ("ICCBased", 3)
        ibbox = [round(x) for x in img.bbox]
        assert ibbox == [254, 899, 358, 973]
        mcs_bbox = img.mcs.props["BBox"]
        # Not quite the same, for Reasons!
        assert mcs_bbox == [254.25, 895.5023, 360.09, 972.6]
        for obj in page.objects:
            if obj.object_type == "path":
                assert len(list(obj)) == 1
        rect = next(obj for obj in page.objects if obj.object_type == "path")
        ibbox = [round(x) for x in rect.bbox]
        assert ibbox == [85, 669, 211, 670]
        boxes = []
        texts = []
        for obj in page.objects:
            if obj.object_type == "text":
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
    passwords = PASSWORDS.get(path.name, [""])
    for password in passwords:
        beach = []
        with playa.open(path, password=password) as doc:
            for page in doc.pages:
                for obj in page.objects:
                    beach.append((obj.object_type, obj.bbox))


if __name__ == "__main__":
    test_content_objects()
