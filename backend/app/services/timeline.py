import re
import uuid
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc, func

from app.models import TimelineEvent, EventRelationship, Document, Case
from app.document_processing.models import DocumentChunk

logger = logging.getLogger(__name__)


class TimelineIntelligenceService:
    """
    Service layer providing legal event extractions, date normalizations,
    duplication merging, and event relational linking logic.
    """
    def __init__(self, db: Session) -> None:
        self.db = db

    def extract_document_events(self, case_id: uuid.UUID, document_id: uuid.UUID) -> List[TimelineEvent]:
        """
        Parses document chunks to extract and save legally significant events.
        """
        # Fetch chunks
        chunks = (
            self.db.query(DocumentChunk)
            .filter(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index.asc())
            .all()
        )
        if not chunks:
            logger.warning("TimelineService: No chunks found for document %s", document_id)
            return []

        # Extensible category patterns mapping keywords to event categories
        category_patterns = {
            "criminal": [r"\b(fir|arrest|charge\ssheet|charge-sheet|bail|police|accused|custody|witness)\b"],
            "civil": [r"\b(suit|contract|lease|breach|agreement|settlement|decree|covenant|partition)\b"],
            "court": [r"\b(hearing|adjourn|stay\sorder|interim|stay|decree|appeal|review|petition|judgment)\b"],
        }

        extracted_events = []

        # Heuristic extraction
        for chunk in chunks:
            text = chunk.chunk_text
            
            # Simple sentence splitting
            sentences = re.split(r"(?<=[.!?])\s+", text)
            for idx, sentence in enumerate(sentences):
                # Look for date patterns (e.g. DD/MM/YYYY or YYYY-MM-DD or Month DD, YYYY)
                date_match = re.search(
                    r"\b(\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}|\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|"
                    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4})\b",
                    sentence,
                    re.IGNORECASE
                )
                if date_match:
                    orig_date = date_match.group(1)
                    norm_dt = self.normalize_event_date(orig_date)
                    if not norm_dt:
                        continue

                    # Determine category
                    event_cat = "general"
                    lower_sentence = sentence.lower()
                    for cat, patterns in category_patterns.items():
                        if any(re.search(pat, lower_sentence) for pat in patterns):
                            event_cat = cat
                            break

                    # Synthesize title and description
                    words = sentence.split()
                    title = " ".join(words[:6]) + "..." if len(words) > 6 else sentence
                    desc = sentence.strip()

                    # Save new event record
                    event = TimelineEvent(
                        case_id=case_id,
                        document_id=document_id,
                        title=title,
                        description=desc,
                        event_date=norm_dt,
                        event_type=event_cat,
                        event_title=title,
                        event_description=desc,
                        normalized_date=norm_dt,
                        original_date=orig_date,
                        confidence_score=0.85,
                        page_number=chunk.page_start,
                        chunk_id=str(chunk.id),
                        source_text=sentence.strip()
                    )
                    self.db.add(event)
                    extracted_events.append(event)

        self.db.commit()
        
        # Merge duplicates and establish links
        self.merge_duplicate_events(case_id)
        self.link_related_events(case_id)
        
        return extracted_events

    def normalize_event_date(self, date_str: str) -> Optional[datetime]:
        """
        Parses multiple date formats (partial/ocr-corrupted) into timezone-aware datetimes.
        """
        clean_str = re.sub(r"\s+", " ", date_str.strip())
        
        # Format 1: DD/MM/YYYY or DD-MM-YYYY
        match1 = re.match(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})", clean_str)
        if match1:
            day, month, year = int(match1.group(1)), int(match1.group(2)), int(match1.group(3))
            if year < 100:
                year += 2000
            try:
                return datetime(year, month, day, tzinfo=timezone.utc)
            except ValueError:
                pass

        # Format 2: YYYY-MM-DD
        match2 = re.match(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", clean_str)
        if match2:
            year, month, day = int(match2.group(1)), int(match2.group(2)), int(match2.group(3))
            try:
                return datetime(year, month, day, tzinfo=timezone.utc)
            except ValueError:
                pass

        # Format 3: Month DD, YYYY (e.g. October 15, 2023)
        months_map = {
            "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
            "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12
        }
        match3 = re.match(r"([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})", clean_str)
        if match3:
            m_name, day, year = match3.group(1).lower()[:3], int(match3.group(2)), int(match3.group(3))
            month = months_map.get(m_name, 1)
            try:
                return datetime(year, month, day, tzinfo=timezone.utc)
            except ValueError:
                pass

        return None

    def merge_duplicate_events(self, case_id: uuid.UUID) -> None:
        """
        Merges duplicate events occurring on the same normalized date with overlapping titles.
        """
        # Fetch events for the case ordered by date
        events = (
            self.db.query(TimelineEvent)
            .filter(TimelineEvent.case_id == case_id)
            .order_by(TimelineEvent.normalized_date.asc())
            .all()
        )
        
        # Deduplication scan
        seen = {}
        for event in events:
            # Group keys by date + first 3 words of title
            date_key = event.normalized_date.date() if event.normalized_date else None
            if not date_key:
                continue

            words = (event.event_title or event.title).lower().split()
            title_key = " ".join(words[:2]) if len(words) >= 2 else "".join(words)
            group_key = (date_key, title_key)

            if group_key in seen:
                # Merge: Keep the earlier one, link or remove the newer duplicate
                duplicate = seen[group_key]
                # Merge descriptions
                if event.event_description and event.event_description not in duplicate.event_description:
                    duplicate.event_description += f"\nNote: {event.event_description}"
                
                # Delete duplicate event
                self.db.delete(event)
                logger.info("TimelineService: Merged duplicate event title: %s", event.title)
            else:
                seen[group_key] = event

        self.db.commit()

    def link_related_events(self, case_id: uuid.UUID) -> None:
        """
        Heuristically link logical sequential events: Suit -> Hearing -> Judgment.
        """
        # Fetch all remaining events
        events = (
            self.db.query(TimelineEvent)
            .filter(TimelineEvent.case_id == case_id)
            .order_by(TimelineEvent.normalized_date.asc())
            .all()
        )

        # Clear old relationships to avoid duplicates
        self.db.query(EventRelationship).filter(
            EventRelationship.parent_event_id.in_([e.id for e in events])
        ).delete(synchronize_session=False)

        # Linking heuristic based on sequential stages
        for i in range(len(events) - 1):
            e_parent = events[i]
            e_child = events[i+1]

            # Connect hearing -> order/stay or notice -> hearing
            p_type = e_parent.event_type
            c_type = e_child.event_type
            
            # Simple link if within 60 days
            delta = e_child.normalized_date - e_parent.normalized_date
            if delta <= timedelta(days=60):
                rel = EventRelationship(
                    parent_event_id=e_parent.id,
                    child_event_id=e_child.id,
                    relationship_type="sequential_stage"
                )
                self.db.add(rel)

        self.db.commit()

    def get_case_timeline(
        self,
        case_id: uuid.UUID,
        event_type: Optional[str] = None,
        min_confidence: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        """Returns ordered timeline events with their children/parent relationships mapped."""
        query = (
            self.db.query(TimelineEvent)
            .filter(TimelineEvent.case_id == case_id)
        )
        if event_type:
            query = query.filter(TimelineEvent.event_type == event_type)
        if min_confidence is not None:
            query = query.filter(TimelineEvent.confidence_score >= min_confidence)
            
        events = query.order_by(TimelineEvent.normalized_date.asc()).all()

        results = []
        for e in events:
            # Map children links
            children = (
                self.db.query(EventRelationship)
                .filter(EventRelationship.parent_event_id == e.id)
                .all()
            )
            child_ids = [str(r.child_event_id) for r in children]

            results.append({
                "id": str(e.id),
                "case_id": str(e.case_id),
                "document_id": str(e.document_id) if e.document_id else None,
                "event_type": e.event_type,
                "event_title": e.event_title or e.title,
                "event_description": e.event_description or e.description,
                "normalized_date": e.normalized_date.isoformat() if e.normalized_date else None,
                "original_date": e.original_date or str(e.event_date),
                "confidence_score": e.confidence_score or 1.0,
                "page_number": e.page_number,
                "chunk_id": e.chunk_id,
                "source_text": e.source_text,
                "linked_child_events": child_ids,
            })
        return results

    def rebuild_case_timeline(self, case_id: uuid.UUID) -> None:
        """Deletes and rebuilds case timeline events across all documents."""
        # 1. Delete existing timeline events
        self.db.query(TimelineEvent).filter(TimelineEvent.case_id == case_id).delete()
        self.db.commit()

        # 2. Query documents
        documents = self.db.query(Document).filter(Document.case_id == case_id).all()
        for doc in documents:
            self.extract_document_events(case_id, doc.id)

    def get_timeline_statistics(self, case_id: uuid.UUID) -> Dict[str, Any]:
        """Calculates statistical aggregates for case timeline insights."""
        events = self.db.query(TimelineEvent).filter(TimelineEvent.case_id == case_id).all()
        if not events:
            return {
                "total_events": 0,
                "category_breakdown": {},
                "average_confidence": 0.0,
                "timeline_span_days": 0,
            }

        counts = {}
        total_conf = 0.0
        dates = []
        for e in events:
            cat = e.event_type or "general"
            counts[cat] = counts.get(cat, 0) + 1
            total_conf += (e.confidence_score or 1.0)
            if e.normalized_date:
                dates.append(e.normalized_date)

        span = 0
        if len(dates) >= 2:
            span = (max(dates) - min(dates)).days

        return {
            "total_events": len(events),
            "category_breakdown": counts,
            "average_confidence": round(total_conf / len(events), 2),
            "timeline_span_days": span,
        }
