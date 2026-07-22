# mc-artifact-parser

`schema_parser` is a small, self-contained Python package that turns loosely
structured source artifacts into reviewed column mappings and per-table schema
markdown. It has **no third-party dependencies** (standard library only), so the
`schema_parser/` folder can be copied as-is into a customer environment.

## Workflow

The package drives a three-command, human-in-the-loop workflow:

1. **`propose-mapping`** — read a source, group its tables by header signature,
   and emit a crosswalk (`extracted column → target column`) for human review.
2. **`create-schema`** — apply the reviewed mapping to the source and write one
   `{table}_schema.md` per table.
3. **`extract-relationships`** — (SVG only) read connector arrows between tables
   and emit a relationships table plus a Mermaid `erDiagram`.

Every stage downstream of extraction is source-agnostic. Extraction is handled by
a per-source subpackage (`schema_parser/sources/`) where a registry tries each
`SourceReader` in turn. Adding a new input type means writing one `SourceReader`
and registering it — nothing else changes.

## Supported sources

| Reader | Extensions | Notes |
|---|---|---|
| `DocxReader` | `.docx` | Default fallback; heading-styled paragraph before a table becomes its name. |
| `SvgReader` | `.svg`, `.xml` | Class/layout-driven table extraction; also encodes table relationships as arrows. |
| `TextSchemaReader` | `.txt`, `.md`, `.markdown` | Markdown pipe tables parsed literally; free-text/bullet column lines coerced onto the target columns. |

Anything unrecognized falls through to the DOCX reader, which gives a clear
"not a valid ZIP-based DOCX file" error.

## Install / distribution

The package is standard-library only, so it can be delivered two ways:

- **Copy the folder** — drop `schema_parser/` onto the target (Python 3.10+) and
  run `python -m schema_parser ...` from the parent directory. No pip, no network.
- **Build a wheel** — from the repo root run `python -m build`, then
  `pip install dist/schema_parser-*.whl` on the target. This installs the package
  and a `schema-parser` console script.

See [schema_parser/DISTRIBUTION.md](schema_parser/DISTRIBUTION.md) for the full
guide.

## Usage

```bash
# DOCX source
python -m schema_parser propose-mapping ./sample.docx --out ./mapping.md
python -m schema_parser create-schema ./sample.docx ./mapping.md --out-dir ./schema

# SVG source (same two commands; .svg or .xml)
python -m schema_parser propose-mapping ./sample.svg --out ./svg-mapping.md
python -m schema_parser create-schema ./sample.svg ./svg-mapping.md --out-dir ./schema

# Text / Markdown source
python -m schema_parser propose-mapping ./notes.md --out ./md-mapping.md
python -m schema_parser create-schema ./notes.md ./md-mapping.md --out-dir ./schema

# Extract table relationships (arrows) from an SVG diagram
python -m schema_parser extract-relationships ./sample.svg --out ./relationships.md
```

The library API mirrors the CLI:

```python
from schema_parser import (
    propose_mapping,
    render_mapping_markdown,
    parse_mapping_markdown,
    write_schema_files,
    read_relationships,
    render_relationships_markdown,
)

column_sets = propose_mapping("/path/to/sample.docx")
mapping_md = render_mapping_markdown(column_sets)

# ...after human review of mapping_md...
written = write_schema_files("/path/to/sample.docx", parse_mapping_markdown(mapping_md), "./schema")

relationships = read_relationships("/path/to/sample.svg")
print(render_relationships_markdown(relationships))
```

## Target columns

Every generated schema is projected onto a fixed set of target columns:

```
Column, Type, Nullable, Primary Key, Foreign Key, Details, Description, Source
```

## Tests

```powershell
.\.venv\Scripts\python -m unittest discover -s tests
```

## Maintenance note

When changing the `schema_parser` workflow or its CLI behavior, update
[schema_parser/DISTRIBUTION.md](schema_parser/DISTRIBUTION.md) so the distribution
guide stays accurate. Bump `__version__` in
[schema_parser/__init__.py](schema_parser/__init__.py) before building a new wheel.
