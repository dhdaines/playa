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
