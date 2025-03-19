"""
Test PDF types and data structures.
"""

from playa.data_structures import NameTree, NumberTree
from playa.pdftypes import ObjRef, resolve1, resolve_all
from playa.runlength import rldecode
from playa.worker import _ref_document

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


def test_resolve_all():
    """See if `resolve_all` will really `resolve` them `all`."""

    # Use a mock document, it just needs to suppot __getitem__
    class MockDoc(dict):
        pass

    mockdoc = MockDoc({42: "hello"})
    mockdoc[41] = ObjRef(_ref_document(mockdoc), 42)
    mockdoc[40] = ObjRef(_ref_document(mockdoc), 41)
    assert mockdoc[41].resolve() == "hello"
    assert resolve1(mockdoc[41]) == "hello"
    assert mockdoc[40].resolve() == mockdoc[41]
    assert resolve_all(mockdoc[40]) == "hello"
    mockdoc[39] = [mockdoc[40], mockdoc[41]]
    assert resolve_all(mockdoc[39]) == ["hello", "hello"]
    mockdoc[38] = ["hello", ObjRef(_ref_document(mockdoc), 38)]
    # This resolves the *list*, not the indirect object, so its second
    # element will get expanded once into a new list.
    ouf = resolve_all(mockdoc[38])
    assert ouf[0] == "hello"
    assert ouf[1][1] is mockdoc[38]
    # Whereas in this case we are expanding the reference itself.
    fou = resolve_all(mockdoc[38][1])
    assert fou[1] is mockdoc[38]
    # Likewise here, we have to dig a bit to see the circular
    # reference.  Your best option is not to use resolve_all ;-)
    mockdoc[30] = ["hello", ObjRef(_ref_document(mockdoc), 31)]
    mockdoc[31] = ["hello", ObjRef(_ref_document(mockdoc), 30)]
    bof = resolve_all(mockdoc[30])
    assert bof[1][1][1] is mockdoc[31]
    fob = resolve_all(mockdoc[30][1])
    assert fob[1][1] is mockdoc[31]
