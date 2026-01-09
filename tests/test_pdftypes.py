"""
Test PDF types and data structures.
"""

import pytest
from playa.data_structures import NameTree, NumberTree
from playa.pdftypes import (
    LIT,
    LITERAL_CRYPT,
    ContentStream,
    ObjRef,
    bool_value,
    decipher_all,
    decompress_corrupted,
    dict_value,
    float_value,
    keyword_name,
    list_value,
    matrix_value,
    num_value,
    point_value,
    rect_value,
    resolve1,
    resolve_all,
    str_value,
)
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


def test_errors() -> None:
    """Verify that we get various errors in pdftypes functions."""
    with pytest.raises(TypeError):
        keyword_name("NOT A KEYWORD DO NOT EAT")
    with pytest.raises(ValueError):
        ObjRef(None, 0)
    assert ObjRef(None, 1) == ObjRef(None, 1)
    assert ObjRef(None, 1) != ObjRef(123, 1)
    assert ObjRef(None, 1).resolve(123) == 123
    assert decipher_all(lambda *args: b"SOMETHING", 1, 0, b"") == b""
    with pytest.raises(TypeError):
        bool_value(b"Norwegian Blue")
    with pytest.raises(TypeError):
        float_value(b"Romanus eunt domus")
    float_value(123.456)  # just for the coverage
    with pytest.raises(TypeError):
        num_value(b"NaN")
    with pytest.raises(TypeError):
        str_value(42)
    with pytest.raises(TypeError):
        list_value({"not": "a list"})
    with pytest.raises(TypeError):
        dict_value(["not", "a dict"])
    with pytest.raises(ValueError):
        point_value((1, 2, 3))  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        point_value((32, "skidoo"))  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        rect_value((1, 2, 3))  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        rect_value((32, "skidoo", 4, 5))  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        matrix_value((1, 2, 3))  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        matrix_value((32, "skidoo", 4, 5, 6, 7))  # type: ignore[arg-type]
    broken_image = ContentStream(
        {"ColorSpace": LIT("NotAColorSpace")},
        rawdata=b"IRRELEVANT!",
    )
    with pytest.raises(ValueError):
        _ = broken_image.colorspace


def test_filters() -> None:
    """Exercise various filter types in streams"""
    stream = ContentStream({"Filter": [LITERAL_CRYPT]}, rawdata=b"")
    with pytest.raises(NotImplementedError):
        stream.decode()
    stream = ContentStream({"Filter": [LIT("FlateDecode")]}, rawdata=b"TOTAL NONSENSE")
    with pytest.raises(ValueError):
        stream.decode(strict=True)
    assert stream.buffer == b""
    stream = ContentStream(
        {"Filter": [LIT("LZWDecode")]}, rawdata=b"\x80\x0b\x60\x50\x22\x0c\x0c\x85\x01"
    )
    assert stream.buffer == b"\x2d\x2d\x2d\x2d\x2d\x41\x2d\x2d\x2d\x42"
    stream = ContentStream(
        {"Filter": [LIT("RunLengthDecode")]},
        rawdata=b"\x05123456\xfa7\x04abcde\x80junk",
    )
    assert stream.buffer == b"1234567777777abcde"
    stream = ContentStream(
        {"Filter": LIT("FlateDecode"), "DecodeParms": {"Predictor": 3}}, rawdata=b""
    )
    with pytest.raises(NotImplementedError):
        stream.decode()


def test_decompress_corrupted(caplog) -> None:
    """Verify that we can recover from missing CRC, truncated, or
    corrupted flate streams."""
    rawdata = (
        b'x\x9c\x0b\xf1\x0fq\xf4Qp\xf4sQ\x08\r\tq\rR\xf0\xf3\xf7\x0bv\x05"\x00R'
        b"\xe8\x06\xb5"
    )
    # Verify that decompress_corrupted works even on uncorrupted streams
    assert decompress_corrupted(rawdata) == b"TOTAL AND UTTER NONSENSE"
    # Or if the CRC is partially missing
    assert decompress_corrupted(rawdata[:-1]) == b"TOTAL AND UTTER NONSENSE"
    # Verify that decode will fail if we remove the trailer in strict mode
    stream = ContentStream({"Filter": LIT("FlateDecode")}, rawdata=rawdata[:-5])
    with pytest.raises(ValueError):
        stream.decode(strict=True)
    # Remove the trailer in non-strict mode
    stream = ContentStream({"Filter": LIT("FlateDecode")}, rawdata=rawdata[:-5])
    assert stream.buffer == b"TOTAL AND UTTER NONSENSE"
    # Remove the CRC in non-strict mode
    stream = ContentStream({"Filter": LIT("FlateDecode")}, rawdata=rawdata[:-3])
    assert stream.buffer == b"TOTAL AND UTTER NONSENSE"
    # Truncate the stream in non-strict mode
    stream = ContentStream({"Filter": LIT("FlateDecode")}, rawdata=rawdata[:-8])
    caplog.clear()
    assert stream.buffer == b"TOTAL AND UTTER NON"
    assert "incomplete" in caplog.text
    # Remove some random bytes (no error as the data is still a valid
    # flate stream, just the CRC is wrong)
    stream = ContentStream(
        {"Filter": LIT("FlateDecode")},
        rawdata=(rawdata[:5] + rawdata[7:10] + rawdata[11:]),
    )
    assert stream.buffer == b"TOT AL UTTER NONSENSE"
    # Insert some random bytes, now we will lose data for real
    bogusdata = bytearray(rawdata)
    bogusdata[7:10] = b"HI!"
    stream = ContentStream({"Filter": LIT("FlateDecode")}, rawdata=bogusdata)
    caplog.clear()
    assert stream.buffer == b""
    assert "Data loss" in caplog.text
    # Test the adjustible buffer size
    assert decompress_corrupted(bogusdata) == b""
    assert decompress_corrupted(bogusdata, 1) == b"TOTAHdd"
    assert decompress_corrupted(bogusdata, 2) == b"TOTAHdd"
    assert decompress_corrupted(bogusdata, 4) == b"TOTAHdd"
    assert decompress_corrupted(bogusdata, 8) == b"TOTAH"
    assert decompress_corrupted(bogusdata, 16) == b""
