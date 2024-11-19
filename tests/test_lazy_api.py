"""
Test the ContentObject API for pages.
"""

from pathlib import Path

import playa

TESTDIR = Path(__file__).parent.parent / "samples"


def test_content_objects():
    with playa.open(TESTDIR / "2023-06-20-PV.pdf") as pdf:
        page = pdf.pages[0]
        objects_by_type = {}
        for obj in page.objects:
            objects_by_type.setdefault(obj.object_type, []).append(obj)
        assert len(objects_by_type["image"]) == 1
        img = objects_by_type["image"][0]
        assert tuple(img.colorspace[0]) == ("ICCBased", 3)
        ibbox = [round(x) for x in img.bbox]
        assert ibbox == [254, 899, 358, 973]
        mcs_bbox = img.mcs.props["BBox"]
        # Not quite the same, for Reasons!
        assert mcs_bbox == [254.25, 895.5023, 360.09, 972.6]


if __name__ == "__main__":
    test_content_objects()
