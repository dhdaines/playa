# **P**LAYA ain't a **LAY**out **A**nalyzer 🏖️

## About

This is not an experimental fork of
[pdfminer.six](https://github.com/pdfminer/pdfminer.six).  Well, it's
kind of an experimental fork of pdfminer.six.  The idea is to extract
just the part of pdfminer.six that gets used by
[pdfplumber](https://github.com/jsvine/pdfplumber), namely the
low-level PDF access, optimize it for speed, see if it can be
reimplemented using other libraries such as pypdf or pikepdf,
benchmark it against those libraries, and improve its API.

There are already too many PDF libraries, unfortunately none of which
does everything that everybody wants it to do, and we probably don't
need another one. It is not recommended that you use this library for
anything at all, but if you were going to use it for something, it
would be specifically one of these things and nothing else:

1. Accessing the document catalog, page tree, structure tree, content
   streams, cross-reference table, XObjects, and other low-level PDF
   metadata.
2. Obtaining the absolute position and attributes of every character,
   line, path, and image in every page of a PDF document.
   
Notably this does *not* include the largely undocumented heuristic
"layout analysis" done by pdfminer.six, because it is quite difficult
to understand due to a Java-damaged API based on deeply nested class
hierarchies, and because layout analysis is best done
probabilistically/visually.  Also, pdfplumber does its own, much
nicer, layout analysis.  Also, if you just want to extract text from a
PDF, there are a lot of better and faster tools and libraries out
there, see [benchmarks]() for a summary (TL;DR pypdfium2 is probably
what you want, but pdfplumber does a nice job of converting PDF to
ASCII art).

## Usage

Do you want to get stuff out of a PDF?  You have come to the right
place!  Let's open up a PDF and see what's in it:

```python
pdf = playa.open("my_awesome_document.pdf")
raw_byte_stream = pdf.buffer
a_bunch_of_tokens = list(pdf.tokens)
a_bunch_of_indirect_objects = list(pdf)
```

The raw PDF tokens and objects are probably not terribly useful to
you, but you might find them interesting.  Note that these are
"indirect objects" where the actual object is accompanied by an object
number and generation number:

```python
for objid, genno, obj in pdf:
    ...
# or also
for obj in pdf:
    obj.objid, obj.genno, obj.obj
```

Also, these will only be the top-level objects and not those found
inside object streams (the streams are themselves indirect objects).
You can access all objects directly by indexing the PDF document:

```python
a_particular_object = pdf[42]
```

It probably has some pages.  How many?  What are their numbers/labels?
(they could be things like "xviii", 'a", or "42", for instance)

```python
npages = len(pdf.pages)
page_numbers = [page.label for page in pdf.pages]
```

What's in the table of contents?

```python
for entry in pdf.outlines:
    ...
```

If you are lucky it has a "logical structure tree".  The elements here
might even be referenced from the table of contents!  (or, they might
not... with PDF you never know)

```python
structure = pdf.structtree
for element in structure:
   for child in element:
       ...
```

Now perhaps we want to look at a specific page.  Okay!
```python
page = pdf.pages[0]        # they are numbered from 0
page = pdf.pages["xviii"]  # but you can get them by label (a string)
page = pdf.pages["42"]  # or "logical" page number (also a string)
a_few_content_streams = list(page.contents) # FIXME
raw_bytes = b"".join(stream.buffer for stream in page.contents) # FIXME
```

## Accessing content

What are these "contents" of which you speak, which were surely
created by a Content Creator?  Well, you can look at the stream of
tokens or mysterious PDF objects:

```python
for token in page.tokens:
    ...
for object in page:  # PDF objects. NOT graphics/text objects!
    ...
```

But that isn't very useful, so you can also access actual textual and
graphical objects (if you wanted to, for instance, do layout
analysis).

```python
for item in page.objects:
    ...
```

Because it is quite inefficient to expand, calculate, and copy every
possible piece of information, PLAYA gives you some options here.
Wherever possible this information can be computed lazily, but this
involves some more work on the user's part.

### Dictionary-based API

If, on the other hand, **you** are lazy, then you can just use
`page.layout`, which will flatten everything for you into a friendly
dictionary representation (but it is a
[`TypedDict`](https://typing.readthedocs.io/en/latest/spec/typeddict.html#typeddict))
which, um, looks a lot like what `pdfplumber` gives you, except in PDF
device coordinate space, meaning `(0, 0)` is the bottom-left and not
the top-left of the page:

```python
for obj in page.layout:
    print("it is a {obj['object_type']} at ({obj['top']}", {obj['left']}))
    print("    the color is {obj['stroking_color']}")
    print("    the text is {obj['text']}")
    print("    it is in MCS {obj['mcid']} which is a {obj['tag']}")
```

This is for instance quite useful for doing "Artificial Intelligence",
or if you like wasting time and energy for no good reason, but I
repeat myself.

If you have more specific needs or want better performance, then read on.

### Lazy object API

Fundamentally you may just want to know *what* is *where* on the page,
and PLAYA has you covered there (note that the bbox is normalized, and
in PDF device space):

```python
for item in page.objects:
    print(f"{item.object_type} at {item.bbox}")
    print(f"{item.object_type} bottom left is {item.left, item.bottom}")
    print(f"{item.object_type} top right is {item.right, item.top}")
```

Another important piece of information (which `pdfminer.six` does not
really handle) is the relationship between layout and logical
structure, done using *marked content sections*:

```python
for item in page.layout:
    print(f"{item.object_type} is in marked content section {item.mcs.mcid}")
    print(f"    which is tag {item.mcs.tag.name}")
    print(f"    with attributes {item.mcs.tag.attrs}")
```

The `mcid` here is the same one referenced in elements of the
structure tree as shown above (but remember that `tag` has nothing to
do with the structure tree element, because Reasons).

You may also wish to know what color an item is, and other aspects of
what PDF refers to as the *graphics state*, which is accessible
through `item.gstate`.  This is a mutable object, and since there are
quite a few parameters in the graphics state, PLAYA does not create a
copy of it for every item in the layout - you are responsible for
saving them yourself if you should so desire.  This is not
particularly onerous, because the parameters themselves are immutable:

```python
for item in page.layout:
    print(f"{item.object_type} at {item.bbox} is:")
    print(f"    {item.gstate.scolor} stroking")
    print(f"    {item.gstate.ncolor} non-stroking")
    my_stuff = (item.bbox, item.gstate.scolor, item.gstate.ncolor)
    other_stuff.append(my_stuff)  # it's safe there
```

For compatbility with `pdfplumber`, PLAYA, even though it is not a
layout analyzer, can do some basic interpretation of paths.  Again,
this is lazy.  If you don't care about them, you just get items with
`object_type` of `"path"`, which you can ignore.  PLAYA won't even
compute the bounding box (which isn't all that slow, but still).  If
you *do* care, then you have some options.  You can look at the actual
path segments in user space (fast):

```python
for seg in path.raw_segments:
   print(f"segment: {seg}")
```

Or in device space (not so fast):

```python
for seg in path.segments:
   print(f"segment: {seg}")
```

This API doesn't try to interpret paths for you.  You only get
`PathSegment`s.  But for convenience you can get them grouped by
subpaths as created using the `m` or `re` operators:

```python
for subpath in path:
   for seg in subpath.segments:
       print(f"segment: {seg}")
```

Since most PDFs consist primarily of text, obviously you may wish to
know something about the actual text (or the `ActualText`, which you
can sometimes find in `item.mcs.tag.attrs["ActualText"]`) of layout
items.  This is more difficult than it looks, as fundamentally PDF
just positions arbitrarily numbered glyphs on a page, and the vast
majority of PDFs embed their own fonts, using *subsetting* to include
only the glyphs actually used.

Whereas `pdfminer.six` would break down text objects into their
individual glyphs (which might or might not correspond to characters),
this is not always what you want, and moreover it is computationally
quite expensive.  It also complicates the use of the `ActualText`
attribute for text extraction.  So PLAYA, by default, does not do
this.  If you don't need to know the actual bounding box of a text
object, then don't access `item.bbox` and it won't be computed.  If
you don't need to know the position of each glyph but simply want the
Unicode characters, then just look at `item.chars` (this will use the
`ActualText` attribute if it exists).

Of course a lot of PDFs, especially ones produced by OCR, won't give
you anything very meaningful in that case, so you will want to
actually look at the glyphs.  This becomes a matter of iterating over
the item, giving you, well, more items, which are the individual
glyphs:

```python
for glyph in item:
    ...
```

By default PLAYA, following the PDF specification, considers the
grouping of glyphs into strings irrelevant by default, but if you
really need to know, you can iterate over these, and *then* over the
individual glyphs:

```python
for string in item.strings:
    for glyph in string:
        ...
```

PDF has the concept of a *text state* which determines some aspects of
how text is rendered.  You can obviously access this though
`glyph.textstate` - note that the text state, like the graphics state,
is mutable, so you will have to copy it or save individual parameters
that you might care about.

PLAYA doesn't guarantee that these items come at you in anything other
than the order they occur in the file (but it does guarantee that).

For everything else, there's pdfplumber, pdfium2, pikepdf, pypdf,
borb, pydyf, etc, etc, etc.

## Acknowledgement

This repository obviously includes code from `pdfminer.six`.  Original
license text is included in [LICENSE](/LICENSE.pdfminer).  The license
itself has not changed!
