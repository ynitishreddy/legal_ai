import uuid
import logging
from typing import List, Dict, Any, Optional
from collections import deque
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.models import LegalEntity, ClaimDefense, LegalEvidence, ActStatute, EntityRelationship

logger = logging.getLogger(__name__)

class KnowledgeGraphQueryService:
    def __init__(self, db: Session):
        self.db = db

    def get_neighbors(self, case_id: uuid.UUID, node_id: uuid.UUID) -> Dict[str, Any]:
        """
        Retrieves all connected edges and neighbor nodes directly linked to node_id.
        """
        # Fetch relationships involving this node
        relationships = (
            self.db.query(EntityRelationship)
            .filter(
                and_(
                    EntityRelationship.case_id == case_id,
                    (EntityRelationship.source_id == node_id) | (EntityRelationship.target_id == node_id)
                )
            )
            .all()
        )

        neighbor_ids = set()
        for rel in relationships:
            neighbor_ids.add(rel.source_id)
            neighbor_ids.add(rel.target_id)
        
        # Remove self
        neighbor_ids.discard(node_id)
        
        # Fetch target nodes context details
        nodes_details = self._fetch_nodes_details(case_id, list(neighbor_ids))

        return {
            "node_id": str(node_id),
            "relationships": [
                {
                    "id": str(r.id),
                    "source": str(r.source_id),
                    "target": str(r.target_id),
                    "type": r.relationship_type,
                    "confidence": r.confidence_score
                } for r in relationships
            ],
            "connected_nodes": nodes_details
        }

    def find_shortest_path(self, case_id: uuid.UUID, start_node_id: uuid.UUID, end_node_id: uuid.UUID) -> List[Dict[str, Any]]:
        """
        Performs a Breadth-First Search (BFS) graph traversal to identify
        the shortest path of nodes and edges connecting start_node_id and end_node_id.
        """
        if start_node_id == end_node_id:
            return [{"node_id": str(start_node_id), "type": "node", "label": "Self"}]

        # Load all relationships for case to construct adjacency lists
        relationships = (
            self.db.query(EntityRelationship)
            .filter(EntityRelationship.case_id == case_id)
            .all()
        )

        adj = {}
        for rel in relationships:
            s, t = rel.source_id, rel.target_id
            if s not in adj: adj[s] = []
            if t not in adj: adj[t] = []
            adj[s].append((t, rel))
            adj[t].append((s, rel))

        if start_node_id not in adj or end_node_id not in adj:
            return []

        # BFS Queue holds: (current_node_id, path_taken_as_list_of_steps)
        queue = deque([(start_node_id, [])])
        visited = {start_node_id}

        while queue:
            curr, path = queue.popleft()

            if curr == end_node_id:
                # Return resolved path objects
                resolved_path = []
                # First node
                resolved_path.append(self._fetch_node_info(case_id, start_node_id))
                for step in path:
                    edge = step["edge"]
                    nxt_node = step["node"]
                    resolved_path.append({
                        "type": "relationship",
                        "relationship_id": str(edge.id),
                        "relationship_type": edge.relationship_type,
                        "confidence": edge.confidence_score
                    })
                    resolved_path.append(self._fetch_node_info(case_id, nxt_node))
                return resolved_path

            for neighbor, edge in adj.get(curr, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    new_path = path + [{"edge": edge, "node": neighbor}]
                    queue.append((neighbor, new_path))

        return []

    def get_centrality_metrics(self, case_id: uuid.UUID) -> List[Dict[str, Any]]:
        """
        Computes degree centrality metric ranking (number of connected edges)
        for all resolved nodes in the case knowledge graph.
        """
        relationships = (
            self.db.query(EntityRelationship)
            .filter(EntityRelationship.case_id == case_id)
            .all()
        )

        degree_map = {}
        for rel in relationships:
            degree_map[rel.source_id] = degree_map.get(rel.source_id, 0) + 1
            degree_map[rel.target_id] = degree_map.get(rel.target_id, 0) + 1

        sorted_degrees = sorted(degree_map.items(), key=lambda x: x[1], reverse=True)
        
        node_ids = [item[0] for item in sorted_degrees[:20]]
        nodes_details = {str(n["id"]): n for n in self._fetch_nodes_details(case_id, node_ids)}

        metrics = []
        for n_id, deg in sorted_degrees[:20]:
            info = nodes_details.get(str(n_id), {"label": "Unknown", "type": "unknown"})
            metrics.append({
                "node_id": str(n_id),
                "label": info["label"],
                "type": info["type"],
                "degree_centrality": deg
            })

        return metrics

    def _fetch_nodes_details(self, case_id: uuid.UUID, node_ids: List[uuid.UUID]) -> List[Dict[str, Any]]:
        """Utility helper gathering labels and type attributes for multiple arbitrary UUIDs."""
        if not node_ids:
            return []
        
        details = []

        # 1. Check LegalEntity
        entities = self.db.query(LegalEntity).filter(
            and_(LegalEntity.case_id == case_id, LegalEntity.id.in_(node_ids))
        ).all()
        for e in entities:
            details.append({"id": str(e.id), "type": e.entity_type, "label": e.name})

        # 2. Check ClaimDefense
        claims = self.db.query(ClaimDefense).filter(
            and_(ClaimDefense.case_id == case_id, ClaimDefense.id.in_(node_ids))
        ).all()
        for cl in claims:
            details.append({"id": str(cl.id), "type": cl.type, "label": cl.statement[:40] + "..."})

        # 3. Check LegalEvidence
        evidence = self.db.query(LegalEvidence).filter(
            and_(LegalEvidence.case_id == case_id, LegalEvidence.id.in_(node_ids))
        ).all()
        for ev in evidence:
            details.append({"id": str(ev.id), "type": "evidence", "label": ev.description[:40] + "..."})

        # 4. Check ActStatute
        acts = self.db.query(ActStatute).filter(
            and_(ActStatute.case_id == case_id, ActStatute.id.in_(node_ids))
        ).all()
        for act in acts:
            details.append({"id": str(act.id), "type": "statute", "label": act.normalized_reference})

        return details

    def _fetch_node_info(self, case_id: uuid.UUID, node_id: uuid.UUID) -> Dict[str, Any]:
        """Resolves label and details for a single node."""
        res = self._fetch_nodes_details(case_id, [node_id])
        if res:
            return {"type": "node", "node_id": res[0]["id"], "node_type": res[0]["type"], "label": res[0]["label"]}
        return {"type": "node", "node_id": str(node_id), "node_type": "unknown", "label": "Unknown Node"}
