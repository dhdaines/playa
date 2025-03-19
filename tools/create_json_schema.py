"""(Re-)create the JSON schemas for playa.data classes."""

import json
from pathlib import Path

from pydantic import TypeAdapter
from typing_extensions import is_typeddict

import playa.data

SCHEMA = Path(playa.data.__file__).parent / "schema"


def main():
    SCHEMA.mkdir(parents=True, exist_ok=True)
    for name, obj in vars(playa.data).items():
        if is_typeddict(obj):
            adapter = TypeAdapter(obj)
            with open(SCHEMA / f"{name}.json", "wt") as outfh:
                json.dump(adapter.json_schema(), outfh, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
