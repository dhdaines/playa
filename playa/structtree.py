"""
PDF logical structure trees.
"""

import logging
import re
from collections import deque
from dataclasses import dataclass, field
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    Iterable,
    Iterator,
    List,
    Pattern,
    Tuple,
    Union,
)

from playa.data_structures import NumberTree
from playa.page import Page
from playa.parser import KEYWORD_NULL, PSLiteral
from playa.pdftypes import ObjRef, resolve1
from playa.utils import decode_text

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from playa.document import Document


MatchFunc = Callable[["StructElement"], bool]


def _find_all(
    elements: Iterable["StructElement"],
    matcher: Union[str, Pattern[str], MatchFunc],
) -> Iterator["StructElement"]:
    """
    Common code for `find_all()` in trees and elements.
    """

    def match_tag(x: "StructElement") -> bool:
        """Match an element name."""
        return x.type == matcher

    def match_regex(x: "StructElement") -> bool:
        """Match an element name by regular expression."""
        return matcher.match(x.type)  # type: ignore

    if isinstance(matcher, str):
        match_func = match_tag
    elif isinstance(matcher, re.Pattern):
        match_func = match_regex
    else:
        match_func = matcher  # type: ignore
    d = deque(elements)
    while d:
        el = d.popleft()
        if match_func(el):
            yield el
        d.extendleft(reversed(el.children))


class Findable:
    """find() and find_all() methods that can be inherited to avoid
    repeating oneself"""

    children: List["StructElement"]

    def find_all(
        self, matcher: Union[str, Pattern[str], MatchFunc]
    ) -> Iterator["StructElement"]:
        """Iterate depth-first over matching elements in subtree.

        The `matcher` argument is either an element name, a regular
        expression, or a function taking a `StructElement` and
        returning `True` if the element matches.
        """
        return _find_all(self.children, matcher)

    def find(
        self, matcher: Union[str, Pattern[str], MatchFunc]
    ) -> Union["StructElement", None]:
        """Find the first matching element in subtree.

        The `matcher` argument is either an element name, a regular
        expression, or a function taking a `StructElement` and
        returning `True` if the element matches.
        """
        try:
            return next(_find_all(self.children, matcher))
        except StopIteration:
            return None


@dataclass
class StructElement(Findable):
    type: str
    revision: Union[int, None]
    id: Union[str, None]
    lang: Union[str, None]
    alt_text: Union[str, None]
    actual_text: Union[str, None]
    title: Union[str, None]
    page_idx: Union[int, None]
    attributes: Dict[str, Any] = field(default_factory=dict)
    mcids: List[int] = field(default_factory=list)
    children: List["StructElement"] = field(default_factory=list)

    def __iter__(self) -> Iterator["StructElement"]:
        return iter(self.children)

    def all_mcids(self) -> Iterator[Tuple[int, int]]:
        """Collect all MCIDs (with their page indices) inside a
        structure element.
        """
        # MCIDs are meaningless without a page object
        if self.mcids:
            assert self.page_idx is not None
            # Collect them depth-first to preserve ordering
            for mcid in self.mcids:
                yield self.page_idx, mcid
        d = deque(self.children)
        while d:
            el = d.popleft()
            if el.mcids:
                assert el.page_idx is not None
                for mcid in el.mcids:
                    yield el.page_idx, mcid
            d.extendleft(reversed(el.children))


class StructTree(Findable):
    """Parse the structure tree of a PDF.

    This class creates a representation of the portion of the
    structure tree that reaches marked content sections for a document
    or a subset of its pages.  Note that this is slightly different
    from the behaviour of other PDF libraries which will also include
    structure elements with no content.

    Raises:
      KeyError: If the PDF has no structure tree.

    Args:
      doc: Document from which to extract structure tree
      pages: List of (index, page) pairs - indices will be used to
             identify pages in the tree through the `page_idx`
             attribute of `StructElement`.
    """

    page: Union[Page, None]

    def __init__(
        self,
        doc: "Document",
        pages: Union[Iterable[Page], None] = None,
    ):
        if "StructTreeRoot" not in doc.catalog:
            raise KeyError("Catalog has no 'StructTreeRoot' entry")
        self.root = resolve1(doc.catalog["StructTreeRoot"])
        self.role_map = resolve1(self.root.get("RoleMap", {}))
        self.class_map = resolve1(self.root.get("ClassMap", {}))
        self.children: List[StructElement] = []
        self.page_dict: Dict[Any, Union[int, None]]

        if pages is None:
            self.page_dict = {page.pageid: page.page_idx for page in doc.pages}
            self._parse_struct_tree()
        else:
            pagelist = list(pages)
            self.page_dict = {page.pageid: page.page_idx for page in pagelist}
            parent_tree_obj = self.root.get("ParentTree")
            # If we have a single page then we will work backwards from
            # its ParentTree - this is because structure elements could
            # span multiple pages, and the "Pg" attribute is *optional*,
            # so this is the approved way to get a page's structure...
            if len(pagelist) == 1 and parent_tree_obj is not None:
                page = pagelist[0]
                parent_tree = NumberTree(parent_tree_obj)
                # If there is no marked content in the structure tree for
                # this page (which can happen even when there is a
                # structure tree) then there is no `StructParents`.
                # Note however that if there are XObjects in a page,
                # *they* may have `StructParent` (not `StructParents`)
                if "StructParents" not in page.attrs:
                    return
                parent_id = page.attrs["StructParents"]
                parent_array = resolve1(parent_tree[parent_id])
                self._parse_parent_tree(parent_array)
            else:
                # ...EXCEPT that the ParentTree is sometimes missing, in which
                # case we fall back to the non-approved way.
                self._parse_struct_tree()

    def _make_attributes(
        self, obj: Dict[str, Any], revision: Union[int, None]
    ) -> Dict[str, Any]:
        attr_obj_list = []
        for key in "C", "A":
            if key not in obj:
                continue
            attr_obj = resolve1(obj[key])
            # It could be a list of attribute objects (why?)
            if isinstance(attr_obj, list):
                attr_obj_list.extend(attr_obj)
            else:
                attr_obj_list.append(attr_obj)
        attr_objs = []
        prev_obj = None
        for aref in attr_obj_list:
            # If we find a revision number, which might "follow the
            # revision object" (the spec is not clear about what this
            # should look like but it implies they are simply adjacent
            # in a flat array), then use it to decide whether to take
            # the previous object...
            if isinstance(aref, int):
                if aref == revision and prev_obj is not None:
                    attr_objs.append(prev_obj)
                prev_obj = None
            else:
                if prev_obj is not None:
                    attr_objs.append(prev_obj)
                prev_obj = resolve1(aref)
        if prev_obj is not None:
            attr_objs.append(prev_obj)
        # Now merge all the attribute objects in the collected to a
        # single set (again, the spec doesn't really explain this but
        # does say that attributes in /A supersede those in /C)
        attr = {}
        for obj in attr_objs:
            if isinstance(obj, PSLiteral):
                key = decode_text(obj.name)
                if key not in self.class_map:
                    logger.warning("Unknown attribute class %s", key)
                    continue
                obj = self.class_map[key]
            for k, v in obj.items():
                if isinstance(v, PSLiteral):
                    attr[k] = decode_text(v.name)
                else:
                    attr[k] = obj[k]
        return attr

    def _make_element(self, obj: Any) -> Tuple[Union[StructElement, None], List[Any]]:
        # We hopefully caught these earlier
        assert "MCID" not in obj, "Uncaught MCR: %s" % obj
        assert "Obj" not in obj, "Uncaught OBJR: %s" % obj
        # Get page index if necessary
        page_idx = None
        if "Pg" in obj:
            page_objid = obj["Pg"].objid
            assert page_objid in self.page_dict, "Object on unparsed page: %s" % obj
            page_idx = self.page_dict[page_objid]
        obj_tag = ""
        if "S" in obj:
            obj_tag = decode_text(obj["S"].name)
            if obj_tag in self.role_map:
                obj_tag = decode_text(self.role_map[obj_tag].name)
        children = resolve1(obj["K"]) if "K" in obj else []
        if isinstance(children, int):  # ugh... isinstance...
            children = [children]
        elif isinstance(children, dict):  # a single object.. ugh...
            children = [obj["K"]]
        revision = obj.get("R")
        attributes = self._make_attributes(obj, revision)
        element_id = decode_text(resolve1(obj["ID"])) if "ID" in obj else None
        title = decode_text(resolve1(obj["T"])) if "T" in obj else None
        lang = decode_text(resolve1(obj["Lang"])) if "Lang" in obj else None
        alt_text = decode_text(resolve1(obj["Alt"])) if "Alt" in obj else None
        actual_text = (
            decode_text(resolve1(obj["ActualText"])) if "ActualText" in obj else None
        )
        element = StructElement(
            type=obj_tag,
            id=element_id,
            page_idx=page_idx,
            revision=revision,
            lang=lang,
            title=title,
            alt_text=alt_text,
            actual_text=actual_text,
            attributes=attributes,
        )
        return element, children

    def _parse_parent_tree(self, parent_array: List[Any]) -> None:
        """Populate the structure tree using the leaves of the parent tree for
        a given page."""
        # First walk backwards from the leaves to the root, tracking references
        d = deque(parent_array)
        s = {}
        found_root = False
        while d:
            ref = d.popleft()
            # In the case where an MCID is not associated with any
            # structure, there will be None in the parent tree
            # (previously it was KWD("null") but we now parse that
            # properly as None)
            if ref is KEYWORD_NULL or ref is None:
                continue
            if repr(ref) in s:
                continue
            obj = resolve1(ref)
            assert obj is not None  # This means the XRef tables are borked
            # This is required! It's in the spec!
            if "Type" in obj and decode_text(obj["Type"].name) == "StructTreeRoot":
                found_root = True
            else:
                # We hope that these are actual elements and not
                # references or marked-content sections...
                element, children = self._make_element(obj)
                # We have no page tree so we assume this page was parsed
                assert element is not None
                s[repr(ref)] = element, children
                d.append(obj["P"])
        # If we didn't reach the root something is quite wrong!
        assert found_root
        self._resolve_children(s)

    def on_parsed_page(self, obj: Dict[str, Any]) -> bool:
        if "Pg" not in obj:
            return True
        page_objid = obj["Pg"].objid
        return page_objid in self.page_dict

    def _parse_struct_tree(self) -> None:
        """Populate the structure tree starting from the root, skipping
        unparsed pages and empty elements."""
        root = resolve1(self.root["K"])

        # It could just be a single object ... it's in the spec (argh)
        if isinstance(root, dict):
            root = [self.root["K"]]
        d = deque(root)
        s = {}
        while d:
            ref = d.popleft()
            # In case the tree is actually a DAG and not a tree...
            if repr(ref) in s:  # pragma: nocover (shouldn't happen)
                continue
            obj = resolve1(ref)
            # Deref top-level OBJR skipping refs to unparsed pages
            if isinstance(obj, dict) and "Obj" in obj:
                if not self.on_parsed_page(obj):
                    continue
                ref = obj["Obj"]
                obj = resolve1(ref)
            element, children = self._make_element(obj)
            # Similar to above, delay resolving the children to avoid
            # tree-recursion.
            s[repr(ref)] = element, children
            for child in children:
                obj = resolve1(child)
                if isinstance(obj, dict):
                    if not self.on_parsed_page(obj):
                        continue
                    if "Obj" in obj:
                        child = obj["Obj"]
                    elif "MCID" in obj:
                        continue
                if isinstance(child, ObjRef):
                    d.append(child)

        # Traverse depth-first, removing empty elements (unsure how to
        # do this non-recursively)
        def prune(elements: List[Any]) -> List[Any]:
            next_elements = []
            for ref in elements:
                obj = resolve1(ref)
                if isinstance(ref, int):
                    next_elements.append(ref)
                    continue
                elif isinstance(obj, dict):
                    if not self.on_parsed_page(obj):
                        continue
                    if "MCID" in obj:
                        next_elements.append(obj["MCID"])
                        continue
                    elif "Obj" in obj:
                        ref = obj["Obj"]
                element, children = s[repr(ref)]
                children = prune(children)
                # See assertions below
                if element is None or not children:
                    del s[repr(ref)]
                else:
                    s[repr(ref)] = element, children
                    next_elements.append(ref)
            return next_elements

        prune(root)
        self._resolve_children(s)

    def _resolve_children(self, seen: Dict[str, Any]) -> None:
        """Resolve children starting from the tree root based on references we
        saw when traversing the structure tree.
        """
        root = resolve1(self.root["K"])
        # It could just be a single object ... it's in the spec (argh)
        if isinstance(root, dict):
            root = [self.root["K"]]
        self.children = []
        # Create top-level self.children
        parsed_root = []
        for ref in root:
            obj = resolve1(ref)
            if isinstance(obj, dict) and "Obj" in obj:
                if not self.on_parsed_page(obj):
                    continue
                ref = obj["Obj"]
            if repr(ref) in seen:
                parsed_root.append(ref)
        d = deque(parsed_root)
        while d:
            ref = d.popleft()
            element, children = seen[repr(ref)]
            assert element is not None, "Unparsed element"
            for child in children:
                obj = resolve1(child)
                if isinstance(obj, int):
                    # FIXME: This might fail! (but that indicates a
                    # programming failure as MCIDs should never occur
                    # without a page object)
                    element.mcids.append(obj)
                elif isinstance(obj, dict):
                    # Skip out-of-page MCIDS and OBJRs (FIXME: do we
                    # *really* want to do this? Perhaps we should
                    # store the page indices directly with the MCIDs?)
                    if not self.on_parsed_page(obj):
                        continue
                    if "MCID" in obj:
                        # FIXME: This might fail, for the same reasons!
                        assert element.page_idx is not None
                        element.mcids.append(obj["MCID"])
                    elif "Obj" in obj:
                        child = obj["Obj"]
                # NOTE: if, not elif, in case of OBJR above
                if isinstance(child, ObjRef):
                    child_element, _ = seen.get(repr(child), (None, None))
                    if child_element is not None:
                        element.children.append(child_element)
                        d.append(child)
        self.children = [seen[repr(ref)][0] for ref in parsed_root]

    def __iter__(self) -> Iterator[StructElement]:
        return iter(self.children)
