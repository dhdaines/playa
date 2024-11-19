"""
Test the ContentObject API for pages.
"""

from pathlib import Path

import playa

TESTDIR = Path(__file__).parent.parent / "samples"


def test_content_objects():
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
        for obj in page.objects:
            if obj.object_type == "text":
                ibbox = [round(x) for x in obj.bbox]
                boxes.append(ibbox)
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


if __name__ == "__main__":
    test_content_objects()
