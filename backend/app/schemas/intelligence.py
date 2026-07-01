import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional
from pydantic import BaseModel


class LegalFactResponse(BaseModel):
    id: uuid.UUID
    case_id: uuid.UUID
    document_id: Optional[uuid.UUID]
    chunk_id: Optional[str]
    fact_text: str
    confidence_score: float
    citation_source: Optional[str]
    extraction_method: str
    created_at: datetime
    
    # Extensions
    category: str
    importance_score: float
    processing_version: str
    supporting_citations: Optional[str]
    confidence_breakdown: Optional[str]

    class Config:
        from_attributes = True


class LegalEntityResponse(BaseModel):
    id: uuid.UUID
    case_id: uuid.UUID
    document_id: Optional[uuid.UUID]
    entity_type: str
    name: str
    normalized_name: str
    aliases: Optional[str]
    role: Optional[str]
    confidence_score: float
    created_at: datetime

    # Extensions
    canonical_id: Optional[uuid.UUID]
    resolution_status: str
    similarity_score: Optional[float]
    merge_metadata: Optional[str]
    confidence_breakdown: Optional[str]

    class Config:
        from_attributes = True


class LegalIssueResponse(BaseModel):
    id: uuid.UUID
    case_id: uuid.UUID
    document_id: Optional[uuid.UUID]
    issue_text: str
    issue_category: str
    confidence_score: float
    created_at: datetime

    # Extensions
    labels: Optional[str]
    confidence_breakdown: Optional[str]

    class Config:
        from_attributes = True


class ClaimDefenseResponse(BaseModel):
    id: uuid.UUID
    case_id: uuid.UUID
    document_id: Optional[uuid.UUID]
    type: str
    statement: str
    confidence_score: float
    created_at: datetime

    # Extensions
    confidence_breakdown: Optional[str]

    class Config:
        from_attributes = True


class LegalEvidenceResponse(BaseModel):
    id: uuid.UUID
    case_id: uuid.UUID
    document_id: Optional[uuid.UUID]
    evidence_type: str
    description: str
    confidence_score: float
    created_at: datetime

    # Extensions
    strength_score: float
    confidence_breakdown: Optional[str]

    class Config:
        from_attributes = True


class ActStatuteResponse(BaseModel):
    id: uuid.UUID
    case_id: uuid.UUID
    document_id: Optional[uuid.UUID]
    act_name: str
    section_reference: Optional[str]
    normalized_reference: str
    confidence_score: float
    created_at: datetime

    # Extensions
    parent_id: Optional[uuid.UUID]
    aliases: Optional[str]
    confidence_breakdown: Optional[str]

    class Config:
        from_attributes = True


class GraphNode(BaseModel):
    id: str
    type: str
    label: str
    details: Dict[str, Any]


class GraphLink(BaseModel):
    id: str
    source: str
    target: str
    type: str
    confidence: float
    details: Optional[Dict[str, Any]] = None


class KnowledgeGraphResponse(BaseModel):
    nodes: List[GraphNode]
    links: List[GraphLink]


class CaseIntelligenceStatsResponse(BaseModel):
    facts_count: int
    entities_count: int
    issues_count: int
    claims_count: int
    evidence_count: int
    statutes_count: int


class ExtractionTriggerRequest(BaseModel):
    case_id: uuid.UUID
    document_id: uuid.UUID


# Phase 8.2 (v1.5.1) — Graph Query Responses
class NeighborNodeInfo(BaseModel):
    id: str
    type: str
    label: str

class NeighborLinkInfo(BaseModel):
    id: str
    source: str
    target: str
    type: str
    confidence: float

class GraphNeighborsResponse(BaseModel):
    node_id: str
    relationships: List[NeighborLinkInfo]
    connected_nodes: List[NeighborNodeInfo]


class PathStep(BaseModel):
    type: str  # 'node' or 'relationship'
    node_id: Optional[str] = None
    node_type: Optional[str] = None
    label: Optional[str] = None
    relationship_id: Optional[str] = None
    relationship_type: Optional[str] = None
    confidence: Optional[float] = None


class CentralityMetric(BaseModel):
    node_id: str
    label: str
    type: str
    degree_centrality: int


class GraphAnalyticsResponse(BaseModel):
    case_id: uuid.UUID
    total_nodes: int
    total_edges: int
    centrality_ranking: List[CentralityMetric]
