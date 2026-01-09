"""PLAYA's CLI, which can get stuff out of PDFs for you.

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
    - `obj`: a best-effort JSON serialization of the object's
      metadata.  In the case of simple objects like strings,
      dictionaries, or lists, this is the object itself.  Object
      references are converted to a string representation of the form
      "<ObjRef:OBJID>", while content streams are reprented by their
      properties dictionary.

Bucking the trend of the last 20 years towards horribly slow
Click-addled CLIs with deeply nested subcommands, anything else is
just a command-line option away.  You may for instance want to decode
a particular (object, content, whatever) stream:

    playa --stream 123 foo.pdf

Or recursively expand the document catalog into a horrible mess of JSON:

    playa --catalog foo.pdf

You can look at the content streams for one or more or all pages
(numbered from 1):

    playa --content-streams foo.pdf
    playa --pages 1 --content-streams foo.pdf
    playa --pages 3,4,9 --content-streams foo.pdf

And you can get the logical structure tree, including the text of
content items (for properly tagged PDFs this is more useful than just
getting the raw text):

    playa --structure foo.pdf

You can even... sort of... use this to extract text (don't @ me).  On
the one hand you can get a torrent of JSON for one or more or all
pages, with each fragment of text and all of its properties (position,
font, color, etc):

    playa --text-objects foo.pdf
    playa --pages 4-6 --text-objects foo.pdf

But also, if you have a Tagged PDF, then in theory it has a defined
reading order, and so we can actually really extract the text from it
(this also works with untagged PDFs but your mileage may vary).

    playa --text tagged-foo.pdf

And finally yes you can also extract images (not necessarily useful
since they are frequently tiled and/or composited):

    playa --images outdir foo.dir

"""

import argparse
import functools
import getpass
import itertools
import json
import logging
import re
import textwrap
from collections import deque
from pathlib import Path
from typing import Any, Deque, Iterable, Iterator, List, TextIO, Tuple, Union

import playa
from playa import Document, Page, PDFPasswordIncorrect, asobj
from playa.data.content import Image
from playa.data.metadata import asobj_document, asobj_structelement
from playa.image import get_one_image
from playa.outline import Outline
from playa.page import ImageObject
from playa.pdftypes import (
    ContentStream,
    ObjRef,
    resolve1,
    PDFObject,
)
from playa.structure import ContentItem
from playa.structure import ContentObject as StructContentObject
from playa.structure import Element

LOG = logging.getLogger(__name__)


def make_argparse() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="PLAYA's CLI, which can get stuff out of PDFs for you."
    )
    parser.add_argument("pdfs", type=Path, nargs="*")
    parser.add_argument("--version", action="store_true", help="Display version")
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
        help="Page, or range, or list of pages (numbered from 1) to process",
        default="all",
    )
    parser.add_argument(
        "-s",
        "--content-streams",
        action="store_true",
        help="Decode content streams into raw bytes",
    )
    parser.add_argument(
        "--content-objects",
        action="store_true",
        help="Extract content objects as JSON",
    )
    parser.add_argument(
        "--explode-text",
        action="store_true",
        help="Explode text objects into constituent glyphs (are you sure?)",
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
        "--structure",
        action="store_true",
        help="Extract logical structure tree as JSON",
    )
    parser.add_argument(
        "--outline",
        action="store_true",
        help="Extract document outline as JSON",
    )
    parser.add_argument(
        "--images",
        type=Path,
        help="Extract image files here (default is not to extract).",
    )
    parser.add_argument(
        "--fonts",
        type=Path,
        help="Extract font files here (default is not to extract).",
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
        "--password",
        help="Password for an encrypted PDF.  If not supplied, "
        "will be read from the console.",
        type=str,
        default="",
    )
    parser.add_argument(
        "--non-interactive",
        help="Do not attempt to read a password from the console.",
        action="store_true",
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
        raise ValueError("Indirect object {args.stream} is not a stream")
    args.outfile.buffer.write(stream.buffer)


def resolve_many(x: PDFObject) -> PDFObject:
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
    objs = [x]
    to_visit: Deque[Tuple[Any, Any, Any]] = deque([(objs, 0, x)])
    while to_visit:
        (parent, key, obj) = to_visit.popleft()
        if key in ("Parent", "P"):  # Special-case these to avoid nonsense
            continue
        if isinstance(obj, ObjRef):
            if obj in danger:
                continue
            while isinstance(obj, ObjRef):
                danger.add(obj)
                obj = obj.resolve()
        parent[key] = obj
        if isinstance(obj, list):
            to_visit.extend((obj, idx, v) for idx, v in enumerate(obj))
        elif isinstance(obj, dict):
            to_visit.extend((obj, k, v) for k, v in obj.items())
        elif isinstance(obj, ContentStream):
            to_visit.extend((obj.attrs, k, v) for k, v in obj.attrs.items())
    return objs[0]


def extract_catalog(doc: Document, args: argparse.Namespace) -> None:
    """Extract catalog data."""
    # We have to use the *reference* to the catalog because some evil
    # PDFs will make a backreference to it somewhere
    catalog: Union[None, PDFObject] = None
    for xref in doc.xrefs:
        trailer = xref.trailer
        if not trailer:
            continue
        if "Root" in trailer and resolve1(trailer["Root"]) is not None:
            catalog = trailer["Root"]
            break
    if catalog is None:
        raise ValueError("No valid catalog found")
    json.dump(
        resolve_many(catalog),
        args.outfile,
        indent=2,
        ensure_ascii=False,
        default=asobj,
    )


def extract_metadata(doc: Document, args: argparse.Namespace) -> None:
    """Extract random metadata."""
    metadata = asobj_document(doc, exclude={"structure", "outline"})
    json.dump(metadata, args.outfile, indent=2, ensure_ascii=False)


def decode_page_spec(doc: Document, spec: str) -> Iterator[int]:
    npages = len(doc.pages)
    for page_spec in spec.split(","):
        startstr, _, endstr = page_spec.partition("-")
        if startstr == "all":
            yield from range(npages)
            continue
        start = int(startstr) - 1
        if start < 0:
            LOG.warning("Pages are numbered from 1, starting with first page")
            start = 0
        if start >= npages:
            LOG.warning(
                "start page %d is after last page %d, skipping", start + 1, npages
            )
            continue
        if endstr:
            end = int(endstr)
            if end > npages:
                LOG.warning("end page %d is after last page %d, clipping", end, npages)
                end = npages
            elif end <= start:
                LOG.warning(
                    "end page %d is before start page %d, reversing", end, start + 1
                )
                start, end = max(0, end - 1), start + 1
            pages: Iterable[int] = range(start, end)
        else:
            pages = (start,)
        yield from pages


def get_text_json(page: Page, explode_text: bool = False) -> List[str]:
    objs = []
    itor = page.glyphs if explode_text else page.texts
    for text in itor:
        objs.append(
            json.dumps(asobj(text), indent=2, ensure_ascii=False, default=asobj)
        )
    return objs


def extract_text_objects(doc: Document, args: argparse.Namespace) -> None:
    """Extract text objects as JSON."""
    pages = decode_page_spec(doc, args.pages)
    print("[", file=args.outfile)
    last = None
    for obj in itertools.chain.from_iterable(
        doc.pages[pages].map(
            functools.partial(get_text_json, explode_text=args.explode_text)
        )
    ):
        if last is not None:
            print(last, end=",\n", sep="", file=args.outfile)
        last = obj
    if last is not None:
        print(last, file=args.outfile)
    print("]", file=args.outfile)


def get_content_json(page: Page, explode_text: bool = False) -> List[str]:
    objs = []
    itor = page.glyphs if explode_text else page.flatten()
    for obj in itor:
        objdict = asobj(obj)
        objdict["object_type"] = obj.object_type
        objs.append(json.dumps(objdict, indent=2, ensure_ascii=False, default=asobj))
    return objs


def extract_content_objects(doc: Document, args: argparse.Namespace) -> None:
    """Extract content objects as JSON."""
    pages = decode_page_spec(doc, args.pages)
    print("[", file=args.outfile)
    last = None
    for obj in itertools.chain.from_iterable(
        doc.pages[pages].map(
            functools.partial(get_content_json, explode_text=args.explode_text)
        )
    ):
        if last is not None:
            print(last, end=",\n", sep="", file=args.outfile)
        last = obj
    if last is not None:
        print(last, file=args.outfile)
    print("]", file=args.outfile)


def get_stream_data(page: Page) -> bytes:
    streams = []
    for stream in page.streams:
        LOG.debug("Page %d content stream %d", page.page_idx, stream.objid)
        streams.append(stream.buffer)
    return b"\n".join(streams)


def extract_page_contents(doc: Document, args: argparse.Namespace) -> None:
    """Extract content streams from pages."""
    pages = decode_page_spec(doc, args.pages)
    for data in doc.pages[pages].map(get_stream_data):
        args.outfile.buffer.write(data)


def extract_text(doc: Document, args: argparse.Namespace) -> None:
    """Extract text, but not in any kind of fancy way."""
    pages = decode_page_spec(doc, args.pages)
    if not doc.is_tagged:
        LOG.warning("Document is not a tagged PDF, text may not be readable")
    textor = doc.pages[pages].map(Page.extract_text)
    for text in textor:
        print(text, file=args.outfile)


@functools.singledispatch
def _extract_child(
    kid: Union[Element, StructContentObject, ContentItem], indent: int, outfh: TextIO
) -> bool:
    return False


@_extract_child.register(StructContentObject)
def _extract_content_object(
    kid: StructContentObject, indent: int, outfh: TextIO
) -> bool:
    ws = " " * indent
    text = json.dumps(kid.props, default=asobj)
    print(f"{ws}{text}", end="", file=outfh)
    return True


@_extract_child.register(ContentItem)
def _extract_content_item(kid: ContentItem, indent: int, outfh: TextIO) -> bool:
    if kid.page is None:
        return False
    text = kid.text
    if text is None:
        return False
    ws = " " * indent
    text = json.dumps(text, ensure_ascii=False)
    print(f"{ws}{text}", end="", file=outfh)
    return True


@_extract_child.register(Element)
def _extract_element(el: Element, indent: int, outfh: TextIO) -> bool:
    """Extract a single structure element."""
    ws = " " * indent
    ss = "  "

    try:
        text = json.dumps(
            asobj_structelement(el, recurse=False), indent=2, ensure_ascii=False
        )
    except KeyError as e:
        LOG.warning("Ignoring malformed structure element with no %s: %r", e, el.props)
        return False
    brace = text.rindex("}")
    print(textwrap.indent(text[:brace].strip(), ws), end="", file=outfh)
    print(f',\n{ws}{ss}"children": [', file=outfh)
    comma = False
    for kid in el:
        if comma:
            print(",", file=outfh)
        comma = _extract_child(kid, indent + 4, outfh)
    print(f"\n{ws}{ss}]", end="", file=outfh)
    print(f"\n{ws}}}", end="", file=outfh)

    return True


def extract_structure(doc: Document, args: argparse.Namespace) -> None:
    """Extract logical structure as JSON, with (not at all fancy) text."""
    if doc.structure is None:
        LOG.info("Document has no logical structure")
        print("[]", file=args.outfile)
        return
    print("[", file=args.outfile, end="")
    comma = False
    for el in doc.structure:
        if comma:
            print(",", file=args.outfile)
        comma = _extract_child(el, 2, args.outfile)
    print("]", file=args.outfile)


def _extract_outline_item(item: Outline, indent: int, outfh: TextIO) -> bool:
    """Extract a single outline item."""
    ws = " " * indent
    ss = "  "
    s = []

    def format_attr(k: Any, v: Any) -> None:
        k = json.dumps(k, ensure_ascii=False)
        v = json.dumps(v, ensure_ascii=False)
        s.append(f"{ws}{ss}{k}: {v}")

    print(f"{ws}{{", file=outfh)
    if item.title is not None:
        format_attr("title", item.title)
    if item.destination is not None:
        format_attr("destination", asobj(item.destination))
    if s:
        print(",\n".join(s), end="", file=outfh)
    children = list(item)
    if children:
        if s:
            print(",", file=outfh)
        print(f'{ws}{ss}"children": [', file=outfh)
        comma = False
        for kid in children:
            if comma:
                print(",", file=outfh)
            comma = _extract_outline_item(kid, indent + 4, outfh)
        print(f"\n{ws}{ss}]", end="", file=outfh)
    print(f"\n{ws}}}", end="", file=outfh)
    return True


def extract_outline(doc: Document, args: argparse.Namespace) -> None:
    """Extract logical outline as JSON."""
    if doc.outline is None:
        LOG.info("Document has no outline")
        print("{}", file=args.outfile)
        return
    _extract_outline_item(doc.outline, 0, args.outfile)


def get_images(page: Page, imgdir: Path) -> List[Tuple[Path, Image]]:
    images = []
    for idx, img in enumerate(page.flatten(ImageObject)):
        if img.xobjid is None:
            text_bbox = ",".join(str(round(x)) for x in img.bbox)
            imgid = f"inline-{text_bbox}"
        else:
            imgid = re.sub(r"\W", "", img.xobjid)
        imgname = f"page{page.page_idx + 1}-{idx}-{imgid}"
        imgpath = imgdir / imgname
        try:
            images.append((get_one_image(img.stream, imgpath), asobj(img)))
        except Exception as e:
            LOG.warning("Failed to extract image %s: %s", imgid, e)
        mask = resolve1(img.get("Mask"))
        if isinstance(mask, ContentStream):
            imgpath = imgdir / f"{imgname}-mask"
            try:
                images.append((get_one_image(mask, imgpath), asobj(mask)))
            except Exception as e:
                LOG.warning("Failed to extract mask %s: %s", imgid, e)
        smask = resolve1(img.get("SMask"))
        if isinstance(smask, ContentStream):
            imgpath = imgdir / f"{imgname}-smask"
            try:
                images.append((get_one_image(smask, imgpath), asobj(smask)))
            except Exception as e:
                LOG.warning("Failed to extract smask %s: %s", imgid, e)
        # In theory this exists, in practice, very unsure
        alts = resolve1(img.get("Alternates"))
        if isinstance(alts, list):
            for idx, alt in enumerate(alts):
                if isinstance(alt, ContentStream):
                    imgpath = imgdir / f"{imgname}-alt{idx}"
                    try:
                        images.append((get_one_image(alt, imgpath), asobj(alt)))
                    except Exception as e:
                        LOG.warning(
                            "Failed to extract alternate %d for %s: %s", idx, imgid, e
                        )

    return images


def extract_images(doc: Document, args: argparse.Namespace) -> None:
    """Extract images."""
    pages = decode_page_spec(doc, args.pages)
    print("[", file=args.outfile, end="")
    if args.images is not None:
        args.images.mkdir(exist_ok=True, parents=True)
    last = None
    for page, images in enumerate(
        doc.pages[pages].map(functools.partial(get_images, imgdir=args.images))
    ):
        for path, image in images:
            if last is not None:
                print(last, end=",\n", sep="", file=args.outfile)
            image["page_idx"] = page
            image["path"] = str(path)
            last = json.dumps(image, indent=2, ensure_ascii=False)
    if last is not None:
        print(last, file=args.outfile)
    print("]", file=args.outfile)


def extract_fonts(doc: Document, args: argparse.Namespace) -> None:
    """Extract fonts."""
    pages = decode_page_spec(doc, args.pages)
    print("{", file=args.outfile, end="")
    if args.fonts is not None:
        args.fonts.mkdir(exist_ok=True, parents=True)
    extracted = set()
    last = None
    for page in doc.pages[pages]:
        fontiter = (text.gstate.font for text in page.texts)
        for font in fontiter:
            if font is None:
                continue
            # Fonts can have identical fontnames, but normally these are just
            # the same font with different encodings, so no point in extracting
            # them multiple times.
            if font.fontname in extracted:
                continue
            path = font.write_fontfile(args.fonts)
            if path is not None:
                extracted.add(font.fontname)
                if last is not None:
                    lastpath, lastfont = last
                    print(
                        json.dumps(str(lastpath)),
                        end=": ",
                        sep="",
                        file=args.outfile,
                    )
                    print(
                        json.dumps(asobj(lastfont)),
                        end=",\n",
                        sep="",
                        file=args.outfile,
                    )
                last = (path, font)
    if last is not None:
        lastpath, lastfont = last
        print(json.dumps(str(lastpath)), end=": ", sep="", file=args.outfile)
        print(json.dumps(asobj(lastfont)), end="\n", sep="", file=args.outfile)
    print("}", file=args.outfile)


def main(argv: Union[List[str], None] = None) -> int:
    parser = make_argparse()
    args = parser.parse_args(argv)
    if args.version:
        print(playa.__version__)
        return 0
    elif not args.pdfs:
        parser.error("At least one PDF is required")
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.WARNING)
    errors = 0
    for path in args.pdfs:
        try:
            doc = playa.open(
                path,
                space="default",
                max_workers=args.max_workers,
                password=args.password,
            )
        except PDFPasswordIncorrect:
            if args.non_interactive:
                raise
            password = getpass.getpass(prompt=f"Password for {path}: ")
            doc = playa.open(
                path,
                space="default",
                max_workers=args.max_workers,
                password=password,
            )
        except Exception as e:
            errors += 1
            if args.debug:
                LOG.exception(f"Invalid or corrupt PDF {path}")
            else:
                LOG.error(f"Invalid or corrupt PDF {path}: {e}")
            continue
        try:
            if args.stream is not None:  # it can't be zero either though
                extract_stream(doc, args)
            elif args.content_streams:
                extract_page_contents(doc, args)
            elif args.catalog:
                extract_catalog(doc, args)
            elif args.content_objects:
                extract_content_objects(doc, args)
            elif args.text_objects:
                extract_text_objects(doc, args)
            elif args.text:
                extract_text(doc, args)
            elif args.structure:
                extract_structure(doc, args)
            elif args.outline:
                extract_outline(doc, args)
            elif args.images:
                extract_images(doc, args)
            elif args.fonts:
                extract_fonts(doc, args)
            else:
                extract_metadata(doc, args)
            doc.close()
        except Exception as e:
            if args.debug:
                LOG.exception(f"Invalid or corrupt PDF {path}")
            else:
                LOG.error(f"Invalid or corrupt PDF {path}: {e}")
            errors += 1
    return errors


if __name__ == "__main__":
    raise SystemExit(main())
