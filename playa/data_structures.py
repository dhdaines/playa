from typing import Dict, Iterator, Mapping, Tuple, Union, ItemsView

from playa.pdftypes import PDFObject, dict_value, int_value, list_value, str_value
from playa.utils import choplist


# TODO: NameTree and NumberTree are nearly identical and should be
# refactored to a single base class.


def walk_number_tree(
    tree: Dict[str, PDFObject], key: Union[int, None] = None
) -> Iterator[Tuple[int, PDFObject]]:
    stack = [tree]
    while stack:
        item = dict_value(stack.pop())
        if key is not None and "Limits" in item:
            (k1, k2) = list_value(item["Limits"])
            if key < k1 or k2 < key:
                continue
        if "Nums" in item:
            for k, v in choplist(2, list_value(item["Nums"])):
                yield int_value(k), v
        if "Kids" in item:
            stack.extend(reversed(list_value(item["Kids"])))


class NumberTreeItemsView(ItemsView[int, PDFObject]):
    _mapping: "NumberTree"

    def __iter__(self) -> Iterator[Tuple[int, PDFObject]]:
        yield from walk_number_tree(self._mapping._obj)


class NumberTree(Mapping[int, PDFObject]):
    """A PDF number tree.

    See Section 7.9.7 of the PDF 1.7 Reference.

    Raises:
        TypeError: If initialized with a non-dictionary.
    """

    def __init__(self, obj: PDFObject):
        self._obj = dict_value(obj)

    def __len__(self) -> int:
        return sum(1 for _ in self)

    def __iter__(self) -> Iterator[int]:
        for idx, _ in walk_number_tree(self._obj):
            yield idx

    def __getitem__(self, num: int) -> PDFObject:
        for idx, val in walk_number_tree(self._obj, num):
            if idx == num:
                return val
        raise KeyError(f"Number {num} not in tree")

    def items(self) -> NumberTreeItemsView:
        return NumberTreeItemsView(self)


def walk_name_tree(
    tree: Dict[str, PDFObject], key: Union[bytes, None] = None
) -> Iterator[Tuple[bytes, PDFObject]]:
    stack = [tree]
    while stack:
        item = dict_value(stack.pop())
        if key is not None and "Limits" in item:
            (k1, k2) = list_value(item["Limits"])
            if key < k1 or k2 < key:
                continue
        if "Names" in item:
            for k, v in choplist(2, list_value(item["Names"])):
                yield str_value(k), v
        if "Kids" in item:
            stack.extend(reversed(list_value(item["Kids"])))


class NameTreeItemsView(ItemsView[bytes, PDFObject]):
    _mapping: "NameTree"

    def __iter__(self) -> Iterator[Tuple[bytes, PDFObject]]:
        yield from walk_name_tree(self._mapping._obj)


class NameTree(Mapping[bytes, PDFObject]):
    """A PDF name tree.

    See Section 7.9.6 of the PDF 1.7 Reference.

    Raises:
        TypeError: If initialized with a non-dictionary.
    """

    def __init__(self, obj: PDFObject):
        self._obj = dict_value(obj)

    def __len__(self) -> int:
        return sum(1 for _ in self)

    def __iter__(self) -> Iterator[bytes]:
        for name, _ in walk_name_tree(self._obj):
            yield name

    def __getitem__(self, key: bytes) -> PDFObject:
        for name, val in walk_name_tree(self._obj, key):
            if name == key:
                return val
        raise KeyError("Name %r not in tree" % key)

    def items(self) -> NameTreeItemsView:
        return NameTreeItemsView(self)
