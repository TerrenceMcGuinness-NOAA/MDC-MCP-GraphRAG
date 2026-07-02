#!/usr/bin/env python3
"""
Hard Negative Miner — Use Neptune graph structure to generate training triples

Finds entity pairs that are 1-hop apart in the graph but belong to different
functional domains, providing challenging negative examples for fine-tuning.
"""

import argparse
import json
import sys
from dataclasses import dataclass
from typing import List, Tuple


@dataclass
class Triple:
    anchor: str
    positive: str
    hard_negative: str


class HardNegativeMiner:
    """Uses Neptune graph structure to generate training triples."""
    
    def __init__(self, graph_driver):
        self.graph_driver = graph_driver
    
    def mine(self, collection_name: str, max_triples: int = 1000) -> List[Triple]:
        """
        Find entity pairs that are 1-hop apart in graph but belong to
        different functional domains.
        
        Args:
            collection_name: Collection to mine triples from
            max_triples: Maximum number of triples to generate
        
        Returns:
            List of (anchor, positive, hard_negative) triples
        """
        triples = []
        
        # Query graph for entities with relationships
        query = """
        MATCH (anchor)-[r1:CALLS|USES|IMPORTS]->(positive)
        MATCH (anchor)-[r2:CALLS|USES|IMPORTS]->(hard_neg)
        WHERE positive.community <> hard_neg.community
        AND positive <> hard_neg
        RETURN anchor.content AS anchor_text,
               positive.content AS positive_text,
               hard_neg.content AS negative_text
        LIMIT $max_triples
        """
        
        # Placeholder: would execute against Neptune/Neo4j
        # For now, return empty list
        return triples
    
    def _compute_graph_distance(self, node1_id: str, node2_id: str) -> int:
        """Compute shortest path distance between two nodes."""
        query = """
        MATCH path = shortestPath((n1)-[*]-(n2))
        WHERE id(n1) = $node1_id AND id(n2) = $node2_id
        RETURN length(path) AS distance
        """
        # Placeholder
        return 1
    
    def export_for_sentence_transformers(self, triples: List[Triple], output_path: str):
        """Export triples in Sentence Transformers training format."""
        data = [
            {
                'anchor': t.anchor,
                'positive': t.positive,
                'negative': t.hard_negative
            }
            for t in triples
        ]
        
        with open(output_path, 'w') as f:
            for item in data:
                f.write(json.dumps(item) + '\n')
        
        print(f"[OK] Exported {len(triples)} triples to {output_path}")


def main():
    parser = argparse.ArgumentParser(description='Mine hard negatives from graph')
    parser.add_argument('collection', help='Collection name')
    parser.add_argument('--output', required=True, help='Output JSONL file')
    parser.add_argument('--max-triples', type=int, default=1000)
    parser.add_argument('--backend', default='aws', choices=['aws', 'cots', 'legacy'])
    
    args = parser.parse_args()

    # Phase 63a deprecation shim: --backend=legacy is auto-mapped to cots.
    if args.backend == 'legacy':
        print(
            "[WARN] --backend=legacy is deprecated; "
            "use --backend=cots (auto-mapped)",
            file=sys.stderr,
        )
        args.backend = 'cots'
    
    # Placeholder: would connect to Neptune/Neo4j
    graph_driver = None
    
    miner = HardNegativeMiner(graph_driver)
    triples = miner.mine(args.collection, max_triples=args.max_triples)
    
    if triples:
        miner.export_for_sentence_transformers(triples, args.output)
        print(f"[OK] Mined {len(triples)} hard negative triples")
    else:
        print("[WARN] No triples generated (graph driver not connected)", file=sys.stderr)


if __name__ == '__main__':
    main()
