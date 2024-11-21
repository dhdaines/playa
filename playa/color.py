import collections
from typing import Dict, List, NamedTuple, Union, Tuple

from playa.exceptions import PDFInterpreterError
from playa.parser import LIT, PDFObject, PSLiteral
from playa.pdftypes import num_value, list_value, literal_name, stream_value

LITERAL_DEVICE_GRAY = LIT("DeviceGray")
LITERAL_DEVICE_RGB = LIT("DeviceRGB")
LITERAL_DEVICE_CMYK = LIT("DeviceCMYK")
# Abbreviations for inline images
LITERAL_INLINE_DEVICE_GRAY = LIT("G")
LITERAL_INLINE_DEVICE_RGB = LIT("RGB")
LITERAL_INLINE_DEVICE_CMYK = LIT("CMYK")


Color = Tuple[Union[int, float, PSLiteral], ...]


class ColorSpace(NamedTuple):
    name: str
    ncomponents: int

    def make_color(self, *components) -> Color:
        if len(components) != self.ncomponents:
            raise PDFInterpreterError(
                "%s requires %d components, got %d!"
                % (self.name, self.ncomponents, len(components))
            )
        # FIXME: Uncolored patterns (PDF 1.7 sec 8.7.3.3) are not supported
        if isinstance(components[0], PSLiteral):
            return tuple(components)
        cc: List[float] = []
        for x in components[0 : self.ncomponents]:
            try:
                cc.append(num_value(x))
            except TypeError:
                cc.append(0)
        while len(cc) < self.ncomponents:
            cc.append(0)
        return tuple(cc)


PREDEFINED_COLORSPACE: Dict[str, ColorSpace] = collections.OrderedDict()

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
    PREDEFINED_COLORSPACE[name] = ColorSpace(name, n)


def get_colorspace(spec: PDFObject) -> Union[ColorSpace, None]:
    if isinstance(spec, list):
        name = literal_name(spec[0])
    else:
        name = literal_name(spec)
    if name == "ICCBased" and isinstance(spec, list) and len(spec) >= 2:
        return ColorSpace(name, stream_value(spec[1])["N"])
    elif name == "DeviceN" and isinstance(spec, list) and len(spec) >= 2:
        return ColorSpace(name, len(list_value(spec[1])))
    else:
        return PREDEFINED_COLORSPACE.get(name)
