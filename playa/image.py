import logging
from pathlib import Path
from typing import BinaryIO, Union

from playa import asobj
from playa.color import ColorSpace
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


def get_one_image(stream: ContentStream, path: Path) -> Path:
    fp = stream.get_filters()
    if fp:
        filters, params = zip(*fp)
        for f in filters:
            if f in LITERALS_DCT_DECODE:
                path = path.with_suffix(".jpg")
                break
            if f in LITERALS_JPX_DECODE:
                path = path.with_suffix(".jp2")
                break
            if f in LITERALS_JBIG2_DECODE:
                path = path.with_suffix(".jb2")
                break
    if path.suffix in (".jpg", ".jp2"):
        # DCT streams are generally readable as JPEG files, and this
        # is also generally true for JPEG2000 streams
        with open(path, "wb") as outfh:
            outfh.write(stream.buffer)
    elif path.suffix == ".jb2":
        # This is not however true for JBIG2, which requires a
        # particular header
        with open(path, "wb") as outfh:
            write_jbig2(outfh, stream)
    else:
        # Otherwise, try to write a PNM file
        bits = stream.bits
        colorspace: Union[ColorSpace, None] = stream.colorspace
        ncomponents = 0
        if colorspace is not None:
            ncomponents = colorspace.ncomponents
            if colorspace.name == "Indexed":
                from playa.color import get_colorspace

                assert isinstance(colorspace.spec, list)
                _, underlying, _, _ = colorspace.spec
                colorspace = get_colorspace(resolve1(underlying))
                if colorspace is not None:
                    ncomponents = colorspace.ncomponents
        if bits == 1:
            path = path.with_suffix(".pbm")
        elif ncomponents == 1:
            path = path.with_suffix(".pgm")
        elif ncomponents == 3:
            path = path.with_suffix(".ppm")
        else:
            path = path.with_suffix(".dat")
            LOG.warning(
                "Unsupported colorspace %s, writing data to %s", asobj(colorspace), path
            )

        if path.suffix != ".dat":
            try:
                with open(path, "wb") as outfh:
                    write_pnm(outfh, stream)
            except ValueError:
                datpath = path.with_suffix(".dat")
                LOG.exception(
                    "Failed to write PNM to %s, writing data to %s", path, datpath
                )
                path = datpath

        if path.suffix == ".dat":
            with open(path, "wb") as outfh:
                outfh.write(stream.buffer)
    return path


def write_pnm(outfh: BinaryIO, stream: ContentStream) -> None:
    """Write stream data to a PBM/PGM/PPM file.

    Raises:
        ValueError: if stream data cannot be written to a PNM, because of an
                    unsupported colour space, or an unsupported filter (JBIG2,
                    DCT or JPEG2000)

    """
    for f in stream.filters:
        if f in LITERALS_DCT_DECODE:
            raise ValueError("Stream is JPEG data, save its buffer directly")
        if f in LITERALS_JPX_DECODE:
            raise ValueError("Stream is JPEG2000 data, save its buffer directly")
        if f in LITERALS_JBIG2_DECODE:
            raise ValueError("Stream is JBIG2 data, save it with write_jbig2")
    bits = stream.bits
    colorspace = stream.colorspace
    ncomponents = colorspace.ncomponents
    data = stream.buffer
    is_bilevel = bits == 1 and ncomponents == 1 and colorspace.name != "Indexed"
    if not is_bilevel:
        from playa.utils import unpack_image_data

        data = unpack_image_data(data, bits, stream.width, stream.height, ncomponents)
    # TODO: Decode array goes here
    if colorspace.name == "Indexed":
        from playa.color import get_colorspace

        assert isinstance(colorspace.spec, list)
        _, underlying, hival, lookup = colorspace.spec
        underlying = get_colorspace(resolve1(underlying))
        if underlying is None:
            raise ValueError(
                "Unknown underlying colorspace in Indexed image: %r" % (underlying,)
            )
        ncomponents = underlying.ncomponents
        if not isinstance(lookup, bytes):
            lookup = stream_value(lookup).buffer
        data = bytes(
            b for i in data for b in lookup[ncomponents * i : ncomponents * (i + 1)]
        )
        bits = 8
    ftype: bytes
    if is_bilevel:
        ftype = b"P4"
    elif ncomponents == 1:
        ftype = b"P5"
    elif ncomponents == 3:
        ftype = b"P6"
    else:
        raise ValueError("Unsupported colorspace: %r" % (stream.colorspace,))
    max_value = (1 << bits) - 1
    outfh.write(b"%s %d %d\n" % (ftype, stream.width, stream.height))
    if is_bilevel:
        # Have to invert the bits! OMG! (FIXME: is there a more
        # efficient way to do this?)
        outfh.write(bytes(x ^ 0xFF for x in data))
    else:
        outfh.write(b"%d\n" % max_value)
        outfh.write(data)


def write_jbig2(outfh: BinaryIO, stream: ContentStream) -> None:
    """Write stream data to a JBIG2 file.

    Raises:
        ValueError: if stream data is not JBIG2.
    """
    if not any(f in LITERALS_JBIG2_DECODE for f in stream.filters):
        raise ValueError("Stream is not JBIG2")
    globals_stream = None
    decode_parms = resolve1(stream.get("DecodeParms"))
    if isinstance(decode_parms, dict):
        globals_stream = resolve1(decode_parms.get("JBIG2Globals"))
    outfh.write(JBIG2_HEADER)
    # flags
    outfh.write(b"\x01")
    # number of pages
    outfh.write(b"\x00\x00\x00\x01")
    # write global segments
    if isinstance(globals_stream, ContentStream):
        outfh.write(globals_stream.buffer)
    # write the rest of the data
    outfh.write(stream.buffer)
    # and an eof segment
    outfh.write(
        b"\x00\x00\x00\x00"  # number (bogus!)
        b"\x33"  # flags: SEG_TYPE_END_OF_FILE
        b"\x00"  # retention_flags: empty
        b"\x00"  # page_assoc: 0
        b"\x00\x00\x00\x00"  # data_length: 0
    )
