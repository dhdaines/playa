"""
Test the classes in data_structures.py
"""

from playa.data_structures import NameTree, NumberTree


def test_name_trees() -> None:
    """Test name trees."""
    nt1 = NameTree(
        {
            "Names": [b"arthur", 1, b"jackson", 3, b"sheds", 4, b"two", 2],
            "Limits": [b"arthur", b"two"],
            "Kids": [{"Names": [b"dead", 33, b"parrot", 66]}],
        }
    )
    assert nt1[b"parrot"] == 66
    assert b"urbanisme" not in nt1
    assert list(nt1) == [b"arthur", b"jackson", b"sheds", b"two", b"dead", b"parrot"]
    assert list(nt1.values()) == [1, 3, 4, 2, 33, 66]


def test_number_trees() -> None:
    """Test number trees."""
    nt1 = NumberTree(
        {
            "Nums": [0, 1, 2, 3, 10, 5],
            "Limits": [0, 10],
            "Kids": [{"Nums": [4, 5, 6, 7]}],
        }
    )
    assert nt1[4] == 5
    assert 11 not in nt1
    assert list(nt1) == [0, 2, 10, 4, 6]
    assert list(nt1.values()) == [1, 3, 5, 5, 7]


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
    assert list(nt.items()) == [
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
    assert (20, 456) in nt.items()
    assert 20 in nt.keys()
    assert 456 in nt.values()


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
    assert list(nt.items()) == [
        (b"bletch", "a"),
        (b"foobie", "b"),
        (b"gargantua", 35),
        (b"gorgon", 42),
        (b"xylophone", 123),
        (b"zzyzx", {"x": "y"}),
    ]
    assert (b"gargantua", 35) in nt.items()
    assert b"gargantua" in nt.keys()
    assert 35 in nt.values()
