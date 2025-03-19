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

You can look at the content streams for one or more or all pages:

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

    playa --images foo.pdf --imgdir outdir
"""

import argparse
import functools
import getpass
import itertools
import json
import logging
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, Iterable, Iterator, List, TextIO, Tuple, Union

import playa
from playa import Document, Page, PDFPasswordIncorrect, asobj
from playa.data.content import Image
from playa.data.metadata import asobj_document
from playa.page import ContentObject, ImageObject, TextObject
from playa.pdftypes import LITERALS_DCT_DECODE, ContentStream, ObjRef, resolve1
from playa.structure import ContentItem
from playa.structure import ContentObject as StructContentObject
from playa.structure import Element
from playa.utils import decode_text
from playa.worker import PageRef, _deref_page

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
        action="store_true",
        help="Extract images as... whatever",
    )
    parser.add_argument(
        "--imgdir",
        type=Path,
        help="Extract image files here (default is not to extract).",
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
        default=asobj,
    )


def extract_metadata(doc: Document, args: argparse.Namespace) -> None:
    """Extract random metadata."""
    metadata = asobj_document(doc, exclude={"structure", "outline"})
    json.dump(metadata, args.outfile, indent=2, ensure_ascii=False)


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


def flatten_harder(itor: Iterator[ContentObject]) -> Iterator[ContentObject]:
    for obj in itor:
        if isinstance(obj, TextObject):
            yield from obj
        else:
            yield obj


def get_text_json(page: Page, explode_text: bool = False) -> List[str]:
    objs = []
    itor = flatten_harder(page.texts) if explode_text else page.texts
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
    itor = flatten_harder(page.flatten()) if explode_text else page.flatten()
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


@functools.lru_cache(maxsize=16)
def get_mcid_text(pageref: PageRef) -> Dict[int, List[str]]:
    """Get text for all MCIDs on a page"""
    page = _deref_page(pageref)
    mctext: Dict[int, List[str]] = {}
    for text in page.texts:
        mcs = text.mcs
        if mcs is None or mcs.mcid is None:
            continue
        if "ActualText" in mcs.props:
            assert isinstance(mcs.props["ActualText"], bytes)
            chars = mcs.props["ActualText"].decode("UTF-16")
        else:
            chars = text.chars
        # Remove soft hyphens
        chars = chars.replace("\xad", "")
        mctext.setdefault(mcs.mcid, []).append(chars)
    return mctext


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
    strs = get_mcid_text(kid.page.pageref).get(kid.mcid)
    if strs is None:
        return False
    ws = " " * indent
    text = json.dumps("".join(strs), ensure_ascii=False)
    print(f"{ws}{text}", end="", file=outfh)
    return True


@_extract_child.register(Element)
def _extract_element(el: Element, indent: int, outfh: TextIO) -> bool:
    """Extract a single structure element."""
    ws = " " * indent
    ss = "  "
    s = []

    def format_attr(k: Any, v: Any) -> None:
        k = json.dumps(k, ensure_ascii=False)
        v = json.dumps(v, ensure_ascii=False)
        s.append(f"{ws}{ss}{k}: {v}")

    format_attr("type", el.type)
    page = el.page
    if page is not None:
        format_attr("page_idx", page.page_idx)
    if "T" in el.props:
        format_attr("title", decode_text(resolve1(el.props["T"])))
    if "Lang" in el.props:
        format_attr("language", decode_text(resolve1(el.props["Lang"])))
    if "Alt" in el.props:
        format_attr("alternate_description", decode_text(resolve1(el.props["Alt"])))
    if "E" in el.props:
        format_attr("abbreviation_expansion", decode_text(resolve1(el.props["E"])))
    if "ActualText" in el.props:
        format_attr("actual_text", decode_text(resolve1(el.props["ActualText"])))
    print(f"{ws}{{", file=outfh)
    print(",\n".join(s), end="", file=outfh)
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


def extract_outline(doc: Document, args: argparse.Namespace) -> None:
    """Extract logical outline as JSON."""
    if doc.outline is None:
        LOG.info("Document has no logical structure")
        print("{}", file=args.outfile)
        return
    # FIXME: Do this incrementally as with structure above
    metadata = asobj(doc.outline)
    json.dump(metadata, args.outfile, indent=2, ensure_ascii=False)


def get_images(page: Page, imgdir: Path) -> List[Tuple[Path, Image]]:
    images = []
    for idx, img in enumerate(page.flatten(ImageObject)):
        if img.xobjid is None:
            text_bbox = ",".join(str(round(x)) for x in img.bbox)
            imgname = f"page{page.page_idx}-{idx}-inline-{text_bbox}"
        else:
            imgname = f"page{page.page_idx}-{idx}-{img.xobjid}"
        imgpath = imgdir / imgname
        # FIXME: only really support plain JPEG for now...
        fp = img.stream.get_filters()
        if fp:
            filters, params = zip(*fp)
            for f in filters:
                if f in LITERALS_DCT_DECODE:
                    imgpath = imgpath.with_suffix(".jpg")
        if imgpath.suffix == "":
            imgpath = imgpath.with_suffix(".dat")
        with open(imgpath, "wb") as outfh:
            outfh.write(img.stream.buffer)
        images.append((imgpath, asobj(img)))
    return images


def extract_images(doc: Document, args: argparse.Namespace) -> None:
    """Extract images."""
    pages = decode_page_spec(doc, args.pages)
    print("[", file=args.outfile, end="")
    if args.imgdir is not None:
        args.imgdir.mkdir(exist_ok=True, parents=True)
    last = None
    for page, images in enumerate(
        doc.pages[pages].map(functools.partial(get_images, imgdir=args.imgdir))
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


def main(argv: Union[List[str], None] = None) -> None:
    parser = make_argparse()
    args = parser.parse_args(argv)
    if args.version:
        print(playa.__version__)
        return
    elif not args.pdfs:
        parser.error("At least one PDF is required")
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.WARNING)
    try:
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
            else:
                extract_metadata(doc, args)
            doc.close()
    except RuntimeError as e:
        parser.error(f"Something went wrong:\n{e}")


if __name__ == "__main__":
    main()
