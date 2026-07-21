# docx_schema Operator Runbook

A step-by-step guide for running the minimal DOCX-to-schema workflow. No
programming knowledge required — just a terminal and a `.docx` file.

## What this does

Two commands turn a Word document into per-table schema files:

1. `propose-mapping` — reads a `.docx` and writes a **reviewer-editable**
   mapping markdown file.
2. `create-schema` — reads the (edited) mapping markdown and writes one
   `{table}_schema.md` file per table.

You review and edit the mapping in between. Nothing is written to the source
document.

## Prerequisites

- Python 3.13.x on PATH (validated on 3.13.11 and 3.13.14; `python --version` should report `Python 3.13.x`).
- Run all commands from the repository root:
  `C:\Users\lferdinand\microsoft_source\mc-artifact-parser`.
- No third-party packages are needed (standard library only).

---

## Step 1 — Propose a mapping from the .docx

```powershell
python -m docx_schema propose-mapping .\tables.docx
```

Shortcuts that also work:

```powershell
# Slash-prefixed command and @-prefixed file reference are both accepted
python -m docx_schema /propose-mapping "@tables.docx"

# Choose the output path explicitly
python -m docx_schema propose-mapping .\tables.docx --out .\tables-mapping.md
```

Expected output:

```
Wrote proposed mapping: <path>\tables-mapping.md
Detected N table(s): Customer, Order, ...
Review and edit the mapping, then run: create-schema tables-mapping.md
```

By default the file is written to `.\<docx-name>-mapping.md` in the current
folder.

**Pass criteria:** the command exits without error, prints the number of
detected tables, and the mapping file exists.

---

## Step 2 — Review and edit the mapping

Open the generated `*-mapping.md`. Tables that share the same set of columns are
grouped into one column set (`## Columns` for a single set, or `## Column Set N`
when tables diverge). The `- Tables:` line lists which tables it applies to:

```markdown
## Columns

- Tables: Customer

| Column | DataType | Nullable (Y/N) | Primary Key (Yes) | Foreign Key (Y/N) | Related Entity | Details | Description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| customer_id | INT | N | Yes | N |  |  | Unique id |
| name | STRING | Y |  | N |  |  | Full name |
```

Edit freely before continuing:

- **Tables** — change the comma-separated list after `- Tables:` (each name
  becomes a `{table}_schema.md` file).
- **Column / DataType / Details / Description** — adjust as needed.
- **Nullable / Foreign Key** — use `Y`/`N` (blank = unknown). **Primary Key** —
  use `Yes` (blank = not a primary key). Set **Related Entity** for foreign keys.
- Delete rows you do not want, or remove an entire column set to skip it.

Save the file when done.

---

## Step 3 — Create the schema files

```powershell
python -m docx_schema create-schema .\tables-mapping.md
```

Choose a different output directory (default is `.\schema`):

```powershell
python -m docx_schema create-schema .\tables-mapping.md --out-dir .\schema
```

Expected output:

```
Wrote 2 schema file(s) to schema:
  - schema\Customer_schema.md
  - schema\Order_schema.md
```

**Pass criteria:** one `{table}_schema.md` file is written per table listed in
each column set's `- Tables:` line, and each file contains the reviewed columns.

---

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `error: docx not found` | Wrong path or typo | Check the path; drag the file into the terminal to paste its full path. |
| `Detected 0 table(s)` | Document has no recognizable tables or headers | Ensure tables use a header row, or add `Table: <name>` / `Entity: <name>` lines above column definitions. |
| `error: no tables found in mapping markdown` | The mapping file has no `## Columns` / `## Column Set` sections | Re-run Step 1, or restore the `## Columns` headings and `- Tables:` lines. |
| `DOCX ... contains disallowed XML declarations` | The `.docx` is malformed or crafted | Use a clean, standard Word document. |

---

## Quick reference

```powershell
# 1. Propose
python -m docx_schema propose-mapping .\tables.docx

# 2. Edit the generated *-mapping.md by hand

# 3. Create schema files
python -m docx_schema create-schema .\tables-mapping.md --out-dir .\schema
```
