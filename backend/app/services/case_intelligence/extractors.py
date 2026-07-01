import re
import uuid
from typing import List, Dict, Any
from app.services.case_intelligence.base import AbstractExtractor


class PartyExtractor(AbstractExtractor):
    def extract(self, chunk_text: str, metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
        results = []
        # Look for phrases like "plaintiff John Smith", "accused Nitish Reddy", "respondent State of Delhi"
        patterns = [
            r"\b(plaintiff|defendant|accused|petitioner|respondent|complainant|appellant)\s+([A-Z][a-zA-Z.]*(?:\s+[A-Z][a-zA-Z.]*)*)\b",
            r"\b([A-Z][a-zA-Z.]*(?:\s+[A-Z][a-zA-Z.]*)*)\s+(is\s+the\s+)(plaintiff|accused|petitioner|defendant|respondent)\b"
        ]
        
        for pat in patterns:
            for match in re.finditer(pat, chunk_text):
                if len(match.groups()) >= 2:
                    # Determine which group is role and name
                    g1, g2 = match.group(1), match.group(2)
                    if g1.lower() in ["plaintiff", "defendant", "accused", "petitioner", "respondent", "complainant", "appellant"]:
                        role = g1.lower()
                        name = g2.strip()
                    else:
                        role = match.group(3).lower()
                        name = g1.strip()
                        
                    results.append({
                        "name": name,
                        "normalized_name": name.upper(),
                        "role": role,
                        "confidence_score": 0.90
                    })
        return results


class JudgeExtractor(AbstractExtractor):
    def extract(self, chunk_text: str, metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
        results = []
        # E.g. "Hon'ble Judge Amit Sharma", "Justice Ramaswamy", "coram: J. Malhotra"
        patterns = [
            r"\b(?:[Hh]on'ble\s+)?(?:[Jj]udge|[Jj]ustice)\s+([A-Z][a-zA-Z.]*(?:\s+[A-Z][a-zA-Z.]*)*)\b",
            r"\b(?:[Cc]oram|[Bb]ench|[Jj]\.)\s+([A-Z][a-zA-Z.]*(?:\s+[A-Z][a-zA-Z.]*)*)\b"
        ]
        for pat in patterns:
            for match in re.finditer(pat, chunk_text):
                name = match.group(1).strip()
                results.append({
                    "name": name,
                    "normalized_name": name.upper(),
                    "role": "judge",
                    "confidence_score": 0.95
                })
        return results


class CourtExtractor(AbstractExtractor):
    def extract(self, chunk_text: str, metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
        results = []
        # E.g. "Delhi High Court", "Supreme Court of India"
        patterns = [
            r"\b([A-Z][a-zA-Z]*(?:\s+[A-Z][a-zA-Z]*)*\s+(?:High\s+Court|Supreme\s+Court|District\s+Court|Sessions\s+Court))\b"
        ]
        for pat in patterns:
            for match in re.finditer(pat, chunk_text):
                court_name = match.group(1).strip()
                results.append({
                    "name": court_name,
                    "normalized_name": court_name.upper(),
                    "role": "court",
                    "confidence_score": 0.95
                })
        return results


class IssueExtractor(AbstractExtractor):
    def extract(self, chunk_text: str, metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
        results = []
        # Look for "issue framed:", "question of law:", "whether the accused..."
        patterns = [
            r"\b(?:issue\s+framed|question\s+of\s+law|whether)\s+([^.!?]{10,150})\b"
        ]
        for pat in patterns:
            for match in re.finditer(pat, chunk_text, re.IGNORECASE):
                issue = match.group(1).strip()
                # Categorize
                category = "civil"
                if any(x in chunk_text.lower() for x in ["ipc", "criminal", "murder", "arrest", "accused"]):
                    category = "criminal"
                elif "constitutional" in chunk_text.lower():
                    category = "constitutional"
                elif "procedure" in chunk_text.lower() or "limitation" in chunk_text.lower():
                    category = "procedural"

                results.append({
                    "issue_text": f"Whether {issue}",
                    "issue_category": category,
                    "confidence_score": 0.85
                })
        return results


class ClaimExtractor(AbstractExtractor):
    def extract(self, chunk_text: str, metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
        results = []
        # E.g. "claimed a compensation", "sought relief of", "prays for stay order"
        patterns = [
            r"\b(?:claimed|sought|prays\s+for|relief\s+of)\s+([^.!?]{10,150})\b"
        ]
        for pat in patterns:
            for match in re.finditer(pat, chunk_text, re.IGNORECASE):
                claim = match.group(1).strip()
                results.append({
                    "type": "claim",
                    "statement": f"Sought {claim}",
                    "confidence_score": 0.88
                })
        return results


class DefenseExtractor(AbstractExtractor):
    def extract(self, chunk_text: str, metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
        results = []
        # E.g. "defendant disputed", "denied the allegations", "rebutted that"
        patterns = [
            r"\b(?:disputed|denied|rebutted|argued\s+that)\s+([^.!?]{10,150})\b"
        ]
        for pat in patterns:
            for match in re.finditer(pat, chunk_text, re.IGNORECASE):
                defense = match.group(1).strip()
                results.append({
                    "type": "defense",
                    "statement": f"Disputed/Rebutted {defense}",
                    "confidence_score": 0.82
                })
        return results


class EvidenceExtractor(AbstractExtractor):
    def extract(self, chunk_text: str, metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
        results = []
        # E.g. "exhibit PW-1/A", "testified that", "electronic record of"
        patterns = [
            r"\b(exhibit\s+[a-zA-Z0-9/-]{1,15})\b",
            r"\b(witness\s+testified\s+that\s+[^.!?]{10,100})\b",
            r"\b(forensic\s+report\s+of\s+[^.!?]{10,100})\b"
        ]
        for pat in patterns:
            for match in re.finditer(pat, chunk_text, re.IGNORECASE):
                ev_text = match.group(1).strip()
                ev_type = "exhibit"
                if "testified" in ev_text.lower():
                    ev_type = "witness_testimony"
                elif "forensic" in ev_text.lower():
                    ev_type = "forensic"

                results.append({
                    "evidence_type": ev_type,
                    "description": ev_text,
                    "confidence_score": 0.90
                })
        return results


class WitnessExtractor(AbstractExtractor):
    def extract(self, chunk_text: str, metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
        results = []
        # E.g. "witness PW-1 Nitish Kumar", "witness examined: Dr. Sharma"
        patterns = [
            r"\b(?:witness|examined|deposition\s+of)\s+(?:PW-\d+\s+)?([A-Z][a-zA-Z.]*(?:\s+[A-Z][a-zA-Z.]*)*)\b"
        ]
        for pat in patterns:
            for match in re.finditer(pat, chunk_text, re.IGNORECASE):
                name = match.group(1).strip()
                results.append({
                    "name": name,
                    "normalized_name": name.upper(),
                    "role": "witness",
                    "confidence_score": 0.85
                })
        return results


class StatuteExtractor(AbstractExtractor):
    def extract(self, chunk_text: str, metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
        results = []
        # E.g. "Section 302 of the IPC", "Article 21 of Constitution"
        patterns = [
            r"\b(Section|Sec\.|Article|Art\.)\s+(\d+[A-Za-z]*)\s+(?:of\s+)?(?:the\s+)?([A-Z][a-zA-Z]*(?:\s+[A-Z][a-zA-Z]*)*)\b"
        ]
        for pat in patterns:
            for match in re.finditer(pat, chunk_text):
                ref_type = match.group(1)
                sec = match.group(2).strip()
                act = match.group(3).strip()
                results.append({
                    "act_name": act,
                    "section_reference": f"{ref_type} {sec}",
                    "normalized_reference": f"{act}, {ref_type} {sec}",
                    "confidence_score": 0.95
                })
        return results
