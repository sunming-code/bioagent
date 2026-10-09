"""
通过 Aura HTTP Query API (端口 443) 把 task_kg_output 的 CSV 导入 Neo4j Aura。

背景：公司网络封锁了 Bolt 端口 7687，官方 neo4j 驱动 / py2neo 都连不上。
Aura 的 HTTP Query API 走 443（HTTPS），可绕过封锁。本脚本即为此而写。

数据源：kg_build/task_kg_output/{task_kg_nodes.csv, task_kg_edges.csv}
        （10,133 节点 / 87,838 边，schema 已校验与 GDgpt tools.py 匹配）

用法：
  python evaluation/import_kg_to_aura_http.py \
    --config config.json \
    --kg-dir "/Users/yeawenqi/hkust/kg_build /task_kg_output" \
    [--clear]     # 导入前清空库
"""

import argparse
import base64
import csv
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

SUPPORTED_LABELS = ["Gene", "Disease", "Pathway", "Phenotype", "Drug"]
# 合法关系白名单（与 GDgpt tools.py 的查询一致）
LEGAL_RELATIONS = {
    "ASSOCIATED_WITH", "INVOLVED_IN", "TARGETS", "METABOLIZED_BY",
    "TRANSPORTED_BY", "CARRIED_BY", "TREATS", "CONTRAINDICATED_FOR",
    "OFF_LABEL_FOR", "HAS_PHENOTYPE",
}


def clean(v):
    if v is None:
        return ""
    return re.sub(r"\s+", " ", str(v).strip())


class AuraHTTPClient:
    """通过 Aura HTTP Query API v2 执行 Cypher（走 443）。"""

    def __init__(self, host, user, password, database):
        self.endpoint = f"https://{host}/db/{database}/query/v2"
        self.auth = base64.b64encode(f"{user}:{password}".encode()).decode()
        self.ctx = ssl.create_default_context()

    def run(self, cypher, params=None, retries=3):
        body = {"statement": cypher}
        if params:
            body["parameters"] = params
        data = json.dumps(body).encode()
        last_err = None
        for attempt in range(retries):
            req = urllib.request.Request(self.endpoint, data=data, method="POST")
            req.add_header("Authorization", f"Basic {self.auth}")
            req.add_header("Content-Type", "application/json")
            req.add_header("Accept", "application/json")
            try:
                with urllib.request.urlopen(req, timeout=60, context=self.ctx) as r:
                    return json.loads(r.read().decode())
            except urllib.error.HTTPError as e:
                detail = e.read()[:300].decode(errors="replace")
                last_err = f"HTTP {e.code}: {detail}"
                # 4xx（除 429）通常是请求问题，不重试
                if 400 <= e.code < 500 and e.code != 429:
                    raise RuntimeError(last_err)
            except Exception as e:
                last_err = f"{type(e).__name__}: {e}"
            time.sleep(2 * (attempt + 1))
        raise RuntimeError(f"查询失败（重试 {retries} 次）: {last_err}")


def read_csv_rows(path):
    with open(path, "r", encoding="utf-8", newline="") as f:
        yield from csv.DictReader(f)


def batched(iterable, size):
    batch = []
    for item in iterable:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def create_constraints(client):
    print("创建约束与索引...")
    for label in SUPPORTED_LABELS:
        client.run(f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.id IS UNIQUE")
        client.run(f"CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.normalized_name)")
        client.run(f"CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.name)")
    print("  约束/索引就绪")


def import_nodes(client, nodes_file, batch_size=500):
    print(f"导入节点: {nodes_file}")
    # 按 label 分组批量 MERGE（Cypher 里 label 不能参数化，故按类型分批）
    label_counter = Counter()
    total = 0
    by_label = {lbl: [] for lbl in SUPPORTED_LABELS}
    for row in read_csv_rows(nodes_file):
        node_id = clean(row.get("id"))
        label = clean(row.get("type"))
        if not node_id or label not in SUPPORTED_LABELS:
            continue
        by_label[label].append({
            "id": node_id,
            "name": clean(row.get("name")),
            "type": label,
            "normalized_name": clean(row.get("normalized_name")),
            "aliases": clean(row.get("aliases")),
            "source": clean(row.get("source")),
            "description": clean(row.get("description")),
        })

    for label, rows in by_label.items():
        if not rows:
            continue
        cypher = (
            f"UNWIND $rows AS row "
            f"MERGE (n:{label} {{id: row.id}}) "
            f"SET n.name=row.name, n.type=row.type, n.normalized_name=row.normalized_name, "
            f"n.aliases=row.aliases, n.source=row.source, n.description=row.description"
        )
        for chunk in batched(rows, batch_size):
            client.run(cypher, {"rows": chunk})
            total += len(chunk)
            label_counter[label] += len(chunk)
            print(f"  {label}: +{len(chunk)}  (累计 {total})")
    print(f"节点导入完成: {total} 个  {dict(label_counter)}")
    return total


def import_edges(client, edges_file, batch_size=500):
    print(f"导入边: {edges_file}")
    # 按 relation_group 分组（关系类型不能参数化）
    by_rel = {}
    skipped = 0
    for row in read_csv_rows(edges_file):
        src = clean(row.get("source_id"))
        dst = clean(row.get("target_id"))
        rel = clean(row.get("relation_group")).upper()
        if not src or not dst:
            continue
        if rel not in LEGAL_RELATIONS:
            skipped += 1
            continue
        by_rel.setdefault(rel, []).append({
            "src": src, "dst": dst,
            "relation_raw": clean(row.get("relation_raw")),
            "display_relation": clean(row.get("display_relation")),
            "relation_group": clean(row.get("relation_group")),
            "source": clean(row.get("source")),
            "weight": clean(row.get("weight")),
            "source_type": clean(row.get("source_type")),
            "target_type": clean(row.get("target_type")),
        })

    total = 0
    rel_counter = Counter()
    for rel, rows in by_rel.items():
        cypher = (
            f"UNWIND $rows AS row "
            f"MATCH (a {{id: row.src}}) MATCH (b {{id: row.dst}}) "
            f"CREATE (a)-[r:{rel}]->(b) "
            f"SET r.relation_raw=row.relation_raw, r.display_relation=row.display_relation, "
            f"r.relation_group=row.relation_group, r.source=row.source, r.weight=row.weight, "
            f"r.source_type=row.source_type, r.target_type=row.target_type"
        )
        for chunk in batched(rows, batch_size):
            client.run(cypher, {"rows": chunk})
            total += len(chunk)
            rel_counter[rel] += len(chunk)
            print(f"  {rel}: +{len(chunk)}  (累计 {total})")
    print(f"边导入完成: {total} 条  {dict(rel_counter)}")
    if skipped:
        print(f"  （跳过 {skipped} 条非白名单关系）")
    return total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--kg-dir", required=True, help="含 task_kg_nodes.csv / task_kg_edges.csv 的目录")
    ap.add_argument("--clear", action="store_true", help="导入前清空数据库")
    ap.add_argument("--batch-size", type=int, default=500)
    args = ap.parse_args()

    cfg = json.load(open(args.config, encoding="utf-8"))
    uri = cfg["neo4j_uri"].strip()
    host = uri.split("://")[1].split(":")[0].strip()
    user = cfg["neo4j_user"].strip()
    pw = cfg["neo4j_password"].strip()
    db = (cfg.get("neo4j_database") or "").strip() or user

    kg_dir = Path(args.kg_dir)
    nodes_file = kg_dir / "task_kg_nodes.csv"
    edges_file = kg_dir / "task_kg_edges.csv"
    for f in (nodes_file, edges_file):
        if not f.exists():
            print(f"❌ 找不到 {f}")
            sys.exit(1)

    client = AuraHTTPClient(host, user, pw, db)
    print(f"连接 Aura HTTP API: {client.endpoint}")
    client.run("RETURN 1")
    print("✅ 连接成功\n")

    if args.clear:
        print("清空数据库...")
        # 分批删除，避免一次事务过大
        while True:
            res = client.run("MATCH (n) WITH n LIMIT 5000 DETACH DELETE n RETURN count(n) AS c")
            c = res["data"]["values"][0][0]
            if c == 0:
                break
            print(f"  已删 {c}")
        print("  已清空\n")

    create_constraints(client)
    t0 = time.time()
    n = import_nodes(client, nodes_file, args.batch_size)
    e = import_edges(client, edges_file, args.batch_size)
    dt = time.time() - t0

    # 校验
    got_n = client.run("MATCH (n) RETURN count(n) AS c")["data"]["values"][0][0]
    got_e = client.run("MATCH ()-[r]->() RETURN count(r) AS c")["data"]["values"][0][0]
    print(f"\n✅ 导入完成，用时 {dt:.0f}s")
    print(f"   写入: {n} 节点 / {e} 边")
    print(f"   库内实际: {got_n} 节点 / {got_e} 边")


if __name__ == "__main__":
    main()
