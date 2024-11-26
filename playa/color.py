from typing import Dict, NamedTuple, Union, Tuple

from playa.exceptions import PDFInterpreterError
from playa.parser import LIT, PDFObject, PSLiteral
from playa.pdftypes import num_value, list_value, literal_name, stream_value

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
        if len(components) != self.ncomponents:
            raise PDFInterpreterError(
                "%s requires %d components, got %d!"
                % (self.name, self.ncomponents, len(components))
            )
        nc = self.ncomponents
        pattern = None
        if isinstance(components[-1], PSLiteral):
            pattern = components[-1].name
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
        # FIXME: do pattern names too?
        if self.name in PREDEFINED_COLORSPACE:
            return self.name
        else:
            return f"{self.name}({self.ncomponents})"


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


def get_colorspace(spec: PDFObject) -> Union[ColorSpace, None]:
    if isinstance(spec, list):
        if spec[0] is LITERAL_ICC_BASED and len(spec) >= 2:
            return ColorSpace(spec[0].name, stream_value(spec[1])["N"], spec)
        elif spec[0] is LITERAL_DEVICE_N and len(spec) >= 2:
            # DeviceN colour spaces (PDF 1.7 sec 8.6.6.5)

            return ColorSpace(spec[0].name, len(list_value(spec[1])), spec)
        elif spec[0] is LITERAL_PATTERN and len(spec) == 2:
            # Uncoloured tiling patterns (PDF 1.7 sec 8.7.3.3)
            if spec[1] is LITERAL_PATTERN:
                raise ValueError(
                    "Underlying colour space cannot be /Pattern: %r" % (spec,)
                )
            underlying = get_colorspace(spec[1])
            if underlying is None:
                raise ValueError("Unrecognized underlying colour space: %r", (spec,))
            # Not super important what we call it but we need to know it
            # has N+1 "components" (the last one being the pattern)
            return ColorSpace(spec[0].name, underlying.ncomponents + 1, spec)
        else:
            cs = PREDEFINED_COLORSPACE.get(literal_name(spec[0]))
            if cs is None:
                return None
            return ColorSpace(cs.name, cs.ncomponents, spec)
    else:
        name = literal_name(spec)
        return PREDEFINED_COLORSPACE.get(name)
