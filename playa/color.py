from typing import Dict, NamedTuple, Tuple, Union

from playa.parser import LIT, PDFObject, PSLiteral
from playa.pdftypes import list_value, literal_name, num_value, resolve1, stream_value

LITERAL_DEVICE_GRAY = LIT("DeviceGray")
LITERAL_DEVICE_RGB = LIT("DeviceRGB")
LITERAL_DEVICE_CMYK = LIT("DeviceCMYK")
LITERAL_DEVICE_N = LIT("DeviceN")
LITERAL_ICC_BASED = LIT("ICCBased")
LITERAL_PATTERN = LIT("Pattern")
# Abbreviations for inline images
LITERAL_INLINE_DEVICE_GRAY = LIT("G")
LITERAL_INLINE_DEVICE_RGB = LIT("RGB")
LITERAL_INLINE_DEVICE_CMYK = LIT("CMYK")
# Rendering intents
LITERAL_RELATIVE_COLORIMETRIC = LIT("RelativeColorimetric")
LITERAL_ABSOLUTE_COLORIMETRIC = LIT("AbsoluteColorimetric")
LITERAL_SATURATION = LIT("Saturation")
LITERAL_PERCEPTUAL = LIT("Perceptual")

PREDEFINED_COLORSPACE: Dict[str, "ColorSpace"] = {}


class Color(NamedTuple):
    values: Tuple[float, ...]
    pattern: Union[str, None]


BASIC_BLACK = Color((0,), None)


class ColorSpace(NamedTuple):
    name: str
    ncomponents: int
    spec: PDFObject = None

    def make_color(self, *components) -> Color:
        pattern = None
        nc = self.ncomponents
        if components and isinstance(components[-1], PSLiteral):
            pattern = components[-1].name
            components = components[:-1]
            # Remove the pattern we added to ncomponents
            nc -= 1
        cc = []
        for x in components[:nc]:
            try:
                cc.append(num_value(x))
            except TypeError:
                cc.append(0)
        while len(cc) < nc:
            cc.append(0)
        return Color(tuple(cc), pattern)

    def __str__(self):
        return self.name


for name, n in [
    ("DeviceGray", 1),
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


def get_colorspace(
    spec: PDFObject, csid: Union[str, None] = None
) -> Union[ColorSpace, None]:
    if isinstance(spec, PSLiteral):
        name = literal_name(spec)
        return PREDEFINED_COLORSPACE.get(name)
    elif isinstance(spec, list):
        name = spec[0].name if csid is None else csid
        if spec[0] is LITERAL_ICC_BASED and len(spec) >= 2:
            n = stream_value(spec[1])["N"]
            return ColorSpace(name, n, spec)
        elif spec[0] is LITERAL_DEVICE_N and len(spec) >= 2:
            # DeviceN colour spaces (PDF 1.7 sec 8.6.6.5)
            n = len(list_value(spec[1]))
            return ColorSpace(name, n, spec)
        elif spec[0] is LITERAL_PATTERN and len(spec) == 2:
            # Uncoloured tiling patterns (PDF 1.7 sec 8.7.3.3)
            if spec[1] is LITERAL_PATTERN:
                raise ValueError(
                    "Underlying colour space cannot be /Pattern: %r" % (spec,)
                )
            underlying = get_colorspace(resolve1(spec[1]))
            if underlying is None:
                raise ValueError("Unrecognized underlying colour space: %r", (spec,))
            # Not super important what we call it but we need to know it
            # has N+1 "components" (the last one being the pattern)
            return ColorSpace(name, underlying.ncomponents + 1, spec)
        else:
            cs = PREDEFINED_COLORSPACE.get(literal_name(resolve1(spec[0])))
            if cs is None:
                return None
            return ColorSpace(cs.name, cs.ncomponents, spec)
    return None
