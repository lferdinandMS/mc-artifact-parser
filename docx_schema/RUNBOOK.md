# docx_schema Runbook

## Workflow

1. `propose-mapping` reads `.docx` tables, groups tables into `Column Set N` sections by shared header signatures, and emits a self-contained mapping markdown.
2. Reviewer updates `Target Column` cells in each crosswalk as needed.
3. `create-schema` reads only the reviewed mapping markdown and writes one populated `{table}_schema.md` per table.

## Step 2 mapping format (self-contained)

```markdown
## Column Set 1

| Extracted Column | Target Column |
|---|---|
| Name | Column |
| Data Type | Type |
| Is Nullable | Nullable |

### Customer

| Column | Type | Nullable | Primary Key | Foreign Key | Details | Description | Source |
|---|---|---|---|---|---|---|---|
| customer_id | int | No | Yes |  |  |  |  |
| email | string | Yes | No |  |  |  |  |
```

Each `### <table>` section carries table rows projected into the 8-column target layout, so the mapping file is fully self-contained.

## Step 3 schema output (riders)

Every generated schema appends two rider sections that are always present and default to empty:

```markdown
## Custom Riders

_None defined._

## Provenance / Audit Columns

_None defined._
```

Concrete provenance/audit columns are supplied by the target adapter (platform layer), not by `docx_schema`.

### Provenance-column format recommendation template

Use this template when a target adapter (or reviewer) defines concrete provenance columns:

- **Name**: column name
- **Load rule**: how value is derived
- **Populated on**: insert/update/both/CDC lifecycle point
- **Description**: purpose and downstream usage notes
