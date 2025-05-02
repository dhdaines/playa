import itertools
from typing import cast
from playa.utils import transform_bbox, get_bound, apply_matrix_pt, Matrix


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
