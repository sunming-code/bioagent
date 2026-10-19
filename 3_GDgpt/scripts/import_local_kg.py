"""Import the shipped Task KG with batched, repeatable Neo4j driver queries."""
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from neo4j import GraphDatabase
from utils import load_config


def main():
    cfg = load_config()
    base = ROOT / "kg_build/task_kg_output"
    summary = json.loads((base / "task_kg_summary.json").read_text())
    expected = (summary["node_count"], summary["edge_count"])
    nodes, edges = defaultdict(list), defaultdict(list)
    for filename, groups, field in (
        ("task_kg_nodes.csv", nodes, "type"),
        ("task_kg_edges.csv", edges, "relation_group"),
    ):
        with (base / filename).open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                name = row[field]
                if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", name):
                    raise ValueError("Invalid graph label or relationship type")
                groups[name].append(row)
    with GraphDatabase.driver(cfg["neo4j_uri"], auth=(cfg["neo4j_user"], cfg["neo4j_password"])) as driver:
        driver.verify_connectivity()
        with driver.session(database=cfg["neo4j_database"] or "neo4j") as session:
            def counts():
                n = session.run("MATCH (n) RETURN count(n) AS n").single()["n"]
                e = session.run("MATCH ()-[r]->() RETURN count(r) AS n").single()["n"]
                return n, e

            before = counts()
            if before == expected:
                print(f"KG already loaded: {before[0]} nodes / {before[1]} edges")
                return
            # This helper owns a dedicated local DB. Refuse to mix an unknown
            # graph into it; partial imports of the same CSV remain repeatable.
            ids = {r["id"] for rows in nodes.values() for r in rows}
            existing = {r["id"] for r in session.run("MATCH (n) RETURN n.id AS id")}
            if not existing.issubset(ids):
                raise RuntimeError("Database contains unrelated nodes; import stopped")
            for label, rows in nodes.items():
                session.run(f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.id IS UNIQUE").consume()
                session.run(f"CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.name)").consume()
                session.run(f"CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.normalized_name)").consume()
                for start in range(0, len(rows), 1000):
                    session.run(f"UNWIND $rows AS row MERGE (n:{label} {{id: row.id}}) SET n += row", rows=rows[start:start+1000]).consume()
                print(f"Nodes {label}: {len(rows)}", flush=True)
            for relation, rows in edges.items():
                # Match endpoints by their indexed labels as well as IDs.
                by_labels = defaultdict(list)
                for row in rows:
                    by_labels[(row["source_type"], row["target_type"])].append(row)
                for (source, target), subset in by_labels.items():
                    if source not in nodes or target not in nodes:
                        raise ValueError("Unknown endpoint type")
                    query = (
                        f"UNWIND $rows AS row MATCH (s:{source} {{id: row.source_id}}) "
                        f"MATCH (t:{target} {{id: row.target_id}}) "
                        f"MERGE (s)-[r:{relation} {{relation_raw: row.relation_raw}}]->(t) "
                        "SET r += row"
                    )
                    for start in range(0, len(subset), 1000):
                        session.run(query, rows=subset[start:start+1000]).consume()
                print(f"Edges {relation}: {len(rows)}", flush=True)
            actual = counts()
            if actual != expected:
                raise RuntimeError(f"Graph count mismatch: {actual}, expected {expected}")
            session.run("CALL db.awaitIndexes(60)").consume()
            print(f"KG verified: {actual[0]} nodes / {actual[1]} edges")


if __name__ == "__main__":
    main()
