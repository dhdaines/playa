"""Python implementation of Arcfour encryption algorithm.
See https://en.wikipedia.org/wiki/RC4
This code is in the public domain.

"""

from typing import List, Sequence


class Arcfour:
    def __init__(self, key: Sequence[int]) -> None:
        s: List[int] = list(range(256))
        j = 0
        kpos = 0
        klen = len(key)
        for i in range(256):
            j = (j + s[i] + key[kpos]) & 0xFF
            (s[i], s[j]) = (s[j], s[i])
            kpos += 1
            if kpos == klen:
                kpos = 0
        self.s = s
        (self.i, self.j) = (0, 0)

    def process(self, data: bytes) -> bytes:
        (i, j) = (self.i, self.j)
        s = self.s
        r = bytearray()
        for c in data:
            i = (i + 1) & 0xFF
            j = (j + s[i]) & 0xFF
            (s[i], s[j]) = (s[j], s[i])
            k = s[(s[i] + s[j]) & 0xFF]
            r.append(c ^ k)
        (self.i, self.j) = (i, j)
        return bytes(r)
