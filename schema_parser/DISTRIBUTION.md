# Distributing `schema_parser`

`schema_parser` is standard-library only (no third-party runtime dependencies),
so it can be delivered to a customer environment two ways. Pick whichever fits
the destination's constraints.

| Method | Best when | Result |
|---|---|---|
| **Copy the folder** | Air-gapped boxes, no pip/network, "just drop it in" | Run with `python -m schema_parser ...` from the parent dir |
| **Build a wheel** | Normal Python env, want a real install + `schema-parser` command | `pip install schema_parser-*.whl` installs the package and console script |

Both ship the same code. Nothing else is required — no `pip install` of
dependencies, because there are none.

---

## Method 1 — Copy the folder

Copy the entire `schema_parser/` directory into the target machine (anywhere on
disk). From the directory that *contains* it, run the module form:

```bash
python -m schema_parser propose-mapping ./sample.docx --out ./mapping.md
python -m schema_parser create-schema ./sample.docx ./mapping.md --out-dir ./schema
python -m schema_parser extract-relationships ./sample.svg --out ./relationships.md
```

Requirements: Python 3.10+ on the target (the code uses `X | Y` type unions).
No virtual environment, no network, no build step.

To use it as a library from your own script, put the parent of `schema_parser/`
on `sys.path` (or run your script from that directory) and `import schema_parser`.

---

## Method 2 — Build and install a wheel

From the repository root (where `pyproject.toml` lives):

```powershell
# one-time: install the build frontend (build tooling only, not a runtime dep)
python -m pip install --upgrade build

# produces dist/schema_parser-<version>-py3-none-any.whl and a .tar.gz sdist
python -m build
```

Ship the `.whl` (or the sdist) to the target and install it:

```powershell
pip install schema_parser-0.1.0-py3-none-any.whl
```

That installs the importable package **and** a `schema-parser` console script:

```bash
schema-parser propose-mapping ./sample.docx --out ./mapping.md
schema-parser create-schema ./sample.docx ./mapping.md --out-dir ./schema
schema-parser extract-relationships ./sample.svg --out ./relationships.md

# equivalent module form still works after install:
python -m schema_parser --help
```

The version is single-sourced from `schema_parser/__init__.py` (`__version__`);
bump it there and rebuild to cut a new release.

---

## What the tool does

A three-command, human-in-the-loop workflow:

1. `propose-mapping <docx|svg|text> --out <mapping.md>` — read a source, group its
   tables by header signature, and emit a crosswalk (`extracted column → target
   column`) for human review.
2. `create-schema <docx|svg|text> <mapping.md> --out-dir <dir>` — apply the
   reviewed mapping to the source and write one `{table}_schema.md` per table.
3. `extract-relationships <svg> --out <relationships.md>` — (SVG only) read
   connector arrows between tables and emit a relationships table plus a Mermaid
   `erDiagram`.

Every stage downstream of extraction is source-agnostic. Extraction lives in the
`schema_parser/sources/` subpackage: a registry tries each `SourceReader` in turn
and falls back to the DOCX reader for unrecognized files. `SvgReader` claims
`.svg`/`.xml`; `TextSchemaReader` claims `.txt`/`.md`/`.markdown` (Markdown pipe
tables parsed literally, free-text column lines coerced onto the target columns);
everything else is read as DOCX. Adding a new input type means writing one
`SourceReader` and registering it.

Invalid input is rejected with a clear message: a non-ZIP or non-DOCX file fails
with an explicit "not a valid ZIP-based DOCX file" error, and a malformed `.svg`
fails with an explicit SVG parse/root error rather than a low-level exception.

## Output format

`propose-mapping` emits one section per distinct column set with a crosswalk and
table membership list:

```markdown
## Column Set 1

- Tables: Customer

| Extracted Column | Target Column |
|---|---|
| Field | Column |
| Type | Type |
| Required | Nullable |
| Purpose | Description |
|  | Primary Key |
|  | Foreign Key |
|  | Details |
|  | Source |
```

`create-schema` reads the source plus the reviewed mapping and writes one
`{table}_schema.md` per table, each projected onto the fixed target columns and
ending with visible rider stubs:

```markdown
## Custom Riders

_None defined._

## Provenance / Audit Columns

_None defined._
```

Every generated schema is projected onto the fixed `TARGET_COLUMNS`: `Column`,
`Type`, `Nullable`, `Primary Key`, `Foreign Key`, `Details`, `Description`,
`Source`.
