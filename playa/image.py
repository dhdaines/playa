import logging
import functools
import itertools
from pathlib import Path
from typing import BinaryIO, Callable, Tuple

from playa import asobj
from playa.color import get_colorspace
from playa.pdftypes import (
    LITERALS_DCT_DECODE,
    LITERALS_JPX_DECODE,
    LITERALS_JBIG2_DECODE,
    ContentStream,
    resolve1,
    stream_value,
)

LOG = logging.getLogger(__name__)

JBIG2_HEADER = b"\x97JB2\r\n\x1a\n"


# PDF 2.0, sec 8.9.3 Sample data shall be represented as a stream of
# bytes, interpreted as 8-bit unsigned integers in the range 0 to
# 255. The bytes constitute a continuous bit stream, with the
# high-order bit of each byte first.  This bit stream, in turn, is
# divided into units of n bits each, where n is the number of bits per
# component.  Each unit encodes a colour component value, given with
# high-order bit first; units of 16 bits shall be given with the most
# significant byte first. Byte boundaries shall be ignored, except
# that each row of sample data shall begin on a byte boundary. If the
# number of data bits per row is not a multiple of 8, the end of the
# row is padded with extra bits to fill out the last byte. A PDF
# processor shall ignore these padding bits.
def unpack_image_data(
    s: bytes, bpc: int, width: int, height: int, ncomponents: int
) -> bytes:
    if bpc not in (1, 2, 4):
        return s
    if bpc == 4:

        def unpack_f(x: int) -> Tuple[int, ...]:
            return (x >> 4, x & 15)

    elif bpc == 2:

        def unpack_f(x: int) -> Tuple[int, ...]:
            return (x >> 6, x >> 4 & 3, x >> 2 & 3, x & 3)

    else:  # bpc == 1

        def unpack_f(x: int) -> Tuple[int, ...]:
            return tuple(x >> i & 1 for i in reversed(range(8)))

    rowsize = (width * ncomponents * bpc + 7) // 8
    rows = (s[i * rowsize : (i + 1) * rowsize] for i in range(height))
    unpacked_rows = (
        itertools.islice(
            itertools.chain.from_iterable(map(unpack_f, row)), width * ncomponents
        )
        for row in rows
    )
    return bytes(itertools.chain.from_iterable(unpacked_rows))


def get_one_image(stream: ContentStream, path: Path) -> Path:
    suffix, writer = get_image_suffix_and_writer(stream)
    path = path.with_suffix(suffix)
    with open(path, "wb") as outfh:
        writer(outfh)
    return path


def get_image_suffix_and_writer(
    stream: ContentStream,
) -> Tuple[str, Callable[[BinaryIO], None]]:
    for f, parms in stream.get_filters():
        if f in LITERALS_DCT_DECODE:
            # DCT streams are generally readable as JPEG files
            return ".jpg", functools.partial(write_raw, data=stream.buffer)
        if f in LITERALS_JPX_DECODE:
            # This is also generally true for JPEG2000 streams
            return ".jp2", functools.partial(write_raw, data=stream.buffer)
        if f in LITERALS_JBIG2_DECODE:
            # This is not however true for JBIG2, which requires a
            # particular header
            globals_stream = resolve1(parms.get("JBIG2Globals"))
            if isinstance(globals_stream, ContentStream):
                jbig2globals = globals_stream.buffer
            else:
                jbig2globals = b""
            return ".jb2", functools.partial(
                write_jbig2, data=stream.buffer, jbig2globals=jbig2globals
            )

    bits = stream.bits
    width = stream.width
    height = stream.height
    colorspace = stream.colorspace
    ncomponents = colorspace.ncomponents
    data = stream.buffer
    if bits == 1 and ncomponents == 1 and colorspace.name != "Indexed":
        return ".pbm", functools.partial(
            write_pbm, data=data, width=width, height=height
        )

    data = unpack_image_data(data, bits, width, height, ncomponents)
    # TODO: Decode array goes here
    if colorspace.name == "Indexed":
        assert isinstance(colorspace.spec, list)
        _, underlying, hival, lookup = colorspace.spec
        colorspace = get_colorspace(resolve1(underlying))
        if colorspace is None:
            LOG.warning(
                "Unknown underlying colorspace in Indexed image: %r, writing as grayscale",
                resolve1(underlying),
            )
        else:
            ncomponents = colorspace.ncomponents
            if not isinstance(lookup, bytes):
                lookup = stream_value(lookup).buffer
            data = bytes(
                b for i in data for b in lookup[ncomponents * i : ncomponents * (i + 1)]
            )
            bits = 8

    if ncomponents == 1:
        return ".pgm", functools.partial(
            write_pnm,
            data=data,
            ftype=b"P5",
            bits=bits,
            width=width,
            height=height,
        )
    elif ncomponents == 3:
        return ".ppm", functools.partial(
            write_pnm,
            data=data,
            ftype=b"P6",
            bits=bits,
            width=width,
            height=height,
        )
    else:
        LOG.warning(
            "Unsupported colorspace %s, writing as raw bytes", asobj(colorspace)
        )
        return ".dat", functools.partial(write_raw, data=data)


def write_raw(outfh: BinaryIO, data: bytes) -> None:
    outfh.write(data)


def write_pbm(outfh: BinaryIO, data: bytes, width: int, height: int) -> None:
    """Write stream data to a PBM file."""
    outfh.write(b"P4 %d %d\n" % (width, height))
    outfh.write(bytes(x ^ 0xFF for x in data))


def write_pnm(
    outfh: BinaryIO, data: bytes, ftype: bytes, bits: int, width: int, height: int
) -> None:
    """Write stream data to a PGM/PPM file."""
    max_value = (1 << bits) - 1
    outfh.write(b"%s %d %d\n" % (ftype, width, height))
    outfh.write(b"%d\n" % max_value)
    outfh.write(data)


def write_jbig2(outfh: BinaryIO, data: bytes, jbig2globals: bytes) -> None:
    """Write stream data to a JBIG2 file."""
    outfh.write(JBIG2_HEADER)
    # flags
    outfh.write(b"\x01")
    # number of pages
    outfh.write(b"\x00\x00\x00\x01")
    # write global segments
    outfh.write(jbig2globals)
    # write the rest of the data
    outfh.write(data)
    # and an eof segment
    outfh.write(
        b"\x00\x00\x00\x00"  # number (bogus!)
        b"\x33"  # flags: SEG_TYPE_END_OF_FILE
        b"\x00"  # retention_flags: empty
        b"\x00"  # page_assoc: 0
        b"\x00\x00\x00\x00"  # data_length: 0
    )
