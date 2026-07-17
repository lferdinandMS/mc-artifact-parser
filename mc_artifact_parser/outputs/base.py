from __future__ import annotations

from abc import ABC, abstractmethod

from mc_artifact_parser.models import ArtifactParseResult


class OutputRenderer(ABC):
    """Base class for output renderers that produce formatted text from a parse result."""

    @abstractmethod
    def render(self, result: ArtifactParseResult) -> str:
        raise NotImplementedError
