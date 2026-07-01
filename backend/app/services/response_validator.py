import logging
import re
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


class ResponseValidator:
    """
    Validates RAG engine responses to prevent hallucinations and check
    citation grounding.
    """

    def validate_response(
        self,
        content: str,
        retrieved_chunks: List[Dict[str, Any]],
        threshold: float = 0.05
    ) -> Dict[str, Any]:
        """
        Runs check validations. Returns dict with 'success' and 'message'.
        """
        # If response states information not found, it is valid grounding fallback
        if "provided document contexts do not contain any information" in content or "I am sorry" in content:
            return {"success": True, "message": "Grounded fallback response."}

        # 1. Check for hallucinated citation references
        # Find citations in final text
        referenced_uuids = re.findall(r"\[Citation: ([a-zA-Z0-9\-]+)\]", content)
        
        retrieved_ids = {str(c.get("chunk_id")) for c in retrieved_chunks}
        
        hallucinated_citations = []
        for ref_id in referenced_uuids:
            if ref_id not in retrieved_ids:
                hallucinated_citations.append(ref_id)
                
        if hallucinated_citations:
            logger.warning("ResponseValidator: Hallucinated citations detected: %s", hallucinated_citations)
            return {
                "success": False,
                "message": f"Hallucinated citations detected: {hallucinated_citations}",
                "code": "hallucinated_citations",
            }

        # 2. Check for unsupported claims: no citations present in a lengthy answer
        if len(content.split()) > 30 and not referenced_uuids:
            logger.warning("ResponseValidator: Long response contains zero citations.")
            return {
                "success": False,
                "message": "Answer lacks grounding citations.",
                "code": "missing_citations",
            }

        return {"success": True, "message": "Grounding verification passed."}
