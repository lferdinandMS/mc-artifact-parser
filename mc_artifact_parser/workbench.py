from __future__ import annotations

from dataclasses import dataclass, field
from dataclasses import replace

from mc_artifact_parser.models import ArtifactParseResult, ColumnSchema, EntitySchema
from mc_artifact_parser.outputs.data_dictionary import DataDictionaryOutput
from mc_artifact_parser.outputs.mappings import MappingMarkdownOutput
from mc_artifact_parser.outputs.mermaid_erd import MermaidErdOutput
from mc_artifact_parser.outputs.open_questions import OpenQuestionsOutput
from mc_artifact_parser.outputs.session_mapping import SessionMappingOutput
from mc_artifact_parser.outputs.source_review import SourceReviewOutput
from mc_artifact_parser.outputs.table_schema_markdown import TableSchemaMarkdownOutput
from mc_artifact_parser.parser import ArtifactParser


@dataclass
class CompletenessIssue:
    entity_name: str | None
    message: str


@dataclass
class ColumnAssessment:
    entity_name: str
    column_name: str
    status: str
    notes: list[str] = field(default_factory=list)


class SchemaCompletenessChecker:
    def check(self, result: ArtifactParseResult) -> list[CompletenessIssue]:
        issues: list[CompletenessIssue] = []
        known_entities = {entity.name for entity in result.entities}

        if not result.entities:
            issues.append(CompletenessIssue(entity_name=None, message="No tables have been parsed yet."))
            return issues

        for entity in result.entities:
            if not entity.columns:
                issues.append(CompletenessIssue(entity.name, "No columns were extracted for this table."))

            if not any(column.primary_key for column in entity.columns):
                issues.append(CompletenessIssue(entity.name, "No primary key was identified."))

            for column in entity.columns:
                if column.data_type is None:
                    issues.append(CompletenessIssue(entity.name, f"Column '{column.name}' is missing a data type."))

            for related in entity.related_entities:
                if related not in known_entities:
                    issues.append(CompletenessIssue(entity.name, f"Related table '{related}' has not been provided yet."))

        return issues

    def generate_questions(self, result: ArtifactParseResult) -> list[str]:
        questions: list[str] = []

        for issue in self.check(result):
            if issue.entity_name is None:
                questions.append(issue.message)
                continue

            if issue.message == "No columns were extracted for this table.":
                questions.append("Provide the types for the columns")
            elif issue.message.startswith("Related table '"):
                related_name = issue.message.split("'", 2)[1]
                questions.append(f"Should {issue.entity_name} reference {related_name}?")

        for entity in result.entities:
            questions.extend(self._missing_target_field_questions(entity))

        return self._dedupe(questions)

    def _missing_target_field_questions(self, entity: EntitySchema) -> list[str]:
        questions: list[str] = []

        if not entity.columns:
            return questions

        def _join_column_names(names: list[str]) -> str:
            return ", ".join(names)

        missing_type = [column.name for column in entity.columns if column.data_type is None]
        missing_nullable = [column.name for column in entity.columns if column.nullable is None]
        missing_foreign_key = [
            column.name
            for column in entity.columns
            if (column.name.lower().endswith("_id") or column.name.lower().endswith(" id")) and not column.foreign_key
        ]
        missing_details_description = [
            column.name
            for column in entity.columns
            if not (column.description and column.description.strip())
        ]

        if missing_type:
            questions.append(f"Provide Type values for: {_join_column_names(missing_type)}")

        if missing_nullable:
            questions.append(f"Specify Nullable values (Yes/No) for: {_join_column_names(missing_nullable)}")

        if not any(column.primary_key for column in entity.columns):
            questions.append(f"Identify the primary key column(s) for {entity.name}")

        if missing_foreign_key:
            questions.append(f"Confirm Foreign Key values for: {_join_column_names(missing_foreign_key)}")

        if missing_details_description:
            questions.append(f"Provide Details and Description values for: {_join_column_names(missing_details_description)}")

        return questions

    def _dedupe(self, items: list[str]) -> list[str]:
        deduped: list[str] = []
        for item in items:
            if item not in deduped:
                deduped.append(item)
        return deduped


@dataclass
class SchemaWorkbench:
    parser: ArtifactParser = field(default_factory=ArtifactParser)
    completeness_checker: SchemaCompletenessChecker = field(default_factory=SchemaCompletenessChecker)
    _result: ArtifactParseResult = field(
        default_factory=lambda: ArtifactParseResult(source_path="", artifact_type="aggregate")
    )
    _sources: list[str] = field(default_factory=list)

    def add(self, path: str) -> ArtifactParseResult:
        parsed = self.parser.parse(path)
        self._sources.append(path)
        self._merge_result(parsed)
        return parsed

    def add_many(self, paths: list[str]) -> ArtifactParseResult:
        for path in paths:
            self.add(path)
        return self.result

    def assess_columns(self) -> list[ColumnAssessment]:
        assessments: list[ColumnAssessment] = []

        for entity in self.result.entities:
            for column in entity.columns:
                notes: list[str] = []
                status = "approved"

                if column.data_type is None:
                    notes.append("Missing data type")
                    status = "needs_review"

                if " " in column.name:
                    notes.append("Column name contains spaces")
                    status = "needs_review"

                if column.name.lower() in {"source", "date", "status", "notes"}:
                    notes.append("Common label that should be verified manually")
                    if status != "needs_review":
                        status = "review_optional"

                assessments.append(
                    ColumnAssessment(
                        entity_name=entity.name,
                        column_name=column.name,
                        status=status,
                        notes=notes,
                    )
                )

        return assessments

    def replace_entity_columns(self, entity_name: str, columns: list[ColumnSchema]) -> None:
        entity = self._find_entity(entity_name)
        if entity is None:
            raise ValueError(f"Entity '{entity_name}' was not found in the accumulated schema.")

        entity.columns = columns

    def review_entity_columns(self, entity_name: str, columns: list[ColumnSchema]) -> ArtifactParseResult:
        self.replace_entity_columns(entity_name, columns)
        return self.result

    @property
    def result(self) -> ArtifactParseResult:
        self._result.source_path = "; ".join(self._sources)
        self._result.artifact_type = "aggregate"
        return self._result

    @property
    def completeness_issues(self) -> list[CompletenessIssue]:
        return self.completeness_checker.check(self.result)

    @property
    def generated_open_questions(self) -> list[str]:
        generated = self.completeness_checker.generate_questions(self.result)
        existing: list[str] = list(self.result.open_questions)
        for entity in self.result.entities:
            existing.extend(entity.open_questions)

        combined: list[str] = []
        for question in existing + generated:
            if question not in combined:
                combined.append(question)
        return combined

    def build_data_dictionary(self) -> str:
        return DataDictionaryOutput().render(self.result)

    def build_erd(self) -> str:
        return MermaidErdOutput().render(self.result)

    def build_table_schema_markdowns(self) -> dict[str, str]:
        documents: dict[str, str] = {}
        renderer = TableSchemaMarkdownOutput()

        for entity in self.result.entities:
            filename = self._entity_filename(entity.name)
            reviewed_entity = replace(entity, open_questions=self._entity_open_questions(entity))
            entity_result = ArtifactParseResult(
                source_path=self.result.source_path,
                artifact_type="aggregate",
                entities=[reviewed_entity],
            )
            documents[filename] = renderer.render(entity_result)

        return documents

    def build_mapping_markdowns(self) -> dict[str, str]:
        documents: dict[str, str] = {}
        renderer = MappingMarkdownOutput()

        for entity in self.result.entities:
            filename = self._entity_filename(entity.name)
            reviewed_entity = replace(entity, open_questions=self._entity_open_questions(entity))
            entity_result = ArtifactParseResult(
                source_path=self.result.source_path,
                artifact_type="aggregate",
                entities=[reviewed_entity],
            )
            documents[filename] = renderer.render(entity_result)

        return documents

    def build_open_questions(self) -> str:
        return OpenQuestionsOutput().render(self._result_with_generated_questions())

    def build_source_review_report(self) -> str:
        return SourceReviewOutput().render(self._result_with_generated_questions())

    def build_session_mapping_proposal(self) -> str:
        return SessionMappingOutput().render(self._result_with_generated_questions())

    def _result_with_generated_questions(self) -> ArtifactParseResult:
        return ArtifactParseResult(
            source_path=self.result.source_path,
            artifact_type=self.result.artifact_type,
            entities=self.result.entities,
            open_questions=self.generated_open_questions,
        )

    def _entity_open_questions(self, entity: EntitySchema) -> list[str]:
        questions: list[str] = list(entity.open_questions)

        questions.extend(self.completeness_checker._missing_target_field_questions(entity))

        for issue in self.completeness_issues:
            if issue.entity_name != entity.name:
                continue

            if issue.message == "No columns were extracted for this table.":
                questions.append("Provide the types for the columns")
            elif issue.message.startswith("Related table '"):
                related_name = issue.message.split("'", 2)[1]
                questions.append(f"Should {entity.name} reference {related_name}?")

        deduped: list[str] = []
        for question in questions:
            if question not in deduped:
                deduped.append(question)

        return deduped

    def _merge_result(self, parsed: ArtifactParseResult) -> None:
        for entity in parsed.entities:
            target = self._find_entity(entity.name)
            if target is None:
                self._result.entities.append(entity)
                continue

            self._merge_entity(target, entity)

        for question in parsed.open_questions:
            self._append_unique(self._result.open_questions, question)

    def _find_entity(self, name: str) -> EntitySchema | None:
        for entity in self._result.entities:
            if entity.name == name:
                return entity
        return None

    def _merge_entity(self, target: EntitySchema, incoming: EntitySchema) -> None:
        for table_name in incoming.implied_tables:
            self._append_unique(target.implied_tables, table_name)

        for related in incoming.related_entities:
            self._append_unique(target.related_entities, related)

        for question in incoming.open_questions:
            self._append_unique(target.open_questions, question)

        for column in incoming.columns:
            target_column = self._find_column(target, column.name)
            if target_column is None:
                target.columns.append(column)
                continue

            if target_column.data_type is None and column.data_type is not None:
                target_column.data_type = column.data_type
            if target_column.nullable is None and column.nullable is not None:
                target_column.nullable = column.nullable
            target_column.primary_key = target_column.primary_key or column.primary_key

    def _find_column(self, entity: EntitySchema, name: str) -> ColumnSchema | None:
        for column in entity.columns:
            if column.name == name:
                return column
        return None

    def _append_unique(self, items: list[str], value: str) -> None:
        if value not in items:
            items.append(value)

    def _entity_filename(self, entity_name: str) -> str:
        safe_name = entity_name.strip().lower()
        safe_name = "".join(char if char.isalnum() or char in {" ", "_", "-"} else " " for char in safe_name)
        safe_name = "_".join(part for part in safe_name.split() if part)
        return f"{safe_name or 'entity'}.md"
