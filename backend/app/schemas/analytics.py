import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional
from pydantic import BaseModel

class MetricCard(BaseModel):
    name: str
    value: Any
    unit: Optional[str] = None
    change_percent: Optional[float] = None
    trend: Optional[str] = None # 'up', 'down', 'neutral'

class ChartDataPoint(BaseModel):
    label: str
    value: float

class KeyValuePair(BaseModel):
    label: str
    value: Any

class CaseAnalyticsResponse(BaseModel):
    metrics: List[MetricCard]
    cases_by_status: List[ChartDataPoint]
    cases_by_court: List[ChartDataPoint]
    cases_by_jurisdiction: List[ChartDataPoint]
    cases_by_category: List[ChartDataPoint]
    cases_by_advocate: List[ChartDataPoint]
    cases_by_judge: List[ChartDataPoint]
    case_growth_trend: List[ChartDataPoint]
    completion_rate: float

class DocumentAnalyticsResponse(BaseModel):
    metrics: List[MetricCard]
    documents_by_case: List[ChartDataPoint]
    documents_by_type: List[ChartDataPoint]
    file_size_distribution: List[ChartDataPoint]
    processing_success_rates: List[ChartDataPoint]
    upload_trends: List[ChartDataPoint]
    largest_documents: List[KeyValuePair]

class ProcessingAnalyticsResponse(BaseModel):
    metrics: List[MetricCard]
    stage_durations: List[ChartDataPoint]
    failures_by_stage: List[ChartDataPoint]
    worker_utilization: List[ChartDataPoint]
    success_rate: float

class EmbeddingAnalyticsResponse(BaseModel):
    metrics: List[MetricCard]
    embeddings_by_document: List[ChartDataPoint]
    embedding_durations: List[ChartDataPoint]
    embedding_growth: List[ChartDataPoint]

class VectorDbAnalyticsResponse(BaseModel):
    metrics: List[MetricCard]
    collection_stats: List[KeyValuePair]
    sync_status: List[ChartDataPoint]
    sync_failures: List[KeyValuePair]

class RetrievalAnalyticsResponse(BaseModel):
    metrics: List[MetricCard]
    latency_distribution: List[ChartDataPoint]
    score_distribution: List[ChartDataPoint]
    top_retrieved_documents: List[KeyValuePair]
    query_categories: List[ChartDataPoint]
    compression_ratios: List[ChartDataPoint]

class ConversationAnalyticsResponse(BaseModel):
    metrics: List[MetricCard]
    messages_distribution: List[ChartDataPoint]
    session_durations: List[ChartDataPoint]
    chat_growth: List[ChartDataPoint]

class LlmAnalyticsResponse(BaseModel):
    metrics: List[MetricCard]
    requests_by_provider: List[ChartDataPoint]
    latency_by_provider: List[ChartDataPoint]
    success_rates: List[ChartDataPoint]
    health_status: List[KeyValuePair]

class TokenAnalyticsResponse(BaseModel):
    metrics: List[MetricCard]
    tokens_by_provider: List[ChartDataPoint]
    tokens_by_case: List[ChartDataPoint]
    tokens_by_user: List[ChartDataPoint]
    token_growth_trend: List[ChartDataPoint]

class CostAnalyticsResponse(BaseModel):
    metrics: List[MetricCard]
    cost_by_provider: List[ChartDataPoint]
    cost_by_case: List[ChartDataPoint]
    cost_by_user: List[ChartDataPoint]
    daily_spend_trend: List[ChartDataPoint]
    monthly_projected: float

class CitationAnalyticsResponse(BaseModel):
    metrics: List[MetricCard]
    citations_by_document: List[ChartDataPoint]
    citation_accuracy_distribution: List[ChartDataPoint]

class TimelineAnalyticsResponse(BaseModel):
    metrics: List[MetricCard]
    events_by_case: List[ChartDataPoint]
    event_categories: List[ChartDataPoint]
    missing_dates_rate: float

class CaseIntelligenceAnalyticsResponse(BaseModel):
    metrics: List[MetricCard]
    extracted_items_by_case: List[ChartDataPoint]
    evidence_strength_distribution: List[ChartDataPoint]

class KnowledgeGraphAnalyticsResponse(BaseModel):
    metrics: List[MetricCard]
    relationship_types_distribution: List[ChartDataPoint]
    centrality_rankings: List[KeyValuePair]

class AiQualityAnalyticsResponse(BaseModel):
    metrics: List[MetricCard]
    confidence_distribution: List[ChartDataPoint]
    low_confidence_entities: List[KeyValuePair]

class AnalyticsOverviewResponse(BaseModel):
    metrics: List[MetricCard]
    charts: List[Any]
    summary: Dict[str, Any]
