import collections
from typing import Dict, NamedTuple, Union

from playa import settings
from playa.casting import safe_float
from playa.exceptions import PDFInterpreterError
from playa.parser import LIT

LITERAL_DEVICE_GRAY = LIT("DeviceGray")
LITERAL_DEVICE_RGB = LIT("DeviceRGB")
LITERAL_DEVICE_CMYK = LIT("DeviceCMYK")
# Abbreviations for inline images
LITERAL_INLINE_DEVICE_GRAY = LIT("G")
LITERAL_INLINE_DEVICE_RGB = LIT("RGB")
LITERAL_INLINE_DEVICE_CMYK = LIT("CMYK")


class ColorRGB(NamedTuple):
    r: float
    g: float
    b: float


class ColorCMYK(NamedTuple):
    c: float
    m: float
    y: float
    k: float


Color = Union[
    float,  # Greyscale
    ColorRGB,
    ColorCMYK,  # FIXME: There is probably RGBA too
]


class PDFColorSpace:
    def __init__(self, name: str, ncomponents: int) -> None:
        self.name = name
        self.ncomponents = ncomponents

    def make_color(self, *components) -> Color:
        if settings.STRICT and len(components) != self.ncomponents:
            raise PDFInterpreterError(
                "%s requires %d components, got %d!"
                % (self.name, self.ncomponents, len(components))
            )
        if self.ncomponents == 1:
            return safe_float(components[0]) or 0.0
        elif self.ncomponents == 3:
            return ColorRGB(*(safe_float(x) or 0.0 for x in components[0:3]))
        elif self.ncomponents == 4:
            return ColorCMYK(*(safe_float(x) or 0.0 for x in components[0:4]))
        else:
            raise PDFInterpreterError(
                "unknown color space %s with %d components"
                % (self.name, self.ncomponents)
            )

    def __repr__(self) -> str:
        return "<PDFColorSpace: %s, ncomponents=%d>" % (self.name, self.ncomponents)


PREDEFINED_COLORSPACE: Dict[str, PDFColorSpace] = collections.OrderedDict()

for name, n in [
    ("DeviceGray", 1),  # default value first
    ("CalRGB", 3),
    ("CalGray", 1),
    ("Lab", 3),
    ("DeviceRGB", 3),
    ("DeviceCMYK", 4),
    ("Separation", 1),
    ("Indexed", 1),
    ("Pattern", 1),
]:
    PREDEFINED_COLORSPACE[name] = PDFColorSpace(name, n)
