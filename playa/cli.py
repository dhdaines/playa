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
from pathlib import Path
from typing import Any

import playa
from playa.document import Document
from playa.pdftypes import ContentStream, ObjRef


def make_argparse() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
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

    This means, for instance, that your `/ParentTree` will just be a
    big list of `ObjRef`.

    """

    def resolver(x: object, default: object, danger: set) -> Any:
        while isinstance(x, ObjRef) and x not in danger:
            danger.add(x)
            x = x.resolve(default=default)
        if isinstance(x, list):
            x = [resolver(v, default, danger) for v in x]
        elif isinstance(x, dict):
            for k, v in x.items():
                x[k] = resolver(v, default, danger)
        elif isinstance(x, ContentStream):
            for k, v in x.attrs.items():
                x.attrs[k] = resolver(v, default, danger)
        return x

    return resolver(x, default, set())


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


def main() -> None:
    parser = make_argparse()
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.WARNING)
    try:
        with playa.open(args.pdf, space="default") as doc:
            if args.stream is not None:  # it can't be zero either though
                extract_stream(doc, args)
            elif args.catalog:
                extract_catalog(doc, args)
            else:
                extract_metadata(doc, args)
    except RuntimeError as e:
        parser.error(f"Something went wrong:\n{e}")


if __name__ == "__main__":
    main()
