"""
app.document_processing.cleaning.strategies.tables — Table flattening strategy (Phase 5.3).
"""

import re
from typing import Dict, Any, Tuple, List
from app.document_processing.cleaning.cleaner import CleaningStrategy


class TableFlatteningStrategy(CleaningStrategy):
    """
    Detects ASCII / Markdown grids containing pipe characters '|'
    and flattens them into a readable key-value list structure, preserving row order.
    """

    def applies(self, doc_type: str) -> bool:
        return True

    def clean(self, text: str, context: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        if not text:
            return "", context

        lines = text.split("\n")
        output_lines: List[str] = []
        
        in_table = False
        table_buffer: List[str] = []
        tables_flattened_count = 0

        def process_and_flatten_table(buffer: List[str]) -> List[str]:
            nonlocal tables_flattened_count
            if not buffer:
                return []

            # Filter out divider rows (e.g. |---|---| or |===|===|)
            rows: List[List[str]] = []
            for row_line in buffer:
                stripped = row_line.strip()
                # Skip dashed dividers
                if re.match(r"^\|?\s*[-=:\s|]+\s*\|?$", stripped):
                    continue
                
                # Split columns by pipe and strip
                cols = [col.strip() for col in row_line.split("|")]
                # Strip outer empty elements if row started/ended with pipes
                if cols and not cols[0]:
                    cols = cols[1:]
                if cols and not cols[-1]:
                    cols = cols[:-1]
                
                if any(cols):  # only keep rows that have some content
                    rows.append(cols)

            if len(rows) < 2:
                # Not a valid table with headers + data, return buffer unchanged
                return buffer

            headers = rows[0]
            data_rows = rows[1:]
            
            flattened = []
            flattened.append("--- Table Start ---")
            
            for row_idx, row in enumerate(data_rows):
                flattened.append(f"Row {row_idx + 1}:")
                for col_idx, col_val in enumerate(row):
                    # Find header name
                    header_name = headers[col_idx] if col_idx < len(headers) else f"Column {col_idx + 1}"
                    # Skip empty values or standard placeholders
                    if not col_val or col_val == "-":
                        col_val = "—"
                    flattened.append(f"  {header_name}: {col_val}")
                flattened.append("")  # gap between rows

            flattened.append("--- Table End ---")
            tables_flattened_count += 1
            return [line for line in flattened if line is not None]

        idx = 0
        while idx < len(lines):
            line = lines[idx]
            stripped = line.strip()
            
            # Simple heuristic: lines containing '|'
            # (excluding standalone noise pipe characters cleaned in OCR strategy)
            is_table_row = "|" in line and not re.match(r"^\s*\|\s*$", stripped)

            if is_table_row:
                in_table = True
                table_buffer.append(line)
            else:
                if in_table:
                    # Table ended, process buffer
                    flattened_table_lines = process_and_flatten_table(table_buffer)
                    output_lines.extend(flattened_table_lines)
                    table_buffer = []
                    in_table = False
                
                output_lines.append(line)
            
            idx += 1

        # Process trailing table buffer if file ends during table
        if in_table and table_buffer:
            flattened_table_lines = process_and_flatten_table(table_buffer)
            output_lines.extend(flattened_table_lines)

        context["tables_flattened"] = context.get("tables_flattened", 0) + tables_flattened_count
        return "\n".join(output_lines), context
