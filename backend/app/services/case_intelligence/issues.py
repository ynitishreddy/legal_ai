from typing import Dict, Any, List
from app.services.case_intelligence.confidence import ConfidenceScoringService

class IssueClassifier:
    # Classification keyword patterns
    CATEGORY_KEYWORDS = {
        "Constitutional": ["constitution", "fundamental rights", "article 21", "article 14", "article 32", "writ petition", "constitutional"],
        "Criminal": ["murder", "bail", "arrest", "police", "fir", "charge", "accused", "ipc", "trial", "offence", "penal code"],
        "Civil": ["injunction", "damages", "recovery", "suit", "performance", "plaintiff", "declaration", "civil"],
        "Corporate": ["shareholder", "company", "board", "director", "sebi", "shares", "corporate", "insolvency", "merger"],
        "Property": ["land", "lease", "possession", "title", "sale deed", "mortgage", "property", "tenant", "landlord"],
        "Taxation": ["income tax", "gst", "revenue", "customs", "taxation", "excise", "assessment", "tax"],
        "Family": ["divorce", "maintenance", "custody", "marriage", "succession", "partition", "wife", "family"],
        "Labor": ["workman", "gratuity", "dismissal", "industrial dispute", "wages", "labor", "employee", "employer"],
        "Environmental": ["pollution", "forest", "epa", "ngt", "environment", "waste", "factory"],
        "Procedural": ["limitation", "jurisdiction", "maintainability", "delay", "res judicata", "procedure", "procedural"],
        "Contract": ["agreement", "breach", "contract", "consideration", "indemnity", "guarantee"],
        "Tort": ["negligence", "defamation", "nuisance", "liability", "damages", "tort"],
        "Administrative": ["department", "tribunal", "discretion", "notification", "by-law", "authority", "administrative"]
    }

    def classify(self, issue_text: str) -> Dict[str, Any]:
        """
        Classifies legal issues into multi-label categories based on keyword mappings,
        computing category-specific confidence weights.
        """
        matched_labels = []
        text_lower = issue_text.lower()
        
        for category, keywords in self.CATEGORY_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                matched_labels.append(category)

        # Fallback category tag
        if not matched_labels:
            matched_labels = ["Procedural"] if "procedure" in text_lower or "jurisdiction" in text_lower else ["Civil"]

        # Scale confidence score dynamically by matching density
        base_conf = min(0.75 + (0.05 * len(matched_labels)), 0.98)
        score_res = ConfidenceScoringService.calculate_score(base_extractor_conf=base_conf)

        return {
            "labels": matched_labels,
            "primary_category": matched_labels[0],
            "confidence_score": score_res["final_score"],
            "confidence_breakdown": score_res["breakdown"]
        }
