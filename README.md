# mc-artifact-parser
Use to parse artifacts containing limited schema guidance.

## Python parser

This repository includes a generalized Python artifact parser with pluggable adapters.

Current adapter support:
- DOCX (`.docx`)

### Example

```python
from mc_artifact_parser import ArtifactParser

result = ArtifactParser().parse("/path/to/schema.docx")
for entity in result.entities:
    print(entity.name)
    print(entity.implied_tables)
    print(entity.related_entities)
    print(entity.open_questions)
```
