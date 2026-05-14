#!/usr/bin/env python3
"""
Test script to compare search modes for the semantic layer agent.

Usage:
    python test_search_modes.py "your question here"

This will run assess_knowledge with different SEARCH_MODE values and compare results.
"""

import os
import sys
import json
from typing import Dict, Any

# Add current directory to path
sys.path.insert(0, os.path.dirname(__file__))

def test_search_modes(question: str) -> Dict[str, Any]:
    """Test assess_knowledge with different search modes."""
    results = {}
    
    # Test current mode
    os.environ["SEARCH_MODE"] = "current"
    try:
        # Need to reload the module to pick up env var change
        if 'agent' in sys.modules:
            del sys.modules['agent']
        import agent
        result = agent.assess_knowledge(question)
        results["current"] = {
            "status": result.get("status"),
            "coverage_score": result.get("coverage_score"),
            "matched_tables_count": len(result.get("matched_tables", [])),
            "matched_kpis_count": len(result.get("matched_kpis", [])),
            "matched_concepts_count": len(result.get("matched_concepts", [])),
            "matched_examples_count": len(result.get("matched_examples", [])),
        }
        print(f"Current mode: {result.get('status')} ({result.get('coverage_score'):.2%})")
    except Exception as e:
        results["current"] = {"error": str(e)}
        print(f"Current mode failed: {e}")
    
    # Test neo4j_only mode
    os.environ["SEARCH_MODE"] = "neo4j_only"
    try:
        # Reload module
        if 'agent' in sys.modules:
            del sys.modules['agent']
        import agent
        result = agent.assess_knowledge(question)
        results["neo4j_only"] = {
            "status": result.get("status"),
            "coverage_score": result.get("coverage_score"),
            "matched_tables_count": len(result.get("matched_tables", [])),
            "matched_kpis_count": len(result.get("matched_kpis", [])),
            "matched_concepts_count": len(result.get("matched_concepts", [])),
            "matched_examples_count": len(result.get("matched_examples", [])),
        }
        print(f"Neo4j-only mode: {result.get('status')} ({result.get('coverage_score'):.2%})")
    except Exception as e:
        results["neo4j_only"] = {"error": str(e)}
        print(f"Neo4j-only mode failed: {e}")
    
    # Test ontology_vector mode (same as current for now)
    os.environ["SEARCH_MODE"] = "ontology_vector"
    try:
        if 'agent' in sys.modules:
            del sys.modules['agent']
        import agent
        result = agent.assess_knowledge(question)
        results["ontology_vector"] = {
            "status": result.get("status"),
            "coverage_score": result.get("coverage_score"),
            "matched_tables_count": len(result.get("matched_tables", [])),
            "matched_kpis_count": len(result.get("matched_kpis", [])),
            "matched_concepts_count": len(result.get("matched_concepts", [])),
            "matched_examples_count": len(result.get("matched_examples", [])),
        }
        print(f"Ontology-vector mode: {result.get('status')} ({result.get('coverage_score'):.2%})")
    except Exception as e:
        results["ontology_vector"] = {"error": str(e)}
        print(f"Ontology-vector mode failed: {e}")
    
    return results

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_search_modes.py 'your question here'")
        sys.exit(1)
    
    question = sys.argv[1]
    print(f"Testing question: {question}")
    print("=" * 50)
    
    results = test_search_modes(question)
    
    print("\n" + "=" * 50)
    print("SUMMARY:")
    for mode, data in results.items():
        if "error" in data:
            print(f"{mode}: ERROR - {data['error']}")
        else:
            print(f"{mode}: {data['status']} ({data['coverage_score']:.2%}) - Tables: {data['matched_tables_count']}, KPIs: {data['matched_kpis_count']}, Concepts: {data['matched_concepts_count']}, Examples: {data['matched_examples_count']}")
    
    # Save detailed results
    with open("search_mode_comparison.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\nDetailed results saved to search_mode_comparison.json")