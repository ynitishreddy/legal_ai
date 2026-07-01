import re
from typing import List, Dict, Any
from app.services.case_intelligence.base import AbstractExtractor
from app.services.case_intelligence.confidence import ConfidenceScoringService

class ArgumentExtractor(AbstractExtractor):
    def extract(self, chunk_text: str, metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
        results = []
        
        # Rule sets mapped to their type categories
        rules = [
            {
                "type": "argument_petitioner",
                "patterns": [
                    r"\b(?:petitioner|plaintiff|appellant)\s+(?:argued|contended|submitted|pleaded)\s+that\s+([^.!?]{10,250})",
                    r"\b(?:argued|contended|submitted)\s+by\s+(?:the\s+)?(?:petitioner|plaintiff|appellant)\s+that\s+([^.!?]{10,250})"
                ],
                "base_confidence": 0.85
            },
            {
                "type": "argument_respondent",
                "patterns": [
                    r"\b(?:respondent|defendant)\s+(?:argued|contended|submitted|pleaded)\s+that\s+([^.!?]{10,250})",
                    r"\b(?:argued|contended|submitted)\s+by\s+(?:the\s+)?(?:respondent|defendant)\s+that\s+([^.!?]{10,250})"
                ],
                "base_confidence": 0.85
            },
            {
                "type": "ratio_decidendi",
                "patterns": [
                    r"\b(?:ratio\s+decidendi|core\s+holding)\s+(?:is|of\s+the\s+case\s+is)\s+that\s+([^.!?]{15,300})",
                    r"\bwe\s+hold\s+that\s+([^.!?]{15,300})",
                    r"\bcourt\s+is\s+of\s+the\s+firm\s+view\s+that\s+([^.!?]{15,300})"
                ],
                "base_confidence": 0.95
            },
            {
                "type": "obiter_dicta",
                "patterns": [
                    r"\bobiter\s+dicta\s+([^.!?]{15,250})",
                    r"\bobserved\s+in\s+passing\s+that\s+([^.!?]{15,250})",
                    r"\bby\s+way\s+of\s+obiter\s+([^.!?]{15,250})"
                ],
                "base_confidence": 0.80
            },
            {
                "type": "court_reasoning",
                "patterns": [
                    r"\bcourt\s+(?:reasoned|noted|observed)\s+that\s+([^.!?]{15,250})",
                    r"\bin\s+our\s+(?:opinion|view)\s+([^.!?]{15,250})"
                ],
                "base_confidence": 0.90
            }
        ]

        for rule in rules:
            for pattern in rule["patterns"]:
                for match in re.finditer(pattern, chunk_text, re.IGNORECASE):
                    statement = match.group(1).strip()
                    if not statement:
                        continue
                    
                    # Compute multi-factor confidence
                    score_res = ConfidenceScoringService.calculate_score(
                        base_extractor_conf=rule["base_confidence"]
                    )

                    results.append({
                        "type": rule["type"],
                        "statement": statement,
                        "confidence_score": score_res["final_score"],
                        "confidence_breakdown": score_res["breakdown"]
                    })

        return results
