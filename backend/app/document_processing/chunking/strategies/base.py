"""
app.document_processing.chunking.strategies.base — Strategy interface base class.
"""

from abc import ABC, abstractmethod
from typing import List
from app.document_processing.chunking.schemas import ChunkingConfig, ChunkResult


class ChunkingStrategy(ABC):
    """
    Abstract Base Class for document text chunking strategies.
    Implementations should split text cleanly and populate correct metadata references.
    """

    @abstractmethod
    def can_handle(self, doc_category: str) -> bool:
        """
        Determines if this strategy supports the document category.
        """
        pass

    @abstractmethod
    def chunk(self, text: str, config: ChunkingConfig) -> List[ChunkResult]:
        """
        Processes text and splits it into a list of ChunkResult objects.
        """
        pass
