"""
app.document_processing.chunking.exceptions — Custom exceptions for chunking pipeline.
"""

class ChunkingError(Exception):
    """Base class for all chunking pipeline exceptions."""
    pass


class ChunkingValidationError(ChunkingError):
    """Raised when generated chunks violate pipeline integrity constraints."""
    pass


class StrategyNotFoundError(ChunkingError):
    """Raised when no suitable chunking strategy can handle the document."""
    pass
