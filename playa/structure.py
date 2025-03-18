"""
Lazy interface to PDF logical structure (PDF 1.7 sect 14.7).
"""

import functools
import logging
import re
from dataclasses import dataclass
from typing import (
    TYPE_CHECKING,
    Callable,
    Dict,
    Iterable,
    Iterator,
    List,
    Pattern,
    Union,
)

from playa.parser import LIT, PDFObject
from playa.pdftypes import ContentStream, ObjRef, literal_name, resolve1, stream_value
from playa.worker import (
    DocumentRef,
    PageRef,
    _deref_document,
    _deref_page,
    _ref_document,
)

LOG = logging.getLogger(__name__)
LITERAL_MCR = LIT("MCR")
LITERAL_OBJR = LIT("OBJR")
LITERAL_STRUCTTREEROOT = LIT("StructTreeRoot")
MatchFunc = Callable[["Element"], bool]

if TYPE_CHECKING:
    from playa.document import Document
    from playa.page import Page


@dataclass
class ContentItem:
    """Content item in logical structure tree.

    This corresponds to an individual marked content section on a
    specific page, and can be used to (lazily) find that section if
    desired.
    """

    _pageref: PageRef
    mcid: int
    stream: Union[ContentStream, None]

    @property
    def page(self) -> Union["Page", None]:
        """Specific page for this structure tree, if any."""
        if self._pageref is None:
            return None
        return _deref_page(self._pageref)


@dataclass
class ContentObject:
    """Content object in logical structure tree.

    This corresponds to a content item that is an entire PDF
    (X)Object, and can be used to (lazily) get that object.

    Not to be confused with `playa.page.ContentObject`.
    """

    _pageref: PageRef
    props: Dict[str, PDFObject]

    @property
    def page(self) -> Union["Page", None]:
        """Specific page for this structure tree, if any."""
        if self._pageref is None:
            return None
        return _deref_page(self._pageref)


def _find_all(
    elements: List["Element"],
    matcher: Union[str, Pattern[str], MatchFunc],
) -> Iterator["Element"]:
    """
    Common code for `find_all()` in trees and elements.
    """

    def match_tag(x: "Element") -> bool:
        """Match an element name."""
        return x.type == matcher

    def match_regex(x: "Element") -> bool:
        """Match an element name by regular expression."""
        return matcher.match(x.type)  # type: ignore

    if isinstance(matcher, str):
        match_func = match_tag
    elif isinstance(matcher, re.Pattern):
        match_func = match_regex
    else:
        match_func = matcher  # type: ignore
    elements.reverse()
    while elements:
        el = elements.pop()
        if match_func(el):
            yield el
        for child in reversed(list(el)):
            if isinstance(child, Element):
                elements.append(child)


class Findable(Iterable):
    """find() and find_all() methods that can be inherited to avoid
    repeating oneself"""

    def find_all(
        self, matcher: Union[str, Pattern[str], MatchFunc]
    ) -> Iterator["Element"]:
        """Iterate depth-first over matching elements in subtree.

        The `matcher` argument is either an element name, a regular
        expression, or a function taking a `Element` and
        returning `True` if the element matches.
        """
        return _find_all(list(self), matcher)

    def find(
        self, matcher: Union[str, Pattern[str], MatchFunc]
    ) -> Union["Element", None]:
        """Find the first matching element in subtree.

        The `matcher` argument is either an element name, a regular
        expression, or a function taking a `Element` and
        returning `True` if the element matches.
        """
        try:
            return next(_find_all(list(self), matcher))
        except StopIteration:
            return None


@dataclass
class Element(Findable):
    """Logical structure element.

    Attributes:
      props: Structure element dictionary (PDF 1.7 table 323).
    """

    _docref: DocumentRef
    props: Dict[str, PDFObject]

    @classmethod
    def from_dict(cls, doc: "Document", obj: Dict[str, PDFObject]) -> "Element":
        """Construct from PDF structure element dictionary."""
        return cls(_docref=_ref_document(doc), props=obj)

    @property
    def type(self) -> str:
        return literal_name(self.props["S"])

    @property
    def doc(self) -> "Document":
        """Containing document for this element."""
        return _deref_document(self._docref)

    @property
    def page(self) -> Union["Page", None]:
        """Containing page for this element, if any."""
        pg = self.props.get("Pg")
        if pg is None:
            return None
        elif isinstance(pg, ObjRef):
            try:
                return self.doc.pages.by_id(pg.objid)
            except KeyError:
                LOG.warning("'Pg' entry not found in document: %r", self.props)
        else:
            LOG.warning(
                "'Pg' entry is not an indirect object reference: %r", self.props
            )
        return None

    @property
    def parent(self) -> Union["Element", "Tree", None]:
        p = resolve1(self.props.get("P"))
        if p is None:
            return None
        if p.get("Type") is LITERAL_STRUCTTREEROOT:
            return Tree(self.doc)
        return Element.from_dict(self.doc, p)

    def __iter__(self) -> Iterator[Union["Element", ContentItem, ContentObject]]:
        if "K" in self.props:
            kids = resolve1(self.props["K"])
            yield from self._make_kids(kids)

    @functools.singledispatchmethod
    def _make_kids(
        self, k: PDFObject
    ) -> Iterator[Union["Element", ContentItem, ContentObject]]:
        """
        Make a child for this element from its K array.

        K in Element can be (PDF 1.7 Table 323):
        - a structure element (not a content item)
        - an integer marked-content ID
        - a marked-content reference dictionary
        - an object reference dictionary
        - an array of one or more of the above
        """
        LOG.warning("Unrecognized 'K' element: %r", k)
        yield from ()

    @_make_kids.register(list)
    def _make_kids_list(
        self, k: list
    ) -> Iterator[Union["Element", ContentItem, ContentObject]]:
        for el in k:
            yield from self._make_kids(resolve1(el))

    @_make_kids.register(int)
    def _make_kids_int(self, k: int) -> Iterator[ContentItem]:
        page = self.page
        if page is None:
            LOG.warning("No page found for marked-content reference: %r", k)
            return
        yield ContentItem(_pageref=page.pageref, mcid=k, stream=None)

    @_make_kids.register(dict)
    def _make_kids_dict(
        self, k: Dict[str, PDFObject]
    ) -> Iterator[Union[ContentItem, ContentObject, "Element"]]:
        ktype = k.get("Type")
        if ktype is LITERAL_MCR:
            yield from self._make_kids_mcr(k)
        elif ktype is LITERAL_OBJR:
            yield from self._make_kids_objr(k)
        else:
            yield Element(_docref=self._docref, props=k)

    def _make_kids_mcr(self, k: Dict[str, PDFObject]) -> Iterator[ContentItem]:
        mcid = resolve1(k.get("MCID"))
        if mcid is None or not isinstance(mcid, int):
            LOG.warning("'MCID' entry is not an int: %r", k)
            return
        stream: Union[ContentStream, None] = None
        pageref = self._get_kid_pageref(k)
        if pageref is None:
            return
        try:
            stream = stream_value(k["Stm"])
        except KeyError:
            pass
        except TypeError:
            LOG.warning("'Stm' entry is not a content stream: %r", k)
        # Do not care about StmOwn, we don't do appearances
        yield ContentItem(_pageref=pageref, mcid=mcid, stream=stream)

    def _make_kids_objr(self, k: Dict[str, PDFObject]) -> Iterator[ContentObject]:
        ref = k.get("Obj")
        if not isinstance(ref, ObjRef):
            LOG.warning("'Obj' entry is not an indirect object reference: %r", k)
            return
        obj = ref.resolve()
        if not isinstance(obj, dict):
            LOG.warning("'Obj' entry does not point to a dict: %r", obj)
            return
        pageref = self._get_kid_pageref(k)
        if pageref is None:
            return
        yield ContentObject(_pageref=pageref, props=obj)

    def _get_kid_pageref(self, k: Dict[str, PDFObject]) -> Union[PageRef, None]:
        pg = k.get("Pg")
        page: Union[Page, None] = None
        if pg is not None:
            if isinstance(pg, ObjRef):
                try:
                    page = self.doc.pages.by_id(pg.objid)
                except KeyError:
                    LOG.warning("'Pg' entry not found in document: %r", k)
                    page = None
            else:
                LOG.warning("'Pg' entry is not an indirect object reference: %r", k)
        if page is None:
            page = self.page
            if page is None:
                LOG.warning("No page found for marked-content reference: %r", k)
                return None
        return page.pageref


def _iter_structure(doc: "Document") -> Iterator[Element]:
    root = resolve1(doc.catalog.get("StructTreeRoot"))
    if root is None:
        return
    kids = resolve1(root.get("K"))
    if kids is None:
        LOG.warning("'K' entry in StructTreeRoot could not be resolved: %r", root)
        return
    # K in StructTreeRoot is special, it can only ever be:
    # - a single element
    # - a list of elements
    if isinstance(kids, dict):
        kids = [kids]
    elif isinstance(kids, list):
        pass
    else:
        LOG.warning(
            "'K' entry in StructTreeRoot should be dict or list but is %r", root
        )
        return
    for k in kids:
        k = resolve1(k)
        if not isinstance(k, dict):
            LOG.warning("'K' entry in StructTreeRoot contains non-element %r", k)
            continue
        # Should not happen?!?!?!?
        if k.get("Type") is LITERAL_OBJR:
            LOG.warning("'K' entry in StructTreeRoot contains object reference %r", k)
            continue
        if k.get("Type") is LITERAL_MCR:
            LOG.warning(
                "'K' entry in StructTreeRoot contains marked content reference %r", k
            )
            continue
        yield Element.from_dict(doc, k)


class Tree(Findable):
    _docref: DocumentRef

    def __init__(self, doc: "Document") -> None:
        self._docref = _ref_document(doc)

    def __iter__(self) -> Iterator[Element]:
        doc = _deref_document(self._docref)
        return _iter_structure(doc)

    @property
    def doc(self) -> "Document":
        """Document with which this structure tree is associated."""
        return _deref_document(self._docref)
