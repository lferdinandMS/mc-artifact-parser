# schema_parser Runbook

## Workflow

1. `propose-mapping` reads `.docx` tables, groups tables into distinct `Column Set N` sections by shared header signatures, and emits a reviewed crosswalk for each set.
2. Reviewer updates `Target Column` cells in each crosswalk as needed.
3. `create-schema` reads the reviewed mapping markdown plus the source `.docx`, matches each table to its column set, and writes one populated `{table}_schema.md` per table.

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

Each `Column Set N` section is the input contract for `create-schema`: the crosswalk defines how tables with that source header shape are projected into the target schema.

## Step 3 schema output (riders)

Every generated schema appends two rider sections that are always present and default to empty:

```markdown
## Custom Riders

_None defined._

## Provenance / Audit Columns

_None defined._
```

Concrete provenance/audit columns are supplied by the target adapter (platform layer), not by `schema_parser`.

### Provenance-column format recommendation template

Use this template when a target adapter (or reviewer) defines concrete provenance columns:

- **Name**: column name
- **Load rule**: how value is derived
- **Populated on**: insert/update/both/CDC lifecycle point
- **Description**: purpose and downstream usage notes
