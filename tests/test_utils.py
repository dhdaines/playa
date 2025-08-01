import itertools
from typing import cast

from playa.data import asobj
from playa.utils import (Matrix, apply_matrix_pt, decode_text, get_bound,
                         normalize_rect, transform_bbox)


def test_rotated_bboxes() -> None:
    """Verify that rotated bboxes are correctly calculated."""
    points = ((0, 0), (0, 100), (100, 100), (100, 0))
    bbox = (0, 0, 100, 100)
    # Test all possible sorts of CTM
    vals = (-1, -0.5, 0, 0.5, 1)
    for matrix in itertools.product(vals, repeat=4):
        ctm = cast(Matrix, (*matrix, 0, 0))
        bound = get_bound((apply_matrix_pt(ctm, p) for p in points))
        assert transform_bbox(ctm, bbox) == bound


def test_decode_text() -> None:
    """Make sure we can always decode text, even if it is nonsense."""
    assert (
        decode_text(
            b"\xfe\xffMicrosoft\xae Word 2010; modified using iText 2.1.7 by 1T3XT"
        )
        == "Microsoft\xae Word 2010; modified using iText 2.1.7 by 1T3XT"
    )
    assert decode_text(b"\xff\xfeW\x00T\x00F\x00-\x001\x006\x00") == "WTF-16"
    # Doesn't really belong here but let's test asobj_bytes too
    assert asobj(
        b"\xfe\xffMicrosoft\xae Word 2010; modified using iText 2.1.7 by 1T3XT"
    ) == (
        "base64:/v9NaWNyb3NvZnSuIFdvcmQgMjAxMDsgbW9kaWZpZWQgdXNpbmcgaVRleHQgMi4xLj"
        "cgYnkgMVQzWFQ="
    )
    assert asobj(b"\xff\xfeW\x00T\x00F\x00-\x001\x006\x00") == "WTF-16"


def test_normalize_rect() -> None:
    """Normalize rects"""
    r1 = (1, 1, 5, 5)
    assert normalize_rect(r1) == r1
    r2 = (5, 5, 1, 1)
    assert normalize_rect(r2) == r1
