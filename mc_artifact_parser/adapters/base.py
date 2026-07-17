from __future__ import annotations

from abc import ABC, abstractmethod

from mc_artifact_parser.models import ArtifactParseResult


class ArtifactAdapter(ABC):
    @abstractmethod
    def can_parse(self, path: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def parse(self, path: str) -> ArtifactParseResult:
        raise NotImplementedError
