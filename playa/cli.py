"""PLAYA's CLI, which can get stuff out of a PDF (one PDF) for you.

This used to extract arbitrary properties of arbitrary graphical objects
as a CSV, but for that you want PAVÉS now.

By default this will just print some hopefully useful metadata about
all the pages and indirect objects in the PDF, as a JSON dictionary,
not because we love JSON, but because it's built-in and easy to parse
and we hate XML a lot more.  This dictionary will always contain the
following keys (but will probably contain more in the future):

- `pdf_version`: self-explanatory
- `is_printable`: whether you should be allowed to print this PDF
- `is_modifiable`: whether you should be allowed to modify this PDF
- `is_extractable`: whether you should be allowed to extract text from
    this PDF (LOL)
- `pages`: list of descriptions of pages, containing:
    - `objid`: the indirect object ID of the page descriptor
    - `label`: a (possibly made up) page label
    - `mediabox`: the boundaries of the page in default user space
    - `cropbox`: the cropping box in default user space
    - `rotate`: the rotation of the page in degrees (no radians for you)
- `objects`: list of all indirect objects (including those in object
    streams, as well as the object streams themselves), containing:
    - `objid`: the object number
    - `genno`: the generation number
    - `type`: the type of object this is
    - `repr`: an arbitrary string representation of the object, **do not
        depend too closely on the contents of this as it will change**

Bucking the trend of the last 20 years towards horribly slow
Click-addled CLIs with deeply nested subcommands, anything else is
just a command-line option away.  You may for instance want to decode
a particular (object, content, whatever) stream:

    playa --stream 123 foo.pdf

Or recursively expand the document catalog into a horrible mess of JSON:

    playa --catalog foo.pdf

You can look at the content streams for one or more or all pages:

    playa --content-streams foo.pdf
    playa --pages 1 --content-streams foo.pdf
    playa --pages 3,4,9 --content-streams foo.pdf

You can... sort of... use this to extract text (don't @ me).  On the
one hand you can get a torrent of JSON for one or more or all pages,
with each fragment of text and all of its properties (position, font,
color, etc):

    playa --text-objects foo.pdf
    playa --pages 4-6 --text-objects foo.pdf

But also, if you have a Tagged PDF, then in theory it has a defined
reading order, and so we can actually really extract the text from it
(this also works with untagged PDFs but your mileage may vary).

    playa --text tagged-foo.pdf

"""

import argparse
import itertools
import json
import logging
import textwrap
from collections import deque
from pathlib import Path
from typing import Any, Deque, Iterable, Iterator, List, Tuple, Union

import playa
from playa import Document, Page
from playa.page import MarkedContent, TextObject
from playa.pdftypes import ContentStream, ObjRef

LOG = logging.getLogger(__name__)


def make_argparse() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="PLAYA's CLI, which can get stuff out of a PDF for you."
    )
    parser.add_argument("pdf", type=Path)
    parser.add_argument(
        "-t",
        "--stream",
        type=int,
        help="Decode an object or content stream into raw bytes",
    )
    parser.add_argument(
        "-c",
        "--catalog",
        action="store_true",
        help="Recursively expand the document catalog as JSON",
    )
    parser.add_argument(
        "-p",
        "--pages",
        type=str,
        help="Page, or range, or list of pages to process with -s or -x",
        default="all",
    )
    parser.add_argument(
        "-s",
        "--content-streams",
        action="store_true",
        help="Decode content streams into raw bytes",
    )
    parser.add_argument(
        "-x",
        "--text-objects",
        action="store_true",
        help="Extract text objects as JSON",
    )
    parser.add_argument(
        "--text",
        action="store_true",
    )
    parser.add_argument(
        "-o",
        "--outfile",
        help="File to write output (or - for standard output)",
        type=argparse.FileType("wt"),
        default="-",
    )
    parser.add_argument(
        "-w",
        "--max-workers",
        type=int,
        help="Maximum number of worker processes to use",
        default=1,
    )
    parser.add_argument(
        "--debug",
        help="Very verbose debugging output",
        action="store_true",
    )
    return parser


def extract_stream(doc: Document, args: argparse.Namespace) -> None:
    """Extract stream data."""
    stream = doc[args.stream]
    if not isinstance(stream, ContentStream):
        raise RuntimeError("Indirect object {args.stream} is not a stream")
    args.outfile.buffer.write(stream.buffer)


def resolve_many(x: object, default: object = None) -> Any:
    """Resolves many indirect object references inside the given object.

    Because there may be circular references (and in the case of a
    logical structure tree, there are *always* circular references),
    we will not `resolve` them `all` as this makes it impossible to
    print a nice JSON object.  For the moment we simply resolve them
    all *once*, though better solutions are possible.

    We resolve stuff in breadth-first order to avoid severely
    unbalanced catalogs, but this is not entirely optimal.

    """
    danger = set()
    to_visit: Deque[Tuple[Any, Any, Any]] = deque([([x], 0, x)])
    while to_visit:
        (parent, key, obj) = to_visit.popleft()
        while isinstance(obj, ObjRef) and obj not in danger:
            danger.add(obj)
            obj = obj.resolve(default=default)
        parent[key] = obj
        if isinstance(obj, list):
            to_visit.extend((obj, idx, v) for idx, v in enumerate(obj))
        elif isinstance(obj, dict):
            to_visit.extend((obj, k, v) for k, v in obj.items())
        elif isinstance(obj, ContentStream):
            to_visit.extend((obj.attrs, k, v) for k, v in obj.attrs.items())
    return x


def extract_catalog(doc: Document, args: argparse.Namespace) -> None:
    """Extract catalog data."""
    json.dump(
        resolve_many(doc.catalog),
        args.outfile,
        indent=2,
        ensure_ascii=False,
        default=repr,
    )


def extract_metadata(doc: Document, args: argparse.Namespace) -> None:
    """Extract random metadata."""
    stuff = {
        "pdf_version": doc.pdf_version,
        "is_printable": doc.is_printable,
        "is_modifiable": doc.is_modifiable,
        "is_extractable": doc.is_extractable,
    }
    pages = []
    for page in doc.pages:
        pages.append(
            {
                "objid": page.pageid,
                "label": page.label,
                "mediabox": page.mediabox,
                "cropbox": page.cropbox,
                "rotate": page.rotate,
            }
        )
    stuff["pages"] = pages
    objects = []
    for obj in doc.objects:
        # TODO: Add method to JSON serialize indirect objects
        objects.append(
            {
                "objid": obj.objid,
                "genno": obj.genno,
                "type": type(obj.obj).__name__,
                "repr": repr(obj.obj),
            }
        )
    stuff["objects"] = objects
    json.dump(stuff, args.outfile, indent=2, ensure_ascii=False)


def decode_page_spec(doc: Document, spec: str) -> Iterator[int]:
    for page_spec in spec.split(","):
        start, _, end = page_spec.partition("-")
        if end:
            pages: Iterable[int] = range(int(start) - 1, int(end))
        elif start == "all":
            pages = range(len(doc.pages))
        else:
            pages = (int(start) - 1,)
        yield from pages


def get_text_json(page: Page) -> List[str]:
    objs = []
    for text in page.texts:
        tstate = text.textstate
        # Prune these objects somewhat (FIXME: need a method that will
        # serialize only non-default values and run _asdict as needed)
        textstate = {
            "line_matrix": tstate.line_matrix,
            "fontsize": tstate.fontsize,
            "render_mode": tstate.render_mode,
        }
        if tstate.font is not None:
            textstate["font"] = {
                "fontname": tstate.font.fontname,
                "vertical": tstate.font.vertical,
            }
        gstate = {
            "scs": text.gstate.scs._asdict(),
            "scolor": text.gstate.scolor._asdict(),
            "ncs": text.gstate.ncs._asdict(),
            "ncolor": text.gstate.ncolor._asdict(),
        }
        obj = {
            "chars": text.chars,
            "bbox": text.bbox,
            "textstate": textstate,
            "gstate": gstate,
            "mcstack": [mcs._asdict() for mcs in text.mcstack],
        }
        objs.append(json.dumps(obj, indent=2, ensure_ascii=False, default=repr))
    return objs


def extract_text_objects(doc: Document, args: argparse.Namespace) -> None:
    """Extract text objects as JSON."""
    pages = decode_page_spec(doc, args.pages)
    print("[", file=args.outfile)
    last = None
    for a, b in itertools.pairwise(
        itertools.chain.from_iterable(doc.pages[pages].map(get_text_json))
    ):
        print(a, ",", sep="", file=args.outfile)
        last = b
    if last is not None:
        print(last, file=args.outfile)
    print("]", file=args.outfile)


def get_stream_data(page: Page) -> bytes:
    streams = []
    for stream in page.streams:
        streams.append(stream.buffer)
    return b"\n".join(streams)


def extract_page_contents(doc: Document, args: argparse.Namespace) -> None:
    """Extract content streams from pages."""
    pages = decode_page_spec(doc, args.pages)
    for data in doc.pages[pages].map(get_stream_data):
        args.outfile.buffer.write(data)


def get_text_from_obj(obj: TextObject, vertical: bool) -> Tuple[str, float]:
    """Try to get text from a text object."""
    chars = []
    prev_end = 0.
    for glyph in obj:
        x, y = glyph.textstate.glyph_offset
        off = y if vertical else x
        # FIXME: This is a heuristic!!!
        if prev_end and off - prev_end > 0.5:
            chars.append(" ")
        if glyph.text is not None:
            chars.append(glyph.text)
        prev_end = off + glyph.adv
    return "".join(chars), prev_end


def get_text_untagged(page: Page) -> str:
    """Get text from a page of an untagged PDF."""
    prev_line_matrix = None
    prev_end = 0.
    lines = []
    strings = []
    for text in page.texts:
        line_matrix = text.textstate.line_matrix
        vertical = (
            False if text.textstate.font is None else text.textstate.font.vertical
        )
        lpos = -2 if vertical else -1
        if prev_line_matrix is not None and line_matrix[lpos] < prev_line_matrix[lpos]:
            lines.append("".join(strings))
            strings.clear()
        wpos = -1 if vertical else -2
        if (
            prev_line_matrix is not None
            and prev_end + prev_line_matrix[wpos] < line_matrix[wpos]
        ):
            strings.append(" ")
        textstr, end = get_text_from_obj(text, vertical)
        strings.append(textstr)
        prev_line_matrix = line_matrix
        prev_end = end
    if strings:
        lines.append("".join(strings))
    return "\n".join(lines)


def get_text_tagged(page: Page) -> str:
    """Get text from a page of a tagged PDF."""
    lines: List[str] = []
    strings: List[str] = []
    at_mcs: Union[MarkedContent, None] = None
    prev_mcid: Union[int, None] = None
    for text in page.texts:
        in_artifact = same_actual_text = reversed_chars = False
        actual_text = None
        for mcs in reversed(text.mcstack):
            if mcs.tag == "Artifact":
                in_artifact = True
                break
            actual_text = mcs.props.get("ActualText")
            if actual_text is not None:
                if mcs is at_mcs:
                    same_actual_text = True
                at_mcs = mcs
                break
            if mcs.tag == "ReversedChars":
                reversed_chars = True
                break
        if in_artifact or same_actual_text:
            continue
        if actual_text is None:
            chars = text.chars
            if reversed_chars:
                chars = chars[::-1]
        else:
            assert isinstance(actual_text, bytes)
            chars = actual_text.decode("UTF-16")
        # Remove soft hyphens
        chars = chars.replace("\xad", "")
        # Insert a line break (FIXME: not really correct)
        if text.mcid != prev_mcid:
            lines.extend(textwrap.wrap("".join(strings)))
            strings.clear()
            prev_mcid = text.mcid
        strings.append(chars)
    if strings:
        lines.extend(textwrap.wrap("".join(strings)))
    return "\n".join(lines)


def extract_text(doc: Document, args: argparse.Namespace) -> None:
    """Extract text, but not in any kind of fancy way."""
    pages = decode_page_spec(doc, args.pages)
    if "MarkInfo" not in doc.catalog or not doc.catalog["MarkInfo"].get("Marked"):
        LOG.warning("Document is not a tagged PDF, text may not be readable")
        textor = doc.pages[pages].map(get_text_untagged)
    else:
        textor = doc.pages[pages].map(get_text_tagged)
    for text in textor:
        print(text, file=args.outfile)


def main() -> None:
    parser = make_argparse()
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.WARNING)
    try:
        with playa.open(args.pdf, space="default", max_workers=args.max_workers) as doc:
            if args.stream is not None:  # it can't be zero either though
                extract_stream(doc, args)
            elif args.content_streams:
                extract_page_contents(doc, args)
            elif args.catalog:
                extract_catalog(doc, args)
            elif args.text_objects:
                extract_text_objects(doc, args)
            elif args.text:
                extract_text(doc, args)
            else:
                extract_metadata(doc, args)
    except RuntimeError as e:
        parser.error(f"Something went wrong:\n{e}")


if __name__ == "__main__":
    main()
