## PLAYA 0.9.0: Unreleased

- Refactor and add convenience methods to text objects
- Insert blank pages for missing object references in page tree
- Clean up type annotations (breaking change: PDFObject can no longer
  be `str`, as the parser will never create this)

## PLAYA 0.8.1: 2025-12-22

- Correct subtle issues with mypyc-compiled pdfminer.six code

## PLAYA 0.8.0: 2025-12-17

- Optionally accelerate image decoding with mypyc
- Correct explicit string positioning in vertical text
- Restore caching in text decoding under Python 3.8
- Bring back pdfminer.six layout analysis algorithm
- Optionally accelerate pdfminer.six compatibility with mypyc

## PLAYA 0.7.2: 2025-11-09

- Fix path traversal vulnerability in cmap code
- Fix insecure deserialization in cmap code
- Fix wildly inefficient deflate code (possible DoS)

## PLAYA 0.7.1: 2025-08-16

- Tolerate non-integer values for page rotation
- Restore Python 3.8 compatibility (oops!)
- Restore robustness to broken structure elements
- Correct handling of byte alignment in CCITT decoding fixing an endless loop
- Be more robust when extracting images

## PLAYA 0.7.0: 2025-08-04

- Remove long-deprecated functions
- Add and document `finalize` method on ContentObjects
- Make `PageList` work more or less like a `Sequence`
- Support iteration over `playa.structure.ContentItem`
- Greatly increase test coverage
- Greatly optimize marked content section access
- Add `find` and `find_all` methods to `page.structure`
- Extract CMYK images (except JPEG/JPEG2000) as TIFF

## PLAYA 0.6.6: 2025-08-01

- Correct and test rotation behaviour which was quite incorrect, and
  also allow users to update rotation and space on an existing page
- Fix a very long-standing and stupid bug in `normalize_rect`
- Never crash on invalid UTF-16 (we mean it this time)

## PLAYA 0.6.5: 2025-08-01
- Fix terrible error in xref detection and parsing
- Support 1D and mixed CCITT fax decoding

## PLAYA 0.6.4: 2025-07-26

- Fix terrible error in fallback indirect object parsing
- Simplify and robustify xref detection
- Stop stream parsing on endobj as well as endstream

## PLAYA 0.6.3: 2025-07-26

- Correct and slightly optimize PNG predictor
- Accept all standard number syntaxes (oops)
- Fail fast on incorrect or damaged xref pointers
- Accept fontsize of 0
- Don't throw an exception on malformed text strings
- Extract images with any colorspace
- Correct `ASCIIHexDecode` for all odd-length strings (not just some)
- Remove sketchy characters from image and font filenames
- Track streamid in `ObjectParser` (this will become useful with time)
- Cache inline images in `ObjectParser`

## PLAYA 0.6.2: 2025-07-21

- Look in ICC profile for number of components if missing
- Accept `None` in `StructParents` (this is legal)
- Use stream object ID, not string XObject ID, to fight evil
- Clarify color space ID vs. name and remember to dereference it
- Add `--fonts` to CLI to get fonts used in a document or its pages
- Correct handling of indexed images with 1/2/4 bits per component
- Add `cid2gid` for CFF fonts

## PLAYA 0.6.1: 2025-06-17

- Fix regression on subset fonts with zero Ascent and Descent
- Add method for PNM extraction to streams
- Extract masks, softmasks, and alternates (if they exist, which they
  never seem to) along with images in CLI
- Correctly extract JBIG2 images
- Fix (again) stream parsing to avoid extraneous EOLs
- Extract images with Indexed color space to PNM

## PLAYA 0.6.0: 2025-06-13

- Add `structure` to `Page` to access structure elements indexed by
  marked content IDs (convenience wrapper over the parent tree)
- Add `structure` to `XObjectObject` for the same reason
- Add `parent` to all `ContentObject` to access parent structure
  element (if any) via the parent tree
- Descend into Form XObjects in `Page.xobjects`
- Improve text extraction for rotated pages
- Improve text extraction for tagged PDFs
- Correct displacement and bbox for Type3 fonts with non-diagonal
  `FontMatrix`
- Add `displacement` property to `TextObject`
- Add functioning `__iter__` to `GlyphObject` in the case of
  Type3 fonts, which works like `XObjectObject`
- Extract non-JPEG images as PNM
- BREAKING: Fix `__len__` on `PathObject` which incorrectly returned
  non-zero even though iteration is not possible
- BREAKING: Remove misleading `char_width`, `get_descent`, and
  `get_ascent` methods and `hscale` and `vscale` properties from font
  objects
- BREAKING: Do not guess `basename` for Type3 fonts (generally it
  isn't different from `fontname` for other subset fonts)
- BREAKING: `Element.contents` contains both `structure.ContentItem`
  and `structure.ContentObject`


## PLAYA 0.5.1: 2025-05-26

- Update documentation for API changes
- Implement graphics state parameter dictionaries
- Correctly implement `name2unicode`
- Handle Type3 fonts with useless Encodings and no ToUnicode
- Correct `fontname` and guess `basename` for Type3 fonts
- Add missing `bbox` property to annotations
- Correct parent tree access (oops!)
- Correctly handle bogus line endings in xref tables
- Avoid `KeyError` when `RoleMap` does not exist

## PLAYA 0.5.0: 2025-05-14

- Remove use of `object` in type annotations
- Add support for role map and standard structure types
- Refactor page.py as it was getting really unwieldy
- Add missing `ctm` to content objects in metadata API
- Somewhat improve untagged text extraction where the CTM is exotic
- Correct character and word spacing to apply after all glyphs
- Correct vertical writing to fully support glyph-specific position
  vectors, even totally absurd ones
- Correct horizontal scaling to apply to vertical writing, including
  the position vector
- Add `bbox` and `contents` to structure elements
- Add `origin` and `displacement` to glyphs
- Add `size` to glyphs and texts to get effective font size (still not
  entirely accurate when there is rotation or skewing)
- Support PDF 2.0 `Length` attribute on inline images
- Add `font` property to documents and pages
- BREAKING: `find` and `find_all` in structure search by standard
  structure types (roles)
- BREAKING: `parent_tree` moved to `playa.structure.Tree`
- BREAKING: `Point`, `Rect`, `Matrix` and `PDFObject` moved to
  `playa.pdftypes`
- BREAKING: `PathObject` no longer contains "subpaths", it is safe to
  recursively descend it now
- BREAKING: Content objects moved to `playa.content` and interpreter
  to `playa.interp`
- BREAKING: Text state no longer exists in the public API, text
  objects have immutable line matrix and glyph offset now, and
  everything else is in the graphic state
- BREAKING: `text_space_` properties are removed since what they
  returned was not actually text space (and maybe not useful either)
- BREAKING: `glyph_offset` is removed from glyphs and made private in
  text objects, as it is not in a well defined space.
- BREAKING: Glyph `bbox` now has a precise definition, which isn't
  exactly the glyph bounding box but is a lot closer.  This means
  notably that adjacent glyphs may overlap or may not touch, which is
  why you should **never** use the `bbox` to detect word boundaries.
  Use `origin` and `displacement` instead, please!
- BREAKING: `cid2unicode` attribute of fonts is removed as it doesn't
  make any sense for Type3 or CID fonts.

## PLAYA 0.4.3: 2025-05-09

- Correct ascent, descent, and glyph boxes for Type3 fonts
- XObjects inherit graphics state from surrounding content

## PLAYA 0.4.2: 2025-04-26

- Correct `fontsize` and `scaling` in text state
- Correct `ValueError` on incorrect stream lengths for ASCII85 data
- Correct implicit font encodings for Type1 fonts
- More fine-grained error handling in font initialization
- Correct infinite recursion in malicious Form XObjects
- Correct and improve `asobj` on structure trees and annotations
- Correctly remove padding on AES-encrypted strings
- Tolerate all sorts of illegal structure trees
- Allow accessing annotations and XObjects from structure tree

## PLAYA 0.4.1: 2025-03-20

- Correct outlines in CLI
- Accept UTF-16LE in strings with BOM
- Speed up fallback xrefs in pathological PDFs
- Detect two PDFs in a trenchcoat

## PLAYA 0.4.0: 2025-03-19

- Cover (nearly) the entire pdf.js testsuite including downloads
- Refactor CLI output into structured metadata/content API
- Provide preliminary JSON schemas for metadata and content
- Remove deprecated APIs
- Extract images in CLI, sort of

## PLAYA 0.3.2: 2025-03-18

- Decrypt objects in `Document.objects` iterator
- Remove disastrous side-effects from `TextObject.bbox`
- Remove frustrating side-effects from `TextObject.__iter__`
- Speed up `TextObject.bbox` and add `text_space_bbox` properties

## PLAYA 0.3.1: 2025-02-28

- Correct CTM in children of XObjectObject
- Add `have_labels` attribute to PageList

## PLAYA 0.3.0: 2025-02-20

- API for text extraction
- Extract text from XObjects with `playa --text`
- Remove deprecated `LayoutDict` API and simplify code
- Deprecate `annots` API and add friendly `annotations`
- Elevate `resolve1` and `resolve_all` to top-level exports
- Deprecate `structtree` and add lazy `structure` API
- Extract logical structure in CLI
- Speed up iteration over particular object types
- Deprecate `outlines` API and add tree-structured `outline`
- Deprecate `dests` API and add friendly `destinations`

## PLAYA 0.2.10: 2025-02-18

- Fix serious bug in rare ' and " text operators
- Fix robustness issues in structtree API

## PLAYA 0.2.9: 2025-02-07

- Support the all-important empty name object
- Break the CLI again (ZeroVer YOLO) to better support page ranges
- Add necessary .doc property to page list
- Correct type annotations for page list
- Extract text objects with `-x` instead of just texts
- Extract text objects and streams in parallel in CLI
- Support arbitrary iterables in `PageList.__getitem__`

## PLAYA 0.2.8: 2025-01-22

- Accept `None` for `max_workers`
- Update documentation with a meme for the younger generation
- Allow returning indirect object references from worker processes

## PLAYA 0.2.7: 2025-01-07

- Remove excessive debug logging
- Add rendering matrix to `GlyphObject`
- Fix ToUnicode CMaps for CID fonts
- Optimize text extraction
- Support slices and lists in `PageList.__getitem__`
- Remove remaining dangerous `cast` usage
- Make text extraction less Lazy so that we get graphics state correct
  (slightly breaking change)
- Correct the handling of marked content sections\
- Be robust to junk before the header
- Deliberately break the CLI (ZeroVer FTW YOLO ROTFL)

## PLAYA 0.2.6: 2024-12-30

- Correct some type annotations (these were not really bugs)
- Handle more CMap and ToUnicode corner cases
- Add parallel operations
- Deprecate "eager" API
- Correct some problems on Windows/MacOS

## PLAYA 0.2.5: 2024-12-15

- Fix various bugs in the lazy API
  - Add specialized `__len__` methods to ContentObject classes
  - Clarify iteration over ContentObject
- Fix installation of playa-pdf[crypto]
- Fix attribute classes in structure tree elements
- Deprecate "user" device space to avoid confusion with user space
- Parse arbitrary Encoding CMaps
- Update `pdfplumber` support
- Add parser for object streams and iterator over all indirect objects
  in a document

## PLAYA 0.2.4: 2024-12-02

- fix more embarrassing bugs largely regarding the creation of empty
  ContentObjects
- these are not actually all fixed because (surprise!) sometimes we
  neglect to map the characters in fonts correctly
- oh and also lots and lots of robustness fixes thanks to the pdf.js
  testsuite of pdf horrors

## PLAYA 0.2.3: 2024-11-28:

- release early and often
- fix some embarrassing bugs, again:
  - CMap parser did not recognize bfrange correctly (regression)
  - corner cases of inline images caused endless woe
  - documentation said document.structtree exists but nope it didn't

## PLAYA 0.2.2: 2024-11-27

- make everything quite a lot faster (25-35% faster than pdfminer now)
- fix some more pdfminer.six bugs and verify others already fixed
- really make sure not to return text objects with no text

## PLAYA 0.2.1: 2024-11-26

- fix serious bug on malformed stream_length
- report actual bounding box for rotated glyphs
  - eager API is no longer faster than pdfminer :( but it is more correct

## PLAYA 0.2: 2024-11-25

- expose form XObjects on Page to allow getting only their contents
- expose form XObject IDs in LayoutDict
- make TextState conform to PDF spec (leading and line matrix) and document it
- expose more of TextState in LayoutDict (render mode in particular - OCRmyPDF)
- do not try to map characters with no ToUnicode and no Encoding (OCRmyPDF)
- properly support Pattern color space (uncolored tiling patterns) the
      way pdfplumber expects it to work
- support marked content points as ContentObjects
- document ContentObjects
- make a proper schema for LayoutDict, document it, and communicate it to Polars
- separate color values and patterns in LayoutDict
