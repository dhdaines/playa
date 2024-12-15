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
