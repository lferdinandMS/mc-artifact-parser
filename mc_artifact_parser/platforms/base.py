from __future__ import annotations

from abc import ABC, abstractmethod

from mc_artifact_parser.models import ArtifactParseResult


class PlatformAdapter(ABC):
    """Base class for platform-specific physical schema renderers.

    Implementors convert a logical ``ArtifactParseResult`` into DDL or other
    platform-specific schema definitions.
    """

    @abstractmethod
    def render(self, result: ArtifactParseResult) -> str:
        raise NotImplementedError
