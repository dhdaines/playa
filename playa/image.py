import logging
import functools
import itertools
import struct
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
        underlying_colorspace = get_colorspace(resolve1(underlying))
        if underlying_colorspace is None:
            LOG.warning(
                "Unknown underlying colorspace in Indexed image: %r, writing as grayscale",
                resolve1(underlying),
            )
        else:
            ncomponents = underlying_colorspace.ncomponents
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
    elif ncomponents == 4:
        return ".tif", functools.partial(
            write_cmyk_tiff,
            data=data,
            bits=bits,
            width=width,
            height=height,
        )
    else:
        LOG.warning(
            "Unsupported colorspace %r, writing as raw bytes", asobj(colorspace)
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


def write_cmyk_tiff(
    outfh: BinaryIO, data: bytes, bits: int, width: int, height: int
) -> None:
    """
    Writes a CMYK image to a TIFF file.
    """
    # 1. --- Rescale 1, 2, 4 bits to 8 bits ---
    # 1, 2, 4 BitsPerSample for CMYK not allowed as of TIFF Revision 6.0
    # Technically 16 BitsPerSample is also not allowed? but definitely exists
    # e.g. PIL can open them (albeit as 8 bit images)
    if bits in (1, 2, 4):
        scale_factor = 255 // ((1 << bits) - 1)  # 1, 3, 15 divides 255
        data = bytes(b * scale_factor for b in data)
        bits = 8

    # 2. --- TIFF Structure Constants & Calculations ---
    byte_order = b"MM"  # Big-endian

    # --- Tag Codes ---
    TAG_IMAGE_WIDTH = 256
    TAG_IMAGE_LENGTH = 257
    TAG_BITS_PER_SAMPLE = 258
    TAG_COMPRESSION = 259
    TAG_PHOTOMETRIC_INTERP = 262
    TAG_STRIP_OFFSETS = 273
    TAG_SAMPLES_PER_PIXEL = 277
    TAG_ROWS_PER_STRIP = 278
    TAG_STRIP_BYTE_COUNTS = 279
    TAG_X_RESOLUTION = 282
    TAG_Y_RESOLUTION = 283
    TAG_PLANAR_CONFIGURATION = 284
    TAG_RESOLUTION_UNIT = 296

    # --- Data Type Codes ---
    TYPE_SHORT = 3
    TYPE_LONG = 4
    TYPE_RATIONAL = 5

    num_tags = 13

    # --- Calculate Offsets ---
    # The file is laid out as: Header -> IFD -> Extra IFD Data -> Image Data
    header_size = 8
    # 2 for tag count, 12 per tag, 4 for next IFD offset
    ifd_size = 2 + (num_tags * 12) + 4

    # Offsets are relative to the start of the file
    offset_extra_data_start = header_size + ifd_size
    offset_bits_per_sample = offset_extra_data_start
    # 4 samples * 2 bytes/SHORT for the BitsPerSample array
    samples_per_pixel = 4
    offset_x_resolution = offset_bits_per_sample + (samples_per_pixel * 2)
    # 1 RATIONAL = 2 * 4 bytes
    offset_y_resolution = offset_x_resolution + 8
    offset_image_data = offset_y_resolution + 8

    # 3. --- Write TIFF Header ---
    # 8-byte header: Byte Order, TIFF Version (42), Offset to first IFD
    outfh.write(struct.pack(">2sHI", byte_order, 42, header_size))

    # 4. --- Write Image File Directory (IFD) ---
    # First, the number of tags in the directory
    outfh.write(struct.pack(">H", num_tags))

    # Write each 12-byte tag entry.
    # Format: Tag ID (2), Type (2), Count (4), Value/Offset (4)

    # Tag: ImageWidth (TYPE_SHORT)
    outfh.write(struct.pack(">HHII", TAG_IMAGE_WIDTH, TYPE_SHORT, 1, width << 16))

    # Tag: ImageLength (Height) (TYPE_SHORT)
    outfh.write(struct.pack(">HHII", TAG_IMAGE_LENGTH, TYPE_SHORT, 1, height << 16))

    # Tag: BitsPerSample (points to data written later)
    outfh.write(
        struct.pack(
            ">HHII",
            TAG_BITS_PER_SAMPLE,
            TYPE_SHORT,
            samples_per_pixel,
            offset_bits_per_sample,
        )
    )

    # Tag: Compression (1 = no compression)
    outfh.write(struct.pack(">HHII", TAG_COMPRESSION, TYPE_SHORT, 1, 1 << 16))

    # Tag: PhotometricInterpretation (5 = CMYK)
    outfh.write(struct.pack(">HHII", TAG_PHOTOMETRIC_INTERP, TYPE_SHORT, 1, 5 << 16))

    # Tag: StripOffsets (points to the single strip of image data)
    outfh.write(
        struct.pack(">HHII", TAG_STRIP_OFFSETS, TYPE_LONG, 1, offset_image_data)
    )

    # Tag: SamplesPerPixel
    outfh.write(
        struct.pack(
            ">HHII", TAG_SAMPLES_PER_PIXEL, TYPE_SHORT, 1, samples_per_pixel << 16
        )
    )

    # Tag: RowsPerStrip (the whole image is one strip)
    outfh.write(struct.pack(">HHII", TAG_ROWS_PER_STRIP, TYPE_LONG, 1, height))

    # Tag: StripByteCounts (total size of the image data)
    outfh.write(struct.pack(">HHII", TAG_STRIP_BYTE_COUNTS, TYPE_LONG, 1, len(data)))

    # Tag: XResolution (points to rational data written later)
    outfh.write(
        struct.pack(">HHII", TAG_X_RESOLUTION, TYPE_RATIONAL, 1, offset_x_resolution)
    )

    # Tag: YResolution (points to rational data written later)
    outfh.write(
        struct.pack(">HHII", TAG_Y_RESOLUTION, TYPE_RATIONAL, 1, offset_y_resolution)
    )

    # Tag: PlanarConfiguration (1 = chunky format CMYKCMYK...)
    outfh.write(struct.pack(">HHII", TAG_PLANAR_CONFIGURATION, TYPE_SHORT, 1, 1 << 16))

    # Tag: ResolutionUnit (2 = inches)
    outfh.write(struct.pack(">HHII", TAG_RESOLUTION_UNIT, TYPE_SHORT, 1, 2 << 16))

    # Write the offset to the next IFD (0 means this is the last one)
    outfh.write(struct.pack(">I", 0))

    # 5. --- Write Data Pointed to by IFD ---
    # BitsPerSample data: [bits, bits, bits, bits]
    outfh.write(struct.pack(">HHHH", bits, bits, bits, bits))

    # X and Y Resolution data (e.g., 72 DPI) as a RATIONAL (numerator, denominator)
    dpi = 72
    outfh.write(struct.pack(">II", dpi, 1))  # XResolution
    outfh.write(struct.pack(">II", dpi, 1))  # YResolution

    # 6. --- Write the Actual Pixel Data ---
    # The current file position should now match `offset_image_data`
    assert outfh.tell() == offset_image_data, (
        f"File position mismatch: at {outfh.tell()}, expected {offset_image_data}"
    )
    outfh.write(data)
