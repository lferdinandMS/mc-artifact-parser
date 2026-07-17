from __future__ import annotations

from mc_artifact_parser.adapters.base import ArtifactAdapter
from mc_artifact_parser.adapters.docx import DocxAdapter
from mc_artifact_parser.adapters.image import ImageAdapter
from mc_artifact_parser.adapters.markdown import MarkdownAdapter
from mc_artifact_parser.models import ArtifactParseResult


class ArtifactParser:
    def __init__(self, adapters: list[ArtifactAdapter] | None = None) -> None:
        self._adapters = [DocxAdapter(), MarkdownAdapter(), ImageAdapter()] if adapters is None else adapters

    def parse(self, path: str) -> ArtifactParseResult:
        for adapter in self._adapters:
            if adapter.can_parse(path):
                return adapter.parse(path)

        raise ValueError(f"No adapter available for artifact path: {path}")
