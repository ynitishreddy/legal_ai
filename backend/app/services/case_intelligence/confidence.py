from typing import Dict, Any, Optional

class ConfidenceScoringService:
    @staticmethod
    def calculate_score(
        base_extractor_conf: float,
        embedding_similarity: Optional[float] = None,
        llm_validation_conf: Optional[float] = None,
        normalization_conf: Optional[float] = None,
        relationship_weight: Optional[float] = None,
        evidence_strength: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Combines multiple confidence factors into a single normalized confidence score and returns a breakdown.
        """
        breakdown = {
            "extractor_confidence": base_extractor_conf,
            "embedding_similarity": embedding_similarity,
            "llm_validation_confidence": llm_validation_conf,
            "normalization_confidence": normalization_conf,
            "relationship_weight": relationship_weight,
            "evidence_strength": evidence_strength
        }
        
        # Define relative weights for present components
        weights = {
            "extractor_confidence": 0.3,
            "embedding_similarity": 0.25,
            "llm_validation_confidence": 0.20,
            "normalization_confidence": 0.10,
            "relationship_weight": 0.08,
            "evidence_strength": 0.07
        }
        
        total_weight = 0.0
        weighted_sum = 0.0
        
        for key, val in breakdown.items():
            if val is not None:
                w = weights.get(key, 0.1)
                total_weight += w
                weighted_sum += val * w
                
        final_score = round(weighted_sum / total_weight, 3) if total_weight > 0 else base_extractor_conf
        
        # Clamp between 0.0 and 1.0
        final_score = min(max(final_score, 0.0), 1.0)
        
        return {
            "final_score": final_score,
            "breakdown": {k: v for k, v in breakdown.items() if v is not None}
        }
