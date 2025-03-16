"""(Re-)create the JSON schemas for playa.data classes."""

import json

from pydantic import TypeAdapter

import playa.data


def main():
    doc_adapter = TypeAdapter(playa.data.Document)
    print(json.dumps(doc_adapter.json_schema(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
