import logging
import weakref
from typing import TYPE_CHECKING, Dict, List, Optional

from playa.exceptions import PDFValueError
from playa.pdftypes import dict_value, int_value, resolve1
from playa.psparser import LIT
from playa.utils import parse_rect

if TYPE_CHECKING:
    from playa.layout import LTPage
    from playa.pdfdocument import PDFDocument

log = logging.getLogger(__name__)

# some predefined literals and keywords.
LITERAL_PAGE = LIT("Page")
LITERAL_PAGES = LIT("Pages")


class PDFPage:
    """An object that holds the information about a page.

    A PDFPage object is merely a convenience class that has a set
    of keys and values, which describe the properties of a page
    and point to its contents.

    Attributes
    ----------
      pageid: any Python object that can uniquely identify the page.
      attrs: a dictionary of page attributes.
      contents: a list of PDFStream objects that represents the page content.
      resources: a dictionary of resources used by the page.
      mediabox: the physical size of the page.
      cropbox: the crop rectangle of the page.
      rotate: the page rotation (in degree).
      label: the page's label (typically, the logical page number).

    """

    def __init__(
        self,
        doc: "PDFDocument",
        pageid: object,
        attrs: object,
        label: Optional[str],
        page_number: int = 1,
    ) -> None:
        """Initialize a page object.

        doc: a PDFDocument object.
        pageid: any Python object that can uniquely identify the page.
        attrs: a dictionary of page attributes.
        label: page label string.
        page_number: page number (starting from 1)
        """
        self.doc = weakref.ref(doc)
        self.pageid = pageid
        self.attrs = dict_value(attrs)
        self.label = label
        self.page_number = page_number
        self.lastmod = resolve1(self.attrs.get("LastModified"))
        self.resources: Dict[object, object] = resolve1(
            self.attrs.get("Resources", dict()),
        )
        if "MediaBox" in self.attrs:
            self.mediabox = parse_rect(
                resolve1(val) for val in resolve1(self.attrs["MediaBox"])
            )
        else:
            log.warning(
                "MediaBox missing from /Page (and not inherited),"
                " defaulting to US Letter (612x792)"
            )
            self.mediabox = (0, 0, 612, 792)
        self.cropbox = self.mediabox
        if "CropBox" in self.attrs:
            try:
                self.cropbox = parse_rect(
                    resolve1(val) for val in resolve1(self.attrs["CropBox"])
                )
            except PDFValueError:
                log.warning("Invalid CropBox in /Page, defaulting to MediaBox")

        self.rotate = (int_value(self.attrs.get("Rotate", 0)) + 360) % 360
        self.annots = self.attrs.get("Annots")
        self.beads = self.attrs.get("B")
        if "Contents" in self.attrs:
            self.contents: List[object] = resolve1(self.attrs["Contents"])
            if not isinstance(self.contents, list):
                self.contents = [self.contents]
        else:
            self.contents = []
        self._layout: Optional["LTPage"] = None

    @property
    def layout(self) -> "LTPage":
        if self._layout is not None:
            return self._layout
        from playa.converter import PDFLayoutAnalyzer
        from playa.pdfinterp import PDFPageInterpreter

        doc = self.doc()
        if doc is None:
            raise RuntimeError("Document no longer exists!")
        # Q: How many classes does does it take a Java programmer to

        # install a lightbulb?
        device = PDFLayoutAnalyzer(
            doc.rsrcmgr,
            pageno=self.page_number,
        )
        interpreter = PDFPageInterpreter(doc.rsrcmgr, device)
        interpreter.process_page(self)
        assert device.result is not None
        self._layout = device.result
        return self._layout

    def __repr__(self) -> str:
        return f"<PDFPage: Resources={self.resources!r}, MediaBox={self.mediabox!r}>"
