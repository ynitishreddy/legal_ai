"""
app.document_processing.extractors.docx_extractor — DOCX file extractor.
"""

import time
import os
import logging
from typing import List

import docx
from docx.oxml.text.paragraph import CT_P
from docx.oxml.table import CT_Tbl
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.document_processing.extractors.base import AbstractDocumentExtractor, ExtractionResult
from app.document_processing.exceptions import ExtractionError

logger = logging.getLogger(__name__)


class DocxExtractor(AbstractDocumentExtractor):
    """
    Parser for Word Documents (.docx).
    Preserves reading order by traversing document body XML elements,
    extracting headings, lists, tables (flattened into markdown), and paragraphs.
    """

    def can_handle(self, mime_type: str) -> bool:
        return mime_type in {
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/msword",
        }

    def extract(self, file_path: str) -> ExtractionResult:
        start_time = time.time()

        if not os.path.exists(file_path):
            raise ExtractionError(f"File not found: {file_path}")

        try:
            doc = docx.Document(file_path)
        except Exception as exc:
            logger.error("Failed to load DOCX document: %s", exc, exc_info=True)
            raise ExtractionError(f"Failed to load DOCX: {exc}") from exc

        body_elements = doc.element.body
        extracted_parts: List[str] = []

        # Traverse body in reading order
        for child in body_elements:
            if isinstance(child, CT_P):
                p = Paragraph(child, doc)
                text = p.text.strip()
                if not text:
                    continue

                style_name = p.style.name.lower() if p.style else ""
                
                # Format headings as Markdown headings
                if style_name.startswith("heading"):
                    level = 1
                    try:
                        # Extract level from style name, e.g. "heading 3" -> 3
                        parts = style_name.split()
                        if len(parts) > 1 and parts[1].isdigit():
                            level = int(parts[1])
                    except Exception:
                        pass
                    extracted_parts.append(f"\n{'#' * level} {text}\n")
                
                # Format list items
                elif "list" in style_name or style_name.startswith("bullet"):
                    extracted_parts.append(f"* {text}")
                
                else:
                    # Regular paragraph
                    extracted_parts.append(text)

            elif isinstance(child, CT_Tbl):
                # Render table cell data as markdown-style table
                t = Table(child, doc)
                table_lines: List[str] = []
                for row_idx, row in enumerate(t.rows):
                    row_cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
                    # Separate columns by pipe
                    line = "| " + " | ".join(row_cells) + " |"
                    table_lines.append(line)

                    # Add separator line after header row
                    if row_idx == 0:
                        separator = "| " + " | ".join(["---"] * len(row_cells)) + " |"
                        table_lines.append(separator)

                if table_lines:
                    extracted_parts.append("\n" + "\n".join(table_lines) + "\n")

        full_text = "\n\n".join(extracted_parts)
        processing_time = time.time() - start_time

        # Extract metadata
        metadata = {}
        try:
            core_properties = doc.core_properties
            metadata = {
                "author": core_properties.author or "",
                "title": core_properties.title or "",
                "revision": core_properties.revision or 0,
                "created": core_properties.created.isoformat() if core_properties.created else "",
                "modified": core_properties.modified.isoformat() if core_properties.modified else "",
            }
        except Exception as exc:
            logger.warning("Failed to extract DOCX core properties metadata: %s", exc)

        return ExtractionResult(
            extracted_text=full_text,
            extraction_method="docx",
            page_count=1,  # Word files don't store pre-computed page counts directly
            processing_time=processing_time,
            confidence_score=1.0,
            has_ocr=False,
            metadata=metadata,
            warnings=[],
            success=True,
        )
