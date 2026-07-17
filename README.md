# mc-artifact-parser
Use to parse artifacts containing limited schema guidance.

## Python parser

This repository includes a generalized Python artifact parser with pluggable adapters.

Current adapter support:
- DOCX (`.docx`)
- Markdown (`.md`)
- Images (`.png`, `.jpg`, `.jpeg`, `.bmp`, `.gif`, `.tif`, `.tiff`, `.webp`) via OCR

### Parse a schema artifact

```python
from mc_artifact_parser import ArtifactParser

result = ArtifactParser().parse("/path/to/schema.docx")
for entity in result.entities:
    print(entity.name)
    print(entity.implied_tables)
    print([(c.name, c.data_type, c.nullable, c.primary_key) for c in entity.columns])
    print(entity.related_entities)
    print(entity.open_questions)
```

Markdown files are parsed the same way — H2–H6 headings are treated as entity names:

```python
result = ArtifactParser().parse("/path/to/schema.md")
```

Image files are parsed through OCR first, then processed with the same schema rules:

```python
result = ArtifactParser().parse("/path/to/schema.png")
```

For image parsing, install an OCR engine such as Tesseract. If you want to plug in
your own OCR pipeline, pass a custom text extractor to `ImageAdapter`.

### Accumulate multiple inputs before rendering outputs

Use `SchemaWorkbench` when you want to add several documents or images over time.
The first phase is to review the per-table markdown bundle, and only after the
collection is complete do you render a data dictionary or ERD:

```python
from mc_artifact_parser import SchemaWorkbench

workbench = SchemaWorkbench()
workbench.add("/path/to/customer.png")
workbench.add("/path/to/order.png")

table_docs = workbench.build_table_schema_markdowns()
mapping_docs = workbench.build_mapping_markdowns()
print(workbench.completeness_issues)
print(workbench.generated_open_questions)
print(table_docs)
print(mapping_docs)
print(workbench.build_data_dictionary())
print(workbench.build_erd())
```

`build_table_schema_markdowns()` returns a dictionary of markdown file names to
per-table schema markdown content. Each file is named from the entity name.

`build_mapping_markdowns()` returns a dictionary of markdown file names to
per-table human review mapping templates that preserve the parsed source values
and leave the intended output structure for review.

### Agent workflow orchestration

Use `SchemaWorkflowAgent` to run a staged human-in-the-loop workflow:

```python
from mc_artifact_parser import ArtifactParser, SchemaWorkflowAgent, SchemaWorkbench

workbench = SchemaWorkbench(parser=ArtifactParser())
agent = SchemaWorkflowAgent(workbench=workbench, output_root="review-bundle")

agent.review_sources(["/path/to/schema.png"])
agent.propose_mapping()
agent.approve_mapping()
agent.draft_outputs()
agent.finalize_outputs()
```

Artifacts are written to these folders under `review-bundle`:
- `session/` for source review, session mapping proposal, and persisted stage state
- `mappings/` for per-table mapping files
- `drafts/` for draft table schemas and draft data dictionary
- `final/` for final ERD and final data dictionary

Command-line usage:

```bash
python -m mc_artifact_parser --sources /path/to/schema.md
```

Slash workflow commands:

```bash
python -m mc_artifact_parser /mapping --sources /path/to/schema.png --output-root review-bundle
```

`/mapping` runs review, proposes mapping, approves mapping, and writes per-entity mapping files to `review-bundle/mappings/` in the mapping template format.

After reviewer edits/finalizes mapping files, run extraction:

```bash
python -m mc_artifact_parser /extraction --output-root review-bundle
```

`/extraction` loads the finalized mapping files and applies the mapping contract when rendering the final data dictionary.

To remove generated workflow output folders quickly:

```bash
python -m mc_artifact_parser /clean
```

`/clean` removes generated output directories such as `review-bundle`, `slash-workflow-demo`, and `walkthrough*` folders from the current working directory.

Run specific stages explicitly:

```bash
python -m mc_artifact_parser --sources /path/to/schema.md --review-sources --propose-mapping
python -m mc_artifact_parser --approve-mapping --draft-outputs --finalize
```

---

### Output renderers

Three output renderers are available to format a parse result.

#### Data dictionary (Markdown table)

```python
from mc_artifact_parser import ArtifactParser, DataDictionaryOutput

result = ArtifactParser().parse("/path/to/schema.docx")
print(DataDictionaryOutput().render(result))
```

Produces a Markdown document with a column table per entity, related-entity
lists, and open questions.

#### ERD as a Mermaid diagram

```python
from mc_artifact_parser import ArtifactParser, MermaidErdOutput

result = ArtifactParser().parse("/path/to/schema.docx")
print(MermaidErdOutput().render(result))
```

Produces a fenced `mermaid` code block containing an `erDiagram` with columns
annotated as `PK` / `FK` and relationship lines derived from `related_entities`.

#### Open questions list

```python
from mc_artifact_parser import ArtifactParser, OpenQuestionsOutput

result = ArtifactParser().parse("/path/to/schema.docx")
print(OpenQuestionsOutput().render(result))
```

Produces a Markdown list of all open questions grouped by global scope and entity.

---

### Physical schema — Unity Catalog

Convert a parsed logical schema to Databricks Unity Catalog DDL:

```python
from mc_artifact_parser import ArtifactParser, UnityCatalogAdapter

result = ArtifactParser().parse("/path/to/schema.docx")
print(UnityCatalogAdapter().render(result))
```

Each entity becomes a `CREATE TABLE IF NOT EXISTS … USING DELTA;` statement.
Logical types (`varchar`, `int`, `boolean`, …) are mapped to Unity Catalog SQL
types; unknown types default to `STRING`.
