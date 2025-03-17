# Data API

## Overview

The `playa.data` module contains schemas (as `TypedDict`) and extractors
for metadata and content from various PLAYA objects, as well as a
single-dispatch function `playa.data.asobj` to extract said metadata
from any object.  This is an entirely non-lazy API.  It is provided
here because the PLAYA CLI uses it, and to discourage users of the
library from reimplementing it themselves.

Many PLAYA objects are already `dataclass` or `NamedTuple` so they
have a function or method to convert them to `dict`, but for a variety
of reasons you shouldn't actually use this function.  See [here for
`dataclasses.asdict` and its many
pitfalls](https://stackoverflow.com/questions/52229521/why-is-dataclasses-asdictobj-10x-slower-than-obj-dict).

The distinction between "metadata" and "content" is admittedly not
very clear for PDF.  Metadata, represented by the schemas in
`playa.data.metadata`, is:

- attributes of pages, content streams, etc (uncontroversial)
- outline and logical structure nodes and their properties (but not
  their contents)
- annotations and their properties
- articles and threads (TODO: PLAYA doesn't support these yet, I need
  to find some PDFs that have them)

Content, represented by the schemas in `playa.data.content`, is:

- data in content streams (except for object streams, obviously)
- anything that is a `ContentObject` (so, paths, images, glyphs)
- marked content sections (as these cannot be created without actually
  parsing the content streams)

Note that the CLI doesn't exactly break things down along those lines.
In particular, the default metadata output doesn't include outlines,
logical structure trees, or annotations.  In general, if you have
performance concerns you are always better off using the lazy API,
then calling `asobj` on specific objects as needed, as extracting all
the metadata (not even the content) may be fairly slow.

## Data and Metadata Objects

All of these objects are accessible through the `playa.data` module.

::: playa.data
    options:
      show_root_heading: false

