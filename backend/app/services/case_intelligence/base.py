from abc import ABC, abstractmethod
from typing import List, Dict, Any


class AbstractExtractor(ABC):
    """
    Base abstract interface class that all legal case intelligence
    extractor strategies must inherit.
    """
    @abstractmethod
    def extract(self, chunk_text: str, metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Executes granular information extraction on chunk level.
        Returns a list of extracted dictionaries containing properties and confidence indices.
        """
        pass
