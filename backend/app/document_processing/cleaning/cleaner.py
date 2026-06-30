"""
app.document_processing.cleaning.cleaner — Strategy interface and orchestrator for text cleaning.
"""

import logging
import time
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Tuple

logger = logging.getLogger(__name__)


class CleaningStrategy(ABC):
    """
    Abstract Base Class for independent text cleaning strategies.
    Each strategy performs a single modular task (e.g., Unicode normalization, header removal).
    """

    @abstractmethod
    def applies(self, doc_type: str) -> bool:
        """
        Determine if this strategy should execute for the document category type.
        """
        pass

    @abstractmethod
    def clean(self, text: str, context: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        """
        Applies the cleaning strategy to the text.
        Returns the updated text and updated context containing metrics.
        """
        pass

    def validate(self, text: str) -> bool:
        """
        Verifies that this cleaning strategy did not corrupt basic text formatting.
        Defaults to True. Can be overridden by specific strategies.
        """
        return True


class TextCleanerOrchestrator:
    """
    Main engine that executes a list of CleaningStrategy classes sequentially
    and collects aggregate execution metrics.
    """

    def __init__(self, strategies: List[CleaningStrategy]) -> None:
        self.strategies = strategies

    def clean_document(self, text: str, doc_type: str) -> Tuple[str, Dict[str, Any]]:
        """
        Runs all applicable cleaning strategies on the text sequentially.
        """
        start_time = time.time()
        context: Dict[str, Any] = {
            "characters_removed": 0,
            "headers_removed": 0,
            "footers_removed": 0,
            "page_numbers_removed": 0,
            "hyphen_repairs": 0,
            "ocr_repairs": 0,
            "whitespace_reductions": 0,
            "bullets_normalized": 0,
            "tables_flattened": 0,
            "warnings": [],
            "history": [],
        }

        current_text = text

        for strategy in self.strategies:
            if not strategy.applies(doc_type):
                continue

            strategy_name = strategy.__class__.__name__
            logger.info("Executing cleaning strategy: %s", strategy_name)
            initial_len = len(current_text)
            strategy_start = time.time()

            try:
                # Run the strategy
                cleaned_text, context = strategy.clean(current_text, context)

                # Post-validation
                if not strategy.validate(cleaned_text):
                    logger.warning("Strategy %s failed validation. Reverting changes.", strategy_name)
                    context["warnings"].append(f"Strategy {strategy_name} validation failed; reverted.")
                else:
                    current_text = cleaned_text
                    chars_changed = initial_len - len(current_text)
                    context["history"].append({
                        "strategy": strategy_name,
                        "chars_removed": chars_changed,
                        "duration_ms": int((time.time() - strategy_start) * 1000),
                    })

            except Exception as exc:
                logger.error("Error executing strategy %s: %s", strategy_name, exc, exc_info=True)
                context["warnings"].append(f"Strategy {strategy_name} crashed: {exc}")

        context["processing_time"] = time.time() - start_time
        context["characters_removed"] = max(0, len(text) - len(current_text))

        return current_text, context
