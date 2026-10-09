"""
Task-driven PrimeKG Import Script (py2neo)
将 create3.py 输出的 task_kg_nodes.csv / task_kg_edges.csv 导入 Neo4j。
"""

import argparse
import csv
import os
import re
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List

from py2neo import Graph, Node, Relationship


NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")

SUPPORTED_LABELS = ["Gene", "Disease", "Pathway", "Phenotype", "Drug"]


def clean(value: str) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).strip())


def sanitize_rel_type(value: str) -> str:
    value = clean(value).upper()
    value = re.sub(r"[^A-Z0-9]+", "_", value).strip("_")
    return value or "RELATED_TO"


class TaskKGImporter:
    def __init__(self, base_dir: Path, uri: str, user: str, password: str, batch_size: int = 1000):
        self.base_dir = base_dir
        self.nodes_file = base_dir / "task_kg_nodes.csv"
        self.edges_file = base_dir / "task_kg_edges.csv"
        self.batch_size = batch_size

        self.graph = Graph(uri, auth=(user, password))
        self.graph.run("RETURN 1")
        print(f"成功连接到 Neo4j: {uri}")

    def validate_files(self) -> None:
        if not self.nodes_file.exists():
            raise FileNotFoundError(f"找不到节点文件: {self.nodes_file}")
        if not self.edges_file.exists():
            raise FileNotFoundError(f"找不到边文件: {self.edges_file}")

    def clear_database(self) -> None:
        print("正在清空数据库...")
        self.graph.run("MATCH (n) DETACH DELETE n")
        print("数据库已清空")

    def create_constraints(self) -> None:
        print("正在创建约束与索引...")
        for label in SUPPORTED_LABELS:
            self.graph.run(f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.id IS UNIQUE")
            self.graph.run(f"CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.normalized_name)")
            self.graph.run(f"CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.name)")
        print("约束与索引创建完成")

    def _read_csv(self, file_path: Path) -> Iterable[Dict[str, str]]:
        with file_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                yield row

    def import_nodes(self) -> Dict[str, Node]:
        print(f"读取节点文件: {self.nodes_file}")
        node_cache: Dict[str, Node] = {}
        node_count = 0
        label_counter = Counter()

        tx = self.graph.begin()
        for row in self._read_csv(self.nodes_file):
            node_id = clean(row.get("id", ""))
            if not node_id:
                continue

            label = clean(row.get("type", ""))
            if label not in SUPPORTED_LABELS:
                continue

            props = {
                "id": node_id,
                "name": clean(row.get("name", "")),
                "type": label,
                "normalized_name": clean(row.get("normalized_name", "")),
                "aliases": clean(row.get("aliases", "")),
                "source": clean(row.get("source", "")),
                "description": clean(row.get("description", "")),
            }

            node = Node(label, **props)
            tx.create(node)
            node_cache[node_id] = node

            node_count += 1
            label_counter[label] += 1
            if node_count % self.batch_size == 0:
                self.graph.commit(tx)
                tx = self.graph.begin()
                print(f"已创建节点: {node_count}")

        self.graph.commit(tx)
        print(f"节点导入完成，共 {node_count} 个")
        print(f"节点分布: {dict(label_counter)}")
        return node_cache

    def import_edges(self, node_cache: Dict[str, Node]) -> None:
        print(f"读取边文件: {self.edges_file}")
        edge_count = 0
        rel_counter = Counter()
        missing_endpoint = 0

        tx = self.graph.begin()
        for row in self._read_csv(self.edges_file):
            source_id = clean(row.get("source_id", ""))
            target_id = clean(row.get("target_id", ""))
            if not source_id or not target_id:
                continue

            source_node = node_cache.get(source_id)
            target_node = node_cache.get(target_id)
            if not source_node or not target_node:
                missing_endpoint += 1
                continue

            rel_type = sanitize_rel_type(row.get("relation_group", ""))

            rel = Relationship(
                source_node,
                rel_type,
                target_node,
                relation_raw=clean(row.get("relation_raw", "")),
                display_relation=clean(row.get("display_relation", "")),
                relation_group=clean(row.get("relation_group", "")),
                source=clean(row.get("source", "")),
                weight=clean(row.get("weight", "")),
                source_type=clean(row.get("source_type", "")),
                target_type=clean(row.get("target_type", "")),
            )
            tx.create(rel)

            edge_count += 1
            rel_counter[rel_type] += 1
            if edge_count % self.batch_size == 0:
                self.graph.commit(tx)
                tx = self.graph.begin()
                print(f"已创建关系: {edge_count}")

        self.graph.commit(tx)
        print(f"关系导入完成，共 {edge_count} 条")
        print(f"关系分布: {dict(rel_counter)}")
        if missing_endpoint:
            print(f"警告: {missing_endpoint} 条边因端点不存在被跳过")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import task-driven PrimeKG CSV outputs into Neo4j with py2neo")
    parser.add_argument("--input-dir", default="task_kg_output", help="目录下需包含 task_kg_nodes.csv 与 task_kg_edges.csv")
    parser.add_argument("--uri", default=NEO4J_URI, help="Neo4j bolt URI")
    parser.add_argument("--user", default=NEO4J_USER, help="Neo4j username")
    parser.add_argument("--password", default=NEO4J_PASSWORD, help="Neo4j password")
    parser.add_argument("--batch-size", type=int, default=1000, help="事务批大小")
    parser.add_argument("--clear", action="store_true", help="导入前清空数据库")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    importer = TaskKGImporter(
        base_dir=Path(args.input_dir),
        uri=args.uri,
        user=args.user,
        password=args.password,
        batch_size=args.batch_size,
    )
    importer.validate_files()
    if args.clear:
        importer.clear_database()
    importer.create_constraints()
    node_cache = importer.import_nodes()
    importer.import_edges(node_cache)
    print("\n✅ Neo4j 导入完成")


if __name__ == "__main__":
    main()