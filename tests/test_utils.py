import itertools
from typing import cast

import pytest
from playa import asobj
from playa.document import PageLabels
from playa.pdftypes import LIT
from playa.utils import (
    IDENTITY_MAPPING,
    Matrix,
    apply_matrix_norm,
    apply_matrix_pt,
    decode_text,
    format_int_alpha,
    format_int_roman,
    get_bound,
    normalize_rect,
    transform_bbox,
)


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


def test_format_romans() -> None:
    """Chic, des Romains."""
    with pytest.raises(ValueError):
        format_int_roman(4000)
    with pytest.raises(ValueError):
        format_int_roman(-1)
    with pytest.raises(ValueError):
        format_int_roman(0)

    romans = ["", *(format_int_roman(x) for x in range(1, 4000))]
    assert romans[9] == "ix"
    for x in range(10, 50):
        assert romans[x].startswith("x")
    for x in range(50, 90):
        assert romans[x].startswith("l")
    for x in range(90, 100):
        assert romans[x].startswith("xc")
    for x in range(100, 500):
        assert romans[x].startswith("c")
    for x in range(500, 900):
        assert romans[x].startswith("d")
    for x in range(900, 1000):
        assert romans[x].startswith("cm")

    romans2 = [
        "",
        *(PageLabels._format_page_label(x, LIT("r")) for x in range(1, 4000)),
    ]
    assert romans2 == romans

    ROMANS = ["", *(PageLabels._format_page_label(x, LIT("R")) for x in range(1, 4000))]
    assert ROMANS == [x.upper() for x in romans]


def test_format_alphas() -> None:
    """Vendeurs de thermopompes."""

    with pytest.raises(ValueError):
        format_int_alpha(0)

    two_letters = (26 + 1) * 26
    alphas = ["", *(format_int_alpha(x) for x in range(1, two_letters + 1))]
    assert alphas[-1] == "zz"
    assert format_int_alpha(two_letters + 1) == "aaa"

    alphas2 = [
        "",
        *(
            PageLabels._format_page_label(x, LIT("a"))
            for x in range(1, two_letters + 1)
        ),
    ]
    assert alphas2 == alphas

    ALPHAS = [
        "",
        *(
            PageLabels._format_page_label(x, LIT("A"))
            for x in range(1, two_letters + 1)
        ),
    ]
    assert ALPHAS == [x.upper() for x in alphas]


def test_normalize_rect() -> None:
    """Normalize rects"""
    r1 = (1, 1, 5, 5)
    assert normalize_rect(r1) == r1
    r2 = (5, 5, 1, 1)
    assert normalize_rect(r2) == r1


def test_apply_matrix_norm() -> None:
    m = (1, 0.75, -0.75, 1, 3, 4)
    x, y = (123, 456)
    nx, ny = apply_matrix_norm(m, (x, y))
    zx, zy = apply_matrix_pt(m, (0, 0))
    px, py = apply_matrix_pt(m, (x, y))
    assert nx == px - zx
    assert ny == py - zy


def test_identity_mapping() -> None:
    assert IDENTITY_MAPPING[42] == 42
    assert IDENTITY_MAPPING["xviii"] == "xviii"
