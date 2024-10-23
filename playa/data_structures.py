from typing import Any, Dict, Iterator, Tuple, Union

from playa.pdftypes import dict_value, int_value, list_value, str_value
from playa.utils import choplist


def walk_number_tree(
    tree: Dict[str, Any], key: Union[int, None] = None
) -> Iterator[Tuple[int, Any]]:
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


class NumberTree:
    """A PDF number tree.

    See Section 7.9.7 of the PDF 1.7 Reference.
    """

    def __init__(self, obj: Any):
        self._obj = dict_value(obj)

    def __iter__(self) -> Iterator[Tuple[int, Any]]:
        return walk_number_tree(self._obj)

    def __contains__(self, num: int) -> bool:
        for idx, val in walk_number_tree(self._obj, num):
            if idx == num:
                return True
        return False

    def __getitem__(self, num: int) -> Any:
        for idx, val in walk_number_tree(self._obj, num):
            if idx == num:
                return val
        raise IndexError(f"Number {num} not in tree")


def walk_name_tree(
    tree: Dict[str, Any], key: Union[bytes, None] = None
) -> Iterator[Tuple[bytes, Any]]:
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


class NameTree:
    """A PDF name tree.

    See Section 7.9.6 of the PDF 1.7 Reference.
    """

    def __init__(self, obj: Any):
        self._obj = dict_value(obj)

    def __iter__(self) -> Iterator[Tuple[bytes, Any]]:
        return walk_name_tree(self._obj, None)

    def __contains__(self, name: bytes) -> bool:
        for idx, val in self:
            if idx == name:
                return True
        return False

    def __getitem__(self, name: bytes) -> Any:
        for idx, val in self:
            if idx == name:
                return val
        raise IndexError("Name %r not in tree" % name)
