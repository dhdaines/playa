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
LITERAL_INLINE_INDEXED = LIT("I")
# Rendering intents
LITERAL_RELATIVE_COLORIMETRIC = LIT("RelativeColorimetric")
LITERAL_ABSOLUTE_COLORIMETRIC = LIT("AbsoluteColorimetric")
LITERAL_SATURATION = LIT("Saturation")
LITERAL_PERCEPTUAL = LIT("Perceptual")
# Use of black point compensation
LITERAL_DEFAULT = LIT("Default")
# Blend modes
LITERAL_NORMAL = LIT("Normal")

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
PREDEFINED_INLINE_COLORSPACE = {
    LITERAL_INLINE_DEVICE_GRAY: PREDEFINED_COLORSPACE["DeviceGray"],
    LITERAL_INLINE_DEVICE_RGB: PREDEFINED_COLORSPACE["DeviceRGB"],
    LITERAL_INLINE_DEVICE_CMYK: PREDEFINED_COLORSPACE["DeviceCMYK"],
    LITERAL_INLINE_INDEXED: PREDEFINED_COLORSPACE["Indexed"],
}


def get_colorspace(
    spec: PDFObject, csid: Union[str, None] = None
) -> Union[ColorSpace, None]:
    if isinstance(spec, PSLiteral):
        if spec in PREDEFINED_INLINE_COLORSPACE:
            return PREDEFINED_INLINE_COLORSPACE[spec]
        name = literal_name(spec)
        return PREDEFINED_COLORSPACE.get(name)
    elif isinstance(spec, list):
        csname = resolve1(spec[0])
        assert isinstance(csname, PSLiteral), (
            "Expected a name for color space, got %r" % (csname,)
        )
        if csid is None:
            csid = csname.name
        if csname is LITERAL_ICC_BASED and len(spec) >= 2:
            profile = stream_value(spec[1])
            if "N" in profile:
                n = profile["N"]
            else:
                # Get the color space from the ICC profile
                space = profile.buffer[16:20]
                if space == b"GRAY":
                    n = 1
                elif space == b"CMYK":
                    n = 4
                elif space[1:3] == b"CLR":
                    n = int(space[0:1], base=16)
                else:
                    # All the other spaces have 3 components
                    n = 3
            return ColorSpace(csid, n, spec)
        elif csname is LITERAL_DEVICE_N and len(spec) >= 2:
            # DeviceN colour spaces (PDF 1.7 sec 8.6.6.5)
            n = len(list_value(spec[1]))
            return ColorSpace(csid, n, spec)
        elif csname is LITERAL_PATTERN and len(spec) == 2:
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
            return ColorSpace(csid, underlying.ncomponents + 1, spec)
        else:
            # Handle Indexed, ICCBased, etc, etc, generically
            cs: Union[ColorSpace, None] = None
            if csname in PREDEFINED_INLINE_COLORSPACE:
                cs = PREDEFINED_INLINE_COLORSPACE[csname]
            else:
                cs = PREDEFINED_COLORSPACE.get(csname.name)
            if cs is None:
                return None
            return ColorSpace(csid, cs.ncomponents, spec)
    return None
