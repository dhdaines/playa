## PLAYA 0.2.x
- [ ] Add `matrix` to `GlyphObject` as it is often needed
- [ ] Fix ToUnicode CMaps for CID fonts (file bug against pdfminer)
- [ ] Optimize text extraction
- [ ] Support slices and lists in `PageList.__getitem__`
- [ ] Remove remaining dangerous `cast` usage

## PLAYA 0.3.x
- [ ] remove `LayoutDict`
- [ ] add optimized serialization/deserialization
- [ ] deprecate `resolve1` and `resolve_all`

## PLAYA 1.0
- [ ] make `ObjRef` into a proxy object
- [ ] make the structure tree lazy
- [ ] support ExtGState (submit PR to pdfminer)
- [ ] better API for document outline, destinations, links, etc
- [ ] test coverage and more test coverage
- [ ] support matching ActualText to text objects when possible
  - [ ] if the text object is a single MCS (LibreOffice will do this)
