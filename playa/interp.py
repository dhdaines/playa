"""
Interpreter for PDF content streams.
"""

import itertools
import logging
import operator
import re
from copy import copy
from dataclasses import dataclass
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    Iterable,
    Iterator,
    List,
    Tuple,
    Union,
    Sequence,
)

from playa.color import PREDEFINED_COLORSPACE, ColorSpace, get_colorspace
from playa.content import (
    ContentObject,
    DashPattern,
    GraphicState,
    ImageObject,
    MarkedContent,
    PathObject,
    PathOperator,
    PathSegment,
    TagObject,
    TextObject,
    XObjectObject,
)
from playa.font import Font
from playa.parser import KWD, ContentParser, InlineImage, PDFObject
from playa.pdftypes import (
    BBOX_NONE,
    LIT,
    MATRIX_IDENTITY,
    ContentStream,
    Matrix,
    ObjRef,
    Point,
    PSKeyword,
    PSLiteral,
    Rect,
    bool_value,
    dict_value,
    int_value,
    list_value,
    literal_name,
    num_value,
    resolve1,
    stream_value,
)
from playa.utils import mult_matrix
from playa.worker import _deref_document

if TYPE_CHECKING:
    from playa.document import Document
    from playa.page import Page

log = logging.getLogger(__name__)

# some predefined literals and keywords.
LITERAL_PAGE = LIT("Page")
LITERAL_PAGES = LIT("Pages")
LITERAL_FORM = LIT("Form")
LITERAL_IMAGE = LIT("Image")
TextSeq = Iterable[Union[int, float, bytes]]


def make_seg(operator: PathOperator, *points: Point):
    return PathSegment(operator, points)


@dataclass
class TextState:
    """Mutable text state (not for public consumption).

    Exceptionally, the line matrix and text matrix are represented
    more compactly with the line matrix itself in `line_matrix`, which
    gets translated by `glyph_offset` for the current glyph (note:
    expressed in **user space**), which pdfminer confusingly called
    `linematrix`, to produce the text matrix.

    Attributes:
      line_matrix: The text line matrix, which defines (in user
        space) the start of the current line of text, which may or may
        not correspond to an actual line because PDF is a presentation
        format.
      glyph_offset: The offset of the current glyph with relation to
        the line matrix, in text space units.
    """

    line_matrix: Matrix = MATRIX_IDENTITY
    glyph_offset: Point = (0, 0)

    def reset(self) -> None:
        """Reset the text state"""
        self.line_matrix = MATRIX_IDENTITY
        self.glyph_offset = (0, 0)


def _make_fontmap(mapping: PDFObject, doc: "Document") -> Dict[str, Font]:
    fontmap: Dict[str, Font] = {}
    mapping = resolve1(mapping)
    if not isinstance(mapping, dict):
        log.warning("Font mapping not a dict: %r", mapping)
        return fontmap
    for fontid, spec in mapping.items():
        objid = 0  # Not a valid object ID (will not cache)
        if isinstance(spec, ObjRef):
            objid = spec.objid
        try:
            fontmap[fontid] = doc.get_font(objid, dict_value(spec))
        except Exception:
            log.warning(
                "Invalid font dictionary for Font %r: %r",
                fontid,
                spec,
                exc_info=True,
            )
            fontmap[fontid] = doc.get_font(objid, None)
    return fontmap


def _make_contentmap(
    streamer: Iterable["ContentObject"],
) -> Sequence[Union[None, Iterable["ContentObject"]]]:
    contents: List[Union[None, Iterable["ContentObject"]]] = []
    for mcid, objs in itertools.groupby(streamer, operator.attrgetter("mcid")):
        if mcid is None:
            continue
        while len(contents) <= mcid:
            contents.append(None)
        contents[mcid] = [obj.finalize() for obj in objs]
    return contents


class LazyInterpreter:
    """Interpret the page yielding lazy objects."""

    ctm: Matrix

    def __init__(
        self,
        page: "Page",
        contents: Iterable[PDFObject],
        resources: Union[Dict, None] = None,
        ctm: Union[Matrix, None] = None,
        gstate: Union[GraphicState, None] = None,
        parent_key: Union[int, None] = None,
        ignore_colours: bool = False,
    ) -> None:
        self._dispatch: Dict[PSKeyword, Tuple[Callable, int]] = {}
        for name in dir(self):
            if name.startswith("do_"):
                func = getattr(self, name)
                name = re.sub(r"_a", "*", name[3:])
                if name == "_q":
                    name = "'"
                if name == "_w":
                    name = '"'
                kwd = KWD(name.encode("iso-8859-1"))
                nargs = func.__code__.co_argcount - 1
                self._dispatch[kwd] = (func, nargs)
        self.page = page
        self.parent_key = (
            page.attrs.get("StructParents") if parent_key is None else parent_key
        )
        self.contents = contents
        self.ignore_colours = ignore_colours
        self.init_resources(page, page.resources if resources is None else resources)
        self.init_state(page.ctm if ctm is None else ctm, gstate)

    def init_resources(self, page: "Page", resources: Dict) -> None:
        """Prepare the fonts and XObjects listed in the Resource attribute."""
        self.resources = resources
        self.fontmap: Dict[str, Font] = {}
        self.xobjmap = {}
        self.csmap: Dict[str, ColorSpace] = copy(PREDEFINED_COLORSPACE)
        self.extgstatemap = {}
        if not self.resources:
            return

        for k, v in dict_value(self.resources).items():
            mapping = resolve1(v)
            if mapping is None:
                log.warning("Missing %s mapping", k)
                continue
            if k == "ProcSet":
                continue
            # PDF 2.0, sec 7.8.3, Table 34, ProcSet is an array, everything else are dictionaries
            if not isinstance(mapping, dict):
                log.warning("%s mapping not a dict: %r", k, mapping)
                continue
            if k == "Font":
                self.fontmap = _make_fontmap(mapping, _deref_document(page.docref))
            elif k == "ColorSpace":
                for csid, spec in mapping.items():
                    colorspace = get_colorspace(resolve1(spec), csid)
                    if colorspace is not None:
                        self.csmap[csid] = colorspace
            elif k == "XObject":
                self.xobjmap = mapping
            elif k == "ExtGState":
                self.extgstatemap = mapping

    def init_state(self, ctm: Matrix, gstate: Union[GraphicState, None] = None) -> None:
        self.gstack: List[Tuple[Matrix, GraphicState, TextState]] = []
        self.ctm = ctm
        # Note the copy here, a new interpreter *always* creates a new
        # graphics state (including text state and CTM)
        self.graphicstate = GraphicState() if gstate is None else copy(gstate)
        # Mutable text state (just the matrices) - this is not
        # supposed to exist outside BT/ET pairs, but we will tolerate
        # it.  In PDF 2.0 it gets saved/restored on the stack by q/Q
        self.textstate: TextState = TextState()
        # Current path (FIXME: is this in the graphics state too?)
        self.curpath: List[PathSegment] = []
        # argstack: stack for command arguments.
        self.argstack: List[PDFObject] = []
        # mcstack: stack for marked content sections.
        self.mcstack: Tuple[MarkedContent, ...] = ()

    def push(self, obj: PDFObject) -> None:
        self.argstack.append(obj)

    def pop(self, n: int) -> List[PDFObject]:
        if n == 0:
            return []
        x = self.argstack[-n:]
        self.argstack = self.argstack[:-n]
        return x

    def __iter__(self) -> Iterator[ContentObject]:
        parser = ContentParser(self.contents, self.page.doc)
        for _, obj in parser:
            # These are handled inside the parser as they don't obey
            # the normal syntax rules (PDF 1.7 sec 8.9.7)
            if isinstance(obj, InlineImage):
                co = self.do_EI(obj)
                if co is not None:
                    yield co
            elif isinstance(obj, PSKeyword):
                if obj in self._dispatch:
                    method, nargs = self._dispatch[obj]
                    co = None
                    if nargs:
                        args = self.pop(nargs)
                        if len(args) != nargs:
                            log.warning(
                                "Insufficient arguments (%d) for operator: %r",
                                len(args),
                                obj,
                            )
                        else:
                            try:
                                co = method(*args)
                            except TypeError as e:
                                log.warning(
                                    "Incorrect type of arguments(%r) for operator %r: %s",
                                    args,
                                    obj,
                                    e,
                                )
                    else:
                        co = method()
                    if co is not None:
                        yield co
                    if isinstance(co, TextObject):
                        self.textstate.glyph_offset = co._get_next_glyph_offset()
                else:
                    # TODO: This can get very verbose
                    log.warning("Unknown operator: %r", obj)
            else:
                self.push(obj)

    def create(self, object_class, **kwargs) -> Union[ContentObject, None]:
        return object_class(
            _pageref=self.page.pageref,
            _parentkey=self.parent_key,
            ctm=self.ctm,
            mcstack=self.mcstack,
            gstate=self.graphicstate,
            **kwargs,
        )

    def do_S(self) -> Union[ContentObject, None]:
        """Stroke path"""
        if not self.curpath:
            return None
        curpath = self.curpath
        self.curpath = []
        return self.create(
            PathObject,
            stroke=True,
            fill=False,
            evenodd=False,
            raw_segments=curpath,
        )

    def do_s(self) -> Union[ContentObject, None]:
        """Close and stroke path"""
        self.do_h()
        return self.do_S()

    def do_f(self) -> Union[ContentObject, None]:
        """Fill path using nonzero winding number rule"""
        if not self.curpath:
            return None
        curpath = self.curpath
        self.curpath = []
        return self.create(
            PathObject,
            stroke=False,
            fill=True,
            evenodd=False,
            raw_segments=curpath,
        )

    def do_F(self) -> Union[ContentObject, None]:
        """Fill path using nonzero winding number rule (obsolete)"""
        return self.do_f()

    def do_f_a(self) -> Union[ContentObject, None]:
        """Fill path using even-odd rule"""
        if not self.curpath:
            return None
        curpath = self.curpath
        self.curpath = []
        return self.create(
            PathObject,
            stroke=False,
            fill=True,
            evenodd=True,
            raw_segments=curpath,
        )

    def do_B(self) -> Union[ContentObject, None]:
        """Fill and stroke path using nonzero winding number rule"""
        if not self.curpath:
            return None
        curpath = self.curpath
        self.curpath = []
        return self.create(
            PathObject,
            stroke=True,
            fill=True,
            evenodd=False,
            raw_segments=curpath,
        )

    def do_B_a(self) -> Union[ContentObject, None]:
        """Fill and stroke path using even-odd rule"""
        if not self.curpath:
            return None
        curpath = self.curpath
        self.curpath = []
        return self.create(
            PathObject,
            stroke=True,
            fill=True,
            evenodd=True,
            raw_segments=curpath,
        )

    def do_b(self) -> Union[ContentObject, None]:
        """Close, fill, and stroke path using nonzero winding number rule"""
        self.do_h()
        return self.do_B()

    def do_b_a(self) -> Union[ContentObject, None]:
        """Close, fill, and stroke path using even-odd rule"""
        self.do_h()
        return self.do_B_a()

    def do_TJ(self, strings: PDFObject) -> Union[ContentObject, None]:
        """Show one or more text strings, allowing individual glyph
        positioning"""
        args: List[Union[bytes, float]] = []
        has_text = False
        for s in list_value(strings):
            if isinstance(s, (int, float)):
                args.append(s)
            elif isinstance(s, bytes):
                if s:
                    has_text = True
                args.append(s)
            else:
                log.warning(
                    "Ignoring non-string/number %r in text object %r", s, strings
                )
        obj = self.create(
            TextObject,
            line_matrix=self.textstate.line_matrix,
            _glyph_offset=self.textstate.glyph_offset,
            args=args,
        )
        if obj is not None:
            if has_text:
                return obj
            # Even without text, TJ can still update the glyph offset
            assert isinstance(obj, TextObject)
            self.textstate.glyph_offset = obj._get_next_glyph_offset()
        return None

    def do_Tj(self, s: PDFObject) -> Union[ContentObject, None]:
        """Show a text string"""
        return self.do_TJ([s])

    def do__q(self, s: PDFObject) -> Union[ContentObject, None]:
        """Move to next line and show text

        The ' (single quote) operator.
        """
        self.do_T_a()
        return self.do_TJ([s])

    def do__w(
        self, aw: PDFObject, ac: PDFObject, s: PDFObject
    ) -> Union[ContentObject, None]:
        """Set word and character spacing, move to next line, and show text

        The " (double quote) operator.
        """
        self.do_Tw(aw)
        self.do_Tc(ac)
        return self.do_TJ([s])

    def do_EI(self, obj: PDFObject) -> Union[ContentObject, None]:
        """End inline image object"""
        if isinstance(obj, InlineImage):
            # Inline images are not XObjects, have no xobjid
            return self.render_image(None, obj)
        else:
            log.warning("EI has unknown argument type: %r", obj)
            return None

    def do_Do(self, xobjid_arg: PDFObject) -> Union[ContentObject, None]:
        """Invoke named XObject"""
        xobjid = literal_name(xobjid_arg)
        try:
            xobj = stream_value(self.xobjmap[xobjid])
        except KeyError:
            log.debug("Undefined xobject id: %r", xobjid)
            return None
        except TypeError as e:
            raise TypeError(f"Empty or invalid xobject with id {xobjid!r}") from e
        subtype = xobj.get("Subtype")
        if subtype is LITERAL_FORM:
            # PDF Ref 1.7, # 4.9
            #
            # When the Do operator is applied to a form XObject,
            # it does the following tasks:
            #
            # 1. Saves the current graphics state, as if by invoking the q operator
            # ...
            # 5. Restores the saved graphics state, as if by invoking the Q operator
            #
            # The lazy interpretation of this is, obviously, that
            # we simply create an XObjectObject with a copy of the
            # current graphics state.  The copying is actually
            # done (lazily, of course) when construcitng a new
            # LazyInterpreter, not here.
            return XObjectObject.from_stream(
                stream=xobj,
                page=self.page,
                xobjid=xobjid,
                ctm=self.ctm,
                gstate=self.graphicstate,
                mcstack=self.mcstack,
            )
        elif subtype is LITERAL_IMAGE:
            return self.render_image(xobjid, xobj)
        else:
            log.debug("Unsupported XObject %r of type %r: %r", xobjid, subtype, xobj)
        return None

    def render_image(
        self, xobjid: Union[str, None], stream: ContentStream
    ) -> Union[ContentObject, None]:
        # Look up colorspace in resources first!
        cspec = resolve1(stream.get_any(("CS", "ColorSpace")))
        if isinstance(cspec, PSLiteral) and cspec.name in self.csmap:
            colorspace: Union[ColorSpace, None] = self.csmap[cspec.name]
        else:
            colorspace = get_colorspace(cspec)
        # Cache it in the stream object to avoid confusion
        if colorspace is not None:
            stream.colorspace = colorspace
        obj = self.create(
            ImageObject,
            stream=stream,
            xobjid=xobjid,
            srcsize=(stream.width, stream.height),
            # Ensure it is always a bool (whither mypy here?)
            imagemask=not not stream.get_any(("IM", "ImageMask")),
            bits=stream.bits,
            colorspace=colorspace,
        )
        # Override parent key if one is defined on the image specifically
        if obj is not None and "StructParent" in stream:
            obj._parentkey = int_value(stream["StructParent"])
        return obj

    def do_q(self) -> None:
        """Save graphics state"""
        self.gstack.append((self.ctm, copy(self.graphicstate), copy(self.textstate)))

    def do_Q(self) -> None:
        """Restore graphics state"""
        if self.gstack:
            self.ctm, self.graphicstate, self.textstate = self.gstack.pop()

    def do_cm(
        self,
        a1: PDFObject,
        b1: PDFObject,
        c1: PDFObject,
        d1: PDFObject,
        e1: PDFObject,
        f1: PDFObject,
    ) -> None:
        """Concatenate matrix to current transformation matrix"""
        cm = (
            num_value(a1),
            num_value(b1),
            num_value(c1),
            num_value(d1),
            num_value(e1),
            num_value(f1),
        )
        self.ctm = mult_matrix(cm, self.ctm)

    def do_w(self, linewidth: PDFObject) -> None:
        """Set line width"""
        self.graphicstate.linewidth = num_value(linewidth)

    def do_J(self, linecap: PDFObject) -> None:
        """Set line cap style"""
        self.graphicstate.linecap = int_value(linecap)

    def do_j(self, linejoin: PDFObject) -> None:
        """Set line join style"""
        self.graphicstate.linejoin = int_value(linejoin)

    def do_M(self, miterlimit: PDFObject) -> None:
        """Set miter limit"""
        self.graphicstate.miterlimit = num_value(miterlimit)

    def do_d(self, dash: PDFObject, phase: PDFObject) -> None:
        """Set line dash pattern"""
        ndash = tuple(num_value(x) for x in list_value(dash))
        self.graphicstate.dash = DashPattern(ndash, num_value(phase))

    def do_ri(self, intent: PDFObject) -> None:
        """Set color rendering intent"""
        if self.ignore_colours:
            return
        if isinstance(intent, PSLiteral):
            # Should possibly check that it is a valid intent
            self.graphicstate.intent = intent
        else:
            raise TypeError(f"Not a name: {intent!r}")

    def do_i(self, flatness: PDFObject) -> None:
        """Set flatness tolerance"""
        self.graphicstate.flatness = num_value(flatness)

    def do_gs(self, name: PDFObject) -> None:
        """Set parameters from graphics state parameter dictionary"""
        try:
            extgstate = dict_value(self.extgstatemap[literal_name(name)])
        except KeyError:
            log.warning("Undefined ExtGState: %r", name)
            return
        # PDF 2.0, sec 8.4.5, Table 57
        # Skipping Device-dependent graphics state parameters except
        # for flatness tolerance
        if "LW" in extgstate:
            self.do_w(extgstate["LW"])
        if "LC" in extgstate:
            self.do_J(extgstate["LC"])
        if "LJ" in extgstate:
            self.do_j(extgstate["LJ"])
        if "ML" in extgstate:
            self.do_M(extgstate["ML"])
        if "D" in extgstate:
            dash, phase = list_value(extgstate["D"])
            self.do_d(dash, phase)
        if "RI" in extgstate:
            self.do_ri(extgstate["RI"])
        if "Font" in extgstate:
            fontref, fontsize = list_value(extgstate["Font"])
            self.graphicstate.font = self.page.doc.get_font(fontref.objid, None)
            self.graphicstate.fontsize = num_value(fontsize)
        if "FL" in extgstate:
            self.do_i(extgstate["FL"])
        if "SA" in extgstate:
            self.graphicstate.stroke_adjustment = bool_value(extgstate["SA"])
        if "BM" in extgstate:
            bm = extgstate["BM"]
            if isinstance(bm, PSLiteral):
                self.graphicstate.blend_mode = bm
            else:
                bml: List[PSLiteral] = []
                for x in list_value(bm):
                    if isinstance(PSLiteral, x):
                        raise TypeError(f"Not a name: {x!r}")
                    bml.append(x)
                self.graphicstate.blend_mode = bml
        if "SMask" in extgstate:
            smask = extgstate["SMask"]
            if isinstance(smask, PSLiteral):
                self.graphicstate.smask = None
            else:
                self.graphicstate.smask = dict_value(smask)
        if "CA" in extgstate:
            self.graphicstate.salpha = num_value(extgstate["CA"])
        if "ca" in extgstate:
            self.graphicstate.nalpha = num_value(extgstate["ca"])
        if "AIS" in extgstate:
            self.graphicstate.alpha_source = bool_value(extgstate["AIS"])
        if "TK" in extgstate:
            self.graphicstate.knockout = bool_value(extgstate["TK"])
        if "UseBlackPtComp" in extgstate and not self.ignore_colours:
            black_pt_comp = extgstate["UseBlackPtComp"]
            assert isinstance(black_pt_comp, PSLiteral)
            self.graphicstate.black_pt_comp = black_pt_comp
        # Also ignored with ignore_colours, but we do not support
        # them: TR, TR2, HT, BG, BG2, UCR, UCR2

    def do_m(self, x: PDFObject, y: PDFObject) -> None:
        """Begin new subpath"""
        self.curpath.append(make_seg("m", (num_value(x), num_value(y))))

    def do_l(self, x: PDFObject, y: PDFObject) -> None:
        """Append straight line segment to path"""
        self.curpath.append(make_seg("l", (num_value(x), num_value(y))))

    def do_c(
        self,
        x1: PDFObject,
        y1: PDFObject,
        x2: PDFObject,
        y2: PDFObject,
        x3: PDFObject,
        y3: PDFObject,
    ) -> None:
        """Append curved segment to path (three control points)"""
        self.curpath.append(
            make_seg(
                "c",
                (num_value(x1), num_value(y1)),
                (num_value(x2), num_value(y2)),
                (num_value(x3), num_value(y3)),
            ),
        )

    def do_v(self, x2: PDFObject, y2: PDFObject, x3: PDFObject, y3: PDFObject) -> None:
        """Append curved segment to path (initial point replicated)"""
        self.curpath.append(
            make_seg(
                "v",
                (num_value(x2), num_value(y2)),
                (num_value(x3), num_value(y3)),
            )
        )

    def do_y(self, x1: PDFObject, y1: PDFObject, x3: PDFObject, y3: PDFObject) -> None:
        """Append curved segment to path (final point replicated)"""
        self.curpath.append(
            make_seg(
                "y",
                (num_value(x1), num_value(y1)),
                (num_value(x3), num_value(y3)),
            )
        )

    def do_h(self) -> None:
        """Close subpath"""
        self.curpath.append(make_seg("h"))

    def do_re(self, x: PDFObject, y: PDFObject, w: PDFObject, h: PDFObject) -> None:
        """Append rectangle to path"""
        x = num_value(x)
        y = num_value(y)
        w = num_value(w)
        h = num_value(h)
        self.curpath.append(make_seg("m", (x, y)))
        self.curpath.append(make_seg("l", (x + w, y)))
        self.curpath.append(make_seg("l", (x + w, y + h)))
        self.curpath.append(make_seg("l", (x, y + h)))
        self.curpath.append(make_seg("h"))

    def do_n(self) -> None:
        """End path without filling or stroking"""
        self.curpath = []

    def do_W(self) -> None:
        """Set clipping path using nonzero winding number rule"""

    def do_W_a(self) -> None:
        """Set clipping path using even-odd rule"""

    def do_CS(self, name: PDFObject) -> None:
        """Set color space for stroking operators

        Introduced in PDF 1.1
        """
        if self.ignore_colours:
            return
        try:
            self.graphicstate.scs = self.csmap[literal_name(name)]
        except KeyError:
            log.warning("Undefined ColorSpace: %r", name)

    def do_cs(self, name: PDFObject) -> None:
        """Set color space for nonstroking operators"""
        if self.ignore_colours:
            return
        try:
            self.graphicstate.ncs = self.csmap[literal_name(name)]
        except KeyError:
            log.warning("Undefined ColorSpace: %r", name)

    def do_G(self, gray: PDFObject) -> None:
        """Set gray level for stroking operators"""
        if self.ignore_colours:
            return
        self.graphicstate.scs = self.csmap["DeviceGray"]
        self.graphicstate.scolor = self.graphicstate.scs.make_color(gray)

    def do_g(self, gray: PDFObject) -> None:
        """Set gray level for nonstroking operators"""
        if self.ignore_colours:
            return
        self.graphicstate.ncs = self.csmap["DeviceGray"]
        self.graphicstate.ncolor = self.graphicstate.ncs.make_color(gray)

    def do_RG(self, r: PDFObject, g: PDFObject, b: PDFObject) -> None:
        """Set RGB color for stroking operators"""
        if self.ignore_colours:
            return
        self.graphicstate.scs = self.csmap["DeviceRGB"]
        self.graphicstate.scolor = self.graphicstate.scs.make_color(r, g, b)

    def do_rg(self, r: PDFObject, g: PDFObject, b: PDFObject) -> None:
        """Set RGB color for nonstroking operators"""
        if self.ignore_colours:
            return
        self.graphicstate.ncs = self.csmap["DeviceRGB"]
        self.graphicstate.ncolor = self.graphicstate.ncs.make_color(r, g, b)

    def do_K(self, c: PDFObject, m: PDFObject, y: PDFObject, k: PDFObject) -> None:
        """Set CMYK color for stroking operators"""
        if self.ignore_colours:
            return
        self.graphicstate.scs = self.csmap["DeviceCMYK"]
        self.graphicstate.scolor = self.graphicstate.scs.make_color(c, m, y, k)

    def do_k(self, c: PDFObject, m: PDFObject, y: PDFObject, k: PDFObject) -> None:
        """Set CMYK color for nonstroking operators"""
        if self.ignore_colours:
            return
        self.graphicstate.ncs = self.csmap["DeviceCMYK"]
        self.graphicstate.ncolor = self.graphicstate.ncs.make_color(c, m, y, k)

    def do_SCN(self) -> None:
        """Set color for stroking operators."""
        if self.ignore_colours:
            return
        assert self.graphicstate.scs is not None  # it is always not None now
        self.graphicstate.scolor = self.graphicstate.scs.make_color(
            *self.pop(self.graphicstate.scs.ncomponents)
        )

    def do_scn(self) -> None:
        """Set color for nonstroking operators"""
        if self.ignore_colours:
            return
        assert self.graphicstate.ncs is not None  # it is always not None now
        self.graphicstate.ncolor = self.graphicstate.ncs.make_color(
            *self.pop(self.graphicstate.ncs.ncomponents)
        )

    def do_SC(self) -> None:
        """Set color for stroking operators"""
        self.do_SCN()

    def do_sc(self) -> None:
        """Set color for nonstroking operators"""
        self.do_scn()

    def do_sh(self, name: Any) -> None:
        """Paint area defined by shading pattern"""
        if self.ignore_colours:
            return
        log.debug("sh operator currently unsupported")

    def do_BT(self) -> None:
        """Begin text object.

        Initializing the text matrix, Tm, and the text line matrix,
        Tlm, to the identity matrix. Text objects cannot be nested; a
        second BT cannot appear before an ET.  While Tm and Tlm are
        saved and restored with the graphics state, they do not
        persist outside a BT/ET pair.

        """
        self.textstate.reset()

    def do_ET(self) -> None:
        """End a text object"""

    def do_BX(self) -> None:
        """Begin compatibility section"""

    def do_EX(self) -> None:
        """End compatibility section"""

    def do_Tc(self, space: PDFObject) -> None:
        """Set character spacing.

        Character spacing is used by the Tj, TJ, and ' operators.

        :param space: a number expressed in unscaled text space units.
        """
        self.graphicstate.charspace = num_value(space)

    def do_Tw(self, space: PDFObject) -> None:
        """Set the word spacing.

        Word spacing is used by the Tj, TJ, and ' operators.

        :param space: a number expressed in unscaled text space units
        """
        self.graphicstate.wordspace = num_value(space)

    def do_Tz(self, scale: PDFObject) -> None:
        """Set the horizontal scaling.

        :param scale: is a number specifying the percentage of the normal width
        """
        self.graphicstate.scaling = num_value(scale)

    def do_TL(self, leading: PDFObject) -> None:
        """Set the text leading.

        Text leading is used only by the T*, ', and " operators.

        :param leading: a number expressed in unscaled text space units
        """
        self.graphicstate.leading = num_value(leading)

    def do_Tf(self, fontid: PDFObject, fontsize: PDFObject) -> None:
        """Set the text font

        :param fontid: the name of a font resource in the Font subdictionary
            of the current resource dictionary
        :param fontsize: size is a number representing a scale factor.
        """
        try:
            self.graphicstate.font = self.fontmap[literal_name(fontid)]
        except KeyError:
            log.warning("Undefined Font id: %r", fontid)
            doc = _deref_document(self.page.docref)
            self.graphicstate.font = doc.get_font()
        self.graphicstate.fontsize = num_value(fontsize)

    def do_Tr(self, render: PDFObject) -> None:
        """Set the text rendering mode"""
        self.graphicstate.render_mode = int_value(render)

    def do_Ts(self, rise: PDFObject) -> None:
        """Set the text rise

        :param rise: a number expressed in unscaled text space units
        """
        self.graphicstate.rise = num_value(rise)

    def do_Td(self, tx: PDFObject, ty: PDFObject) -> None:
        """Move to the start of the next line

        Offset from the start of the current line by (tx , ty).
        """
        try:
            tx = num_value(tx)
            ty = num_value(ty)
            (a, b, c, d, e, f) = self.textstate.line_matrix
            e_new = tx * a + ty * c + e
            f_new = tx * b + ty * d + f
            self.textstate.line_matrix = (a, b, c, d, e_new, f_new)
        except TypeError as e:
            raise TypeError(f"Invalid offset ({tx!r}, {ty!r})") from e
        self.textstate.glyph_offset = (0, 0)

    def do_TD(self, tx: PDFObject, ty: PDFObject) -> None:
        """Move to the start of the next line.

        offset from the start of the current line by (tx , ty). As a side effect, this
        operator sets the leading parameter in the text state.

        (PDF 1.7 Table 108) This operator shall have the same effect as this code:
            −ty TL
            tx ty Td
        """
        self.do_TL(-num_value(ty))
        self.do_Td(tx, ty)

    def do_Tm(
        self,
        a: PDFObject,
        b: PDFObject,
        c: PDFObject,
        d: PDFObject,
        e: PDFObject,
        f: PDFObject,
    ) -> None:
        """Set text matrix and text line matrix"""
        self.textstate.line_matrix = (
            num_value(a),
            num_value(b),
            num_value(c),
            num_value(d),
            num_value(e),
            num_value(f),
        )
        self.textstate.glyph_offset = (0, 0)

    def do_T_a(self) -> None:
        """Move to start of next text line"""
        (a, b, c, d, e, f) = self.textstate.line_matrix
        self.textstate.line_matrix = (
            a,
            b,
            c,
            d,
            -self.graphicstate.leading * c + e,
            -self.graphicstate.leading * d + f,
        )
        self.textstate.glyph_offset = (0, 0)

    def do_BI(self) -> None:
        """Begin inline image object"""

    def do_ID(self) -> None:
        """Begin inline image data"""

    def get_property(self, prop: PSLiteral) -> Union[Dict, None]:
        if "Properties" in self.resources:
            props = dict_value(self.resources["Properties"])
            return dict_value(props.get(prop.name))
        return None

    def do_MP(self, tag: PDFObject) -> Union[ContentObject, None]:
        """Define marked-content point"""
        return self.do_DP(tag, None)

    def do_DP(
        self, tag: PDFObject, props: PDFObject = None
    ) -> Union[ContentObject, None]:
        """Define marked-content point with property list"""
        # See above
        if isinstance(props, PSLiteral):
            props = self.get_property(props)
        rprops = {} if props is None else dict_value(props)
        return TagObject(
            _pageref=self.page.pageref,
            _parentkey=self.parent_key,
            ctm=self.ctm,
            mcstack=self.mcstack,
            gstate=self.graphicstate,
            _mcs=MarkedContent(mcid=None, tag=literal_name(tag), props=rprops),
        )

    def begin_tag(self, tag: PDFObject, props: Dict[str, PDFObject]) -> None:
        """Handle beginning of tag, setting current MCID if any."""
        assert isinstance(tag, PSLiteral)
        if "MCID" in props:
            mcid = int_value(props["MCID"])
        else:
            mcid = None
        self.mcstack = (
            *self.mcstack,
            MarkedContent(mcid=mcid, tag=tag.name, props=props),
        )

    def do_BMC(self, tag: PDFObject) -> None:
        """Begin marked-content sequence"""
        self.begin_tag(tag, {})

    def do_BDC(self, tag: PDFObject, props: PDFObject) -> None:
        """Begin marked-content sequence with property list"""
        # PDF 1.7 sec 14.6.2: If any of the values are indirect
        # references to objects outside the content stream, the
        # property list dictionary shall be defined as a named
        # resource in the Properties subdictionary of the current
        # resource dictionary (see 7.8.3, “Resource Dictionaries”) and
        # referenced by name as the properties operand of the DP or
        # BDC operat

        if not isinstance(tag, PSLiteral):
            log.warning("Tag %r is not a name object, ignoring", tag)
            return None
        if isinstance(props, PSLiteral):
            propdict = self.get_property(props)
            if propdict is None:
                log.warning("Missing property list in tag %r: %r", tag, props)
                propdict = {}
        else:
            propdict = dict_value(props)
        self.begin_tag(tag, propdict)

    def do_EMC(self) -> None:
        """End marked-content sequence"""
        if self.mcstack:
            self.mcstack = self.mcstack[:-1]


# This should be in playa.fontprogram, but circular imports...
class Type3Interpreter(LazyInterpreter):
    """Interpret Type3 font programs."""

    width: float = 1000
    bbox: Rect = BBOX_NONE

    def do_d0(self, wx: float, wy: float) -> None:
        """Simple Type3 font metrics operator."""
        self.width = wx

    def do_d1(
        self, wx: float, wy: float, llx: float, lly: float, urx: float, ury: float
    ) -> None:
        """More complete Type3 font metrics operator that ignores colours."""
        self.width = wx
        self.ignore_colours = True
        self.bbox = (llx, lly, urx, ury)
