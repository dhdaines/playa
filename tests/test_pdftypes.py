"""
Test PDF types and data structures.
"""

from playa.data_structures import NameTree, NumberTree
from playa.runlength import rldecode

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


NAMETREE1 = {
    "Kids": [
        {"Names": [b"bletch", "a", b"foobie", "b"], "Limits": [b"bletch", b"foobie"]},
        {
            "Kids": [
                {
                    "Names": [b"gargantua", 35, b"gorgon", 42],
                    "Limits": [b"gargantua", b"gorgon"],
                },
                {
                    "Names": [b"xylophone", 123, b"zzyzx", {"x": "y"}],
                    "Limits": [b"xylophone", b"zzyzx"],
                },
            ],
            "Limits": [b"gargantua", b"zzyzx"],
        },
    ]
}


def test_name_tree():
    """Test NameTrees."""
    nt = NameTree(NAMETREE1)
    assert b"bletch" in nt
    assert b"zzyzx" in nt
    assert b"gorgon" in nt
    assert nt[b"zzyzx"] == {"x": "y"}
    assert list(nt) == [
        (b"bletch", "a"),
        (b"foobie", "b"),
        (b"gargantua", 35),
        (b"gorgon", 42),
        (b"xylophone", 123),
        (b"zzyzx", {"x": "y"}),
    ]


def test_rle():
    large_white_image_encoded = bytes([129, 255] * (3 * 3000 * 4000 // 128))
    _ = rldecode(large_white_image_encoded)
