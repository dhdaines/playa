"""Miscellaneous Routines."""

import itertools
import string
from typing import (
    TYPE_CHECKING,
    Iterable,
    Iterator,
    List,
    Mapping,
    Tuple,
    TypeVar,
    Union,
)

from playa.pdftypes import PDFObject, Point, Rect, Matrix, dict_value, str_value

if TYPE_CHECKING:
    from mypy_extensions import u8
    from playa.content import GraphicState
    from playa.font import Font


def paeth_predictor(left: int, above: int, upper_left: int) -> int:
    # From http://www.libpng.org/pub/png/spec/1.2/PNG-Filters.html
    # Initial estimate
    p = left + above - upper_left
    # Distances to a,b,c
    pa = abs(p - left)
    pb = abs(p - above)
    pc = abs(p - upper_left)

    # Return nearest of a,b,c breaking ties in order a,b,c
    if pa <= pb and pa <= pc:
        return left
    elif pb <= pc:
        return above
    else:
        return upper_left


def apply_tiff_predictor(
    colors: int, columns: int, bitspercomponent: int, data: bytes
) -> bytes:
    """Reverse the effect of the TIFF predictor 2

    Documentation: https://www.itu.int/itudoc/itu-t/com16/tiff-fx/docs/tiff6.pdf
    (Section 14, page 64)
    """
    if bitspercomponent != 8:
        error_msg = f"Unsupported `bitspercomponent': {bitspercomponent}"
        raise ValueError(error_msg)
    bpp = colors * (bitspercomponent // 8)
    nbytes = columns * bpp
    # Incredibly, this is faster than bytearray (with and without mypyc)
    buf: List["u8"] = []
    for scanline_i in range(0, len(data), nbytes):
        for i in range(nbytes):
            new_value = data[scanline_i + i]
            if i >= bpp:
                new_value = (new_value + buf[scanline_i + i - bpp]) & 255
            buf.append(new_value)
    return bytes(buf)


def apply_png_predictor(
    pred: int,
    colors: int,
    columns: int,
    bitspercomponent: int,
    data: bytes,
) -> bytes:
    """Reverse the effect of the PNG predictor

    Documentation: http://www.libpng.org/pub/png/spec/1.2/PNG-Filters.html
    """
    if bitspercomponent not in (8, 1):
        msg = "Unsupported `bitspercomponent': %d" % bitspercomponent
        raise ValueError(msg)

    nbytes = (colors * columns * bitspercomponent + 7) // 8
    bpp = (colors * bitspercomponent + 7) // 8
    # Likewise, this is *twice as fast* as bytearray...
    buf: List["u8"] = []
    line_above: List["u8"] = [0] * nbytes
    raw: List["u8"] = [0] * nbytes
    for scanline_i in range(0, len(data), nbytes + 1):
        filter_type = data[scanline_i]
        line_encoded = data[scanline_i + 1 : scanline_i + 1 + nbytes]

        if filter_type == 0:
            # Filter type 0: None
            raw[:] = line_encoded

        elif filter_type == 1:
            # Filter type 1: Sub
            # To reverse the effect of the Sub() filter after decompression,
            # output the following value:
            #   Raw(x) = Sub(x) + Raw(x - bpp)
            # (computed mod 256), where Raw() refers to the bytes already
            #  decoded.
            for j, sub_x in enumerate(line_encoded):
                if j < bpp:
                    raw[j] = sub_x
                else:
                    raw[j] = (sub_x + raw[j - bpp]) & 255

        elif filter_type == 2:
            # Filter type 2: Up
            # To reverse the effect of the Up() filter after decompression,
            # output the following value:
            #   Raw(x) = Up(x) + Prior(x)
            # (computed mod 256), where Prior() refers to the decoded bytes of
            # the prior scanline.
            for j, up_x in enumerate(line_encoded):
                prior_x = line_above[j]
                raw[j] = (up_x + prior_x) & 255

        elif filter_type == 3:
            # Filter type 3: Average
            # To reverse the effect of the Average() filter after
            # decompression, output the following value:
            #    Raw(x) = Average(x) + floor((Raw(x-bpp)+Prior(x))/2)
            # where the result is computed mod 256, but the prediction is
            # calculated in the same way as for encoding. Raw() refers to the
            # bytes already decoded, and Prior() refers to the decoded bytes of
            # the prior scanline.
            for j, average_x in enumerate(line_encoded):
                prior_x = line_above[j]
                if j < bpp:
                    raw_x_bpp = 0
                else:
                    raw_x_bpp = raw[j - bpp]
                raw[j] = (average_x + (raw_x_bpp + prior_x) // 2) & 255

        elif filter_type == 4:
            # Filter type 4: Paeth
            # To reverse the effect of the Paeth() filter after decompression,
            # output the following value:
            #    Raw(x) = Paeth(x)
            #             + PaethPredictor(Raw(x-bpp), Prior(x), Prior(x-bpp))
            # (computed mod 256), where Raw() and Prior() refer to bytes
            # already decoded. Exactly the same PaethPredictor() function is
            # used by both encoder and decoder.
            for j, paeth_x in enumerate(line_encoded):
                if j - bpp < 0:
                    raw_x_bpp = 0
                    prior_x_bpp = 0
                else:
                    raw_x_bpp = raw[j - bpp]
                    prior_x_bpp = line_above[j - bpp]
                prior_x = line_above[j]
                paeth = paeth_predictor(raw_x_bpp, prior_x, prior_x_bpp)
                raw[j] = (paeth_x + paeth) & 255

        else:
            raise ValueError("Unsupported predictor value: %d" % filter_type)

        buf.extend(raw)
        raw, line_above = line_above, raw
    return bytes(buf)


def normalize_rect(r: Rect) -> Rect:
    (x0, y0, x1, y1) = r
    if x1 < x0:
        x1, x0 = x0, x1
    if y1 < y0:
        y1, y0 = y0, y1
    return x0, y0, x1, y1


def mult_matrix(m1: Matrix, m0: Matrix) -> Matrix:
    (a1, b1, c1, d1, e1, f1) = m1
    (a0, b0, c0, d0, e0, f0) = m0
    """Returns the multiplication of two matrices."""
    return (
        a0 * a1 + c0 * b1,
        b0 * a1 + d0 * b1,
        a0 * c1 + c0 * d1,
        b0 * c1 + d0 * d1,
        a0 * e1 + c0 * f1 + e0,
        b0 * e1 + d0 * f1 + f0,
    )


def translate_matrix(m: Matrix, v: Point) -> Matrix:
    """Pre-translates a matrix by `v == (dx, dy)`.

    Specifically this translates the *input space* of the matrix by
    `(dx, dy)`, so:

       (apply_matrix_pt(matrix, (x + dx, y + dy))
        == apply_matrix_pt(translate_matrix(matrix,
                                            (dx, dy)),
                           x, y))

    For all `x, y, dx, dy`.
    """
    (a, b, c, d, e, f) = m
    (x, y) = v
    return a, b, c, d, x * a + y * c + e, x * b + y * d + f


def apply_matrix_pt(m: Matrix, v: Point) -> Point:
    """Applies a matrix to a point."""
    (a, b, c, d, e, f) = m
    (x, y) = v
    return a * x + c * y + e, b * x + d * y + f


def apply_matrix_norm(m: Matrix, v: Point) -> Point:
    """Equivalent to apply_matrix_pt(M, (p,q)) - apply_matrix_pt(M, (0,0))"""
    (a, b, c, d, e, f) = m
    (p, q) = v
    return a * p + c * q, b * p + d * q


#  Utility functions
_T = TypeVar("_T")


def get_bound(pts: Iterable[Point]) -> Rect:
    """Compute a minimal rectangle that covers all the points.

    Raises:
      ValueError on empty input (as there is no bounding box).
    """
    xs, ys = zip(*pts)
    x0 = min(xs)
    y0 = min(ys)
    x1 = max(xs)
    y1 = max(ys)
    return x0, y0, x1, y1


def get_bound_rects(boxes: Iterable[Rect]) -> Rect:
    """Compute the union of bounding boxes (which need not be normalized)

    Raises:
      ValueError on empty input (as there is no bounding box).
    """
    return get_bound(
        itertools.chain.from_iterable(((x0, y0), (x1, y1)) for x0, y0, x1, y1 in boxes)
    )


def transform_bbox(matrix: Matrix, bbox: Rect) -> Rect:
    """Transform a bounding box and return the rectangle that covers
    the points of the resulting shape."""
    x0, y0, x1, y1 = bbox
    if matrix[0] * matrix[2] < 0 or matrix[1] * matrix[3] < 0:
        # Corners of untransformed bbox are not preserved
        return get_bound(
            (
                apply_matrix_pt(matrix, (x0, y0)),
                apply_matrix_pt(matrix, (x0, y1)),
                apply_matrix_pt(matrix, (x1, y1)),
                apply_matrix_pt(matrix, (x1, y0)),
            )
        )
    return get_bound(
        (
            apply_matrix_pt(matrix, (x0, y0)),
            apply_matrix_pt(matrix, (x1, y1)),
        )
    )


def choplist(n: int, seq: Iterable[_T]) -> Iterator[Tuple[_T, ...]]:
    """Groups every n elements of the list."""
    r = []
    for x in seq:
        r.append(x)
        if len(r) == n:
            yield tuple(r)
            r = []


def nunpack(s: bytes, default: int = 0) -> int:
    """Unpacks variable-length unsigned integers (big endian)."""
    length = len(s)
    if not length:
        return default
    else:
        return int.from_bytes(s, byteorder="big", signed=False)


PDFDocEncoding = "".join(
    chr(x)
    for x in (
        0x0000,
        0x0001,
        0x0002,
        0x0003,
        0x0004,
        0x0005,
        0x0006,
        0x0007,
        0x0008,
        0x0009,
        0x000A,
        0x000B,
        0x000C,
        0x000D,
        0x000E,
        0x000F,
        0x0010,
        0x0011,
        0x0012,
        0x0013,
        0x0014,
        0x0015,
        0x0017,
        0x0017,
        0x02D8,
        0x02C7,
        0x02C6,
        0x02D9,
        0x02DD,
        0x02DB,
        0x02DA,
        0x02DC,
        0x0020,
        0x0021,
        0x0022,
        0x0023,
        0x0024,
        0x0025,
        0x0026,
        0x0027,
        0x0028,
        0x0029,
        0x002A,
        0x002B,
        0x002C,
        0x002D,
        0x002E,
        0x002F,
        0x0030,
        0x0031,
        0x0032,
        0x0033,
        0x0034,
        0x0035,
        0x0036,
        0x0037,
        0x0038,
        0x0039,
        0x003A,
        0x003B,
        0x003C,
        0x003D,
        0x003E,
        0x003F,
        0x0040,
        0x0041,
        0x0042,
        0x0043,
        0x0044,
        0x0045,
        0x0046,
        0x0047,
        0x0048,
        0x0049,
        0x004A,
        0x004B,
        0x004C,
        0x004D,
        0x004E,
        0x004F,
        0x0050,
        0x0051,
        0x0052,
        0x0053,
        0x0054,
        0x0055,
        0x0056,
        0x0057,
        0x0058,
        0x0059,
        0x005A,
        0x005B,
        0x005C,
        0x005D,
        0x005E,
        0x005F,
        0x0060,
        0x0061,
        0x0062,
        0x0063,
        0x0064,
        0x0065,
        0x0066,
        0x0067,
        0x0068,
        0x0069,
        0x006A,
        0x006B,
        0x006C,
        0x006D,
        0x006E,
        0x006F,
        0x0070,
        0x0071,
        0x0072,
        0x0073,
        0x0074,
        0x0075,
        0x0076,
        0x0077,
        0x0078,
        0x0079,
        0x007A,
        0x007B,
        0x007C,
        0x007D,
        0x007E,
        0x0000,
        0x2022,
        0x2020,
        0x2021,
        0x2026,
        0x2014,
        0x2013,
        0x0192,
        0x2044,
        0x2039,
        0x203A,
        0x2212,
        0x2030,
        0x201E,
        0x201C,
        0x201D,
        0x2018,
        0x2019,
        0x201A,
        0x2122,
        0xFB01,
        0xFB02,
        0x0141,
        0x0152,
        0x0160,
        0x0178,
        0x017D,
        0x0131,
        0x0142,
        0x0153,
        0x0161,
        0x017E,
        0x0000,
        0x20AC,
        0x00A1,
        0x00A2,
        0x00A3,
        0x00A4,
        0x00A5,
        0x00A6,
        0x00A7,
        0x00A8,
        0x00A9,
        0x00AA,
        0x00AB,
        0x00AC,
        0x0000,
        0x00AE,
        0x00AF,
        0x00B0,
        0x00B1,
        0x00B2,
        0x00B3,
        0x00B4,
        0x00B5,
        0x00B6,
        0x00B7,
        0x00B8,
        0x00B9,
        0x00BA,
        0x00BB,
        0x00BC,
        0x00BD,
        0x00BE,
        0x00BF,
        0x00C0,
        0x00C1,
        0x00C2,
        0x00C3,
        0x00C4,
        0x00C5,
        0x00C6,
        0x00C7,
        0x00C8,
        0x00C9,
        0x00CA,
        0x00CB,
        0x00CC,
        0x00CD,
        0x00CE,
        0x00CF,
        0x00D0,
        0x00D1,
        0x00D2,
        0x00D3,
        0x00D4,
        0x00D5,
        0x00D6,
        0x00D7,
        0x00D8,
        0x00D9,
        0x00DA,
        0x00DB,
        0x00DC,
        0x00DD,
        0x00DE,
        0x00DF,
        0x00E0,
        0x00E1,
        0x00E2,
        0x00E3,
        0x00E4,
        0x00E5,
        0x00E6,
        0x00E7,
        0x00E8,
        0x00E9,
        0x00EA,
        0x00EB,
        0x00EC,
        0x00ED,
        0x00EE,
        0x00EF,
        0x00F0,
        0x00F1,
        0x00F2,
        0x00F3,
        0x00F4,
        0x00F5,
        0x00F6,
        0x00F7,
        0x00F8,
        0x00F9,
        0x00FA,
        0x00FB,
        0x00FC,
        0x00FD,
        0x00FE,
        0x00FF,
    )
)


def decode_text(s: bytes) -> str:
    """Decodes a text string (see PDF 1.7 section 7.9.2.2 - it could
    be PDFDocEncoding or UTF-16BE) to a `str`.
    """
    # Sure, it could be UTF-16LE... \/\/hatever...
    if isinstance(s, bytes) and (
        s.startswith(b"\xfe\xff") or s.startswith(b"\xff\xfe")
    ):
        try:
            return s.decode("UTF-16")
        except UnicodeDecodeError:
            # Sure, it could have a BOM and not actually be UTF-16, \/\/TF...
            s = s[2:]
    try:
        return "".join(PDFDocEncoding[c] for c in s)
    except IndexError:
        # This is obviously wrong, but a reasonable fallback
        return s.decode("iso-8859-1")


def string_property(obj: PDFObject, key: str) -> Union[str, None]:
    """Retrieve and decode a string property of an object dictionary
    (such as an annotation, a page, a structure element, etc)

    Takes care of resolving indirect object references in both the
    object and its values.

    Raises:
        TypeError: If `obj` is not a dictionary, or if the value
        requested is not a string

    Returns:
        The decoded string, or `None` if the property doesn't exist.
    """
    objdict = dict_value(obj)
    val = objdict.get(key)
    if val is None:
        return None
    val = str_value(val)
    return decode_text(val)


ROMAN_ONES = ["i", "x", "c", "m"]
ROMAN_FIVES = ["v", "l", "d"]


def format_int_roman(value: int) -> str:
    """Format a number as lowercase Roman numerals."""
    if value <= 0 or value >= 4000:
        raise ValueError(f"Romanes eunt domus: {value}")
    result: List[str] = []
    index = 0

    while value != 0:
        value, remainder = divmod(value, 10)
        if remainder == 9:
            result.insert(0, ROMAN_ONES[index])
            result.insert(1, ROMAN_ONES[index + 1])
        elif remainder == 4:
            result.insert(0, ROMAN_ONES[index])
            result.insert(1, ROMAN_FIVES[index])
        else:
            over_five = remainder >= 5
            if over_five:
                result.insert(0, ROMAN_FIVES[index])
                remainder -= 5
            result.insert(1 if over_five else 0, ROMAN_ONES[index] * remainder)
        index += 1

    return "".join(result)


def format_int_alpha(value: int) -> str:
    """Format a number as lowercase letters a-z, aa-zz, etc."""
    if value <= 0:
        raise ValueError(f"No alphabetic page number for {value}")
    result: List[str] = []

    while value != 0:
        value, remainder = divmod(value - 1, len(string.ascii_lowercase))
        result.append(string.ascii_lowercase[remainder])

    result.reverse()
    return "".join(result)


class IdentityMapping(Mapping[_T, _T]):
    def __getitem__(self, key: _T) -> _T:
        return key

    def __iter__(self) -> Iterator[_T]:
        yield from ()

    def __len__(self) -> int:
        return 0


IDENTITY_MAPPING: IdentityMapping = IdentityMapping()


def update_glyph_offset(
    origin: Point,
    font: "Font",
    gstate: "GraphicState",
    args: List[Union[bytes, int, float]],
) -> Point:
    fontsize = gstate.fontsize
    horizontal_scaling = gstate.scaling * 0.01
    charspace = gstate.charspace
    wordspace = gstate.wordspace
    vert = font.vertical
    if font.multibyte:
        wordspace = 0.0
    (x, y) = origin
    if vert:
        return x, update_glyph_offset_vertical(
            y, font, args, vscale=fontsize, charspace=charspace, wordspace=wordspace
        )
    else:
        return (
            update_glyph_offset_horizontal(
                x,
                font,
                args,
                hscale=fontsize * horizontal_scaling,
                charspace=charspace * horizontal_scaling,
                wordspace=wordspace * horizontal_scaling,
            ),
            y,
        )


def update_glyph_offset_horizontal(
    x: float,
    font: "Font",
    args: List[Union[bytes, int, float]],
    hscale: float,
    charspace: float,
    wordspace: float,
) -> float:
    for obj in args:
        if isinstance(obj, (int, float)):
            x -= obj * 0.001 * hscale
        else:
            for cid, _ in font.decode(obj):
                x += font.hdisp(cid) * hscale + charspace
                if cid == 32:
                    x += wordspace
    return x


def update_glyph_offset_vertical(
    y: float,
    font: "Font",
    args: List[Union[bytes, int, float]],
    vscale: float,
    charspace: float,
    wordspace: float,
) -> float:
    for obj in args:
        if isinstance(obj, (int, float)):
            y -= obj * 0.001 * vscale
        else:
            for cid, _ in font.decode(obj):
                y += font.vdisp(cid) * vscale + charspace
                if cid == 32:
                    y += wordspace
    return y
