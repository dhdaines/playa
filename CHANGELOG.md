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
