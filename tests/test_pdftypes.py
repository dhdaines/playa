"""
Test PDF types and data structures.
"""

from playa.data_structures import NumberTree

NUMTREE1 = {
    "Kids": [
        {"Nums": [1, "a", 3, "b", 7, "c"], "Limits": [1, 7]},
        {
            "Kids": [
                {"Nums": [8, 123, 9, {"x": "y"}, 10, "forty-two"], "Limits": [8, 10]},
                {"Nums": [11, "zzz", 12, "xxx", 15, "yyy"], "Limits": [11, 15]},
            ],
            "Limits": [8, 15],
        },
        {"Nums": [20, 456], "Limits": [20, 20]},
    ]
}


def test_number_tree():
    """Test NumberTrees."""
    nt = NumberTree(NUMTREE1)
    assert 15 in nt
    assert 20 in nt
    assert nt[20] == 456
    assert nt[9] == {"x": "y"}
    assert list(nt) == [
        (1, "a"),
        (3, "b"),
        (7, "c"),
        (8, 123),
        (9, {"x": "y"}),
        (10, "forty-two"),
        (11, "zzz"),
        (12, "xxx"),
        (15, "yyy"),
        (20, 456),
    ]
