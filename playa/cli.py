"""PLAYA's CLI, which can get stuff out of a PDF (one PDF) for you.

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

This used to extract arbitrary properties of arbitrary graphical objects
as a CSV, but for that you want PAVÉS now.

"""

import argparse
import json
import logging
from collections import deque
from pathlib import Path
from typing import Any, Deque, Iterable, Tuple

import playa
from playa.document import Document
from playa.pdftypes import ContentStream, ObjRef


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
        "--page-contents",
        type=str,
        help="Decode the content streams for a page "
        "(or range, or 'all') into raw bytes",
    )
    parser.add_argument(
        "-x",
        "--text",
        action="store_true",
        help="Extract text, badly",
    )
    parser.add_argument(
        "-o",
        "--outfile",
        help="File to write output (or - for standard output)",
        type=argparse.FileType("wt"),
        default="-",
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


def extract_text_badly(doc: Document, args: argparse.Namespace) -> None:
    """Extract text, badly."""
    for page in doc.pages:
        for text in page.texts:
            print(text.chars, file=args.outfile)


def extract_page_contents(doc: Document, args: argparse.Namespace) -> None:
    """Extract text, badly."""
    for page_spec in args.page_contents.split(","):
        start, _, end = page_spec.partition("-")
        if end:
            pages: Iterable[int] = range(int(start) - 1, int(end))
        elif start == "all":
            pages = range(len(doc.pages))
        else:
            pages = (int(start) - 1,)
        for page_idx in pages:
            for stream in doc.pages[page_idx].streams:
                args.outfile.buffer.write(stream.buffer)


def main() -> None:
    parser = make_argparse()
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.WARNING)
    try:
        with playa.open(args.pdf, space="default") as doc:
            if args.stream is not None:  # it can't be zero either though
                extract_stream(doc, args)
            elif args.page_contents:
                extract_page_contents(doc, args)
            elif args.catalog:
                extract_catalog(doc, args)
            elif args.text:
                extract_text_badly(doc, args)
            else:
                extract_metadata(doc, args)
    except RuntimeError as e:
        parser.error(f"Something went wrong:\n{e}")


if __name__ == "__main__":
    main()
