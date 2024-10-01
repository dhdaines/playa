from typing import Any, Dict, Iterator, List, Tuple

from playa import settings
from playa.pdfparser import PDFSyntaxError
from playa.pdftypes import dict_value, int_value, list_value
from playa.utils import choplist


def walk_number_tree(tree: Dict[str, Any]) -> Iterator[Tuple[int, Any]]:
    stack = [tree]
    while stack:
        item = dict_value(stack.pop())
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

    def __contains__(self, num) -> bool:
        for idx, val in self:
            if idx == num:
                return True
        return False

    def __getitem__(self, num) -> Any:
        for idx, val in self:
            if idx == num:
                return val
        raise IndexError(f"Number {num} not in tree")

    @property
    def values(self) -> List[Tuple[int, Any]]:
        values = list(self)
        # NOTE: They are supposed to be sorted! (but, I suppose, often aren't)
        if settings.STRICT:
            if not all(a[0] <= b[0] for a, b in zip(values, values[1:])):
                raise PDFSyntaxError("Number tree elements are out of order")
        else:
            values.sort(key=lambda t: t[0])

        return values
