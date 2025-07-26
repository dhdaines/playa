"""
Test the data API
"""

import playa
from dataclasses import dataclass
from typing import NamedTuple


def test_asobj_generic() -> None:
    """Test asobj on generic dataclasses and namedtuples"""

    @dataclass
    class Spam:
        spam: str

    spam = Spam(spam="spam")
    assert playa.asobj(spam) == {"spam": "spam"}

    class Eggs(NamedTuple):
        spam: str

    eggs = Eggs(spam="spam")
    assert playa.asobj(eggs) == {"spam": "spam"}
