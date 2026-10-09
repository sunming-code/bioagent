"""
为测试集每题生成 `expected_kg_edges`（Traceability 的"标准答案边"）。

背景：compute_system_metrics.py 的 Traceability = |cited_edges ∩ expected_kg_edges| / |expected_kg_edges|。
测试集缺 expected_kg_edges 字段 → Traceability 恒为 NaN。本脚本补上它。

严谨性（B 方案）：不凭空拼边，而是把 (disease, gold_gene/pathway) 候选边拿到 Neo4j(Aura)
逐条核实【真实存在】后才收录，保证标准答案全是 KG 里的真边。

边格式：[实体A, 实体B, 关系]，与抽取器产出的 cited_edges 一致；
compute_system_metrics._norm_edge 会做小写/去空格/前两元素排序的无序匹配。

关系类型（与 GDgpt tools.py 查询一致）：
  - disease -[ASSOCIATED_WITH]- gene
  - disease 经 gene -[INVOLVED_IN]- pathway（通过 Bridge 两跳核实通路可达）

用法：
  python evaluation/build_expected_kg_edges.py \
    --config config.json \
    --gold  evaluation/independent_testset/output/testset_kg_optimized_enriched.jsonl \
    --out   evaluation/independent_testset/output/testset_kg_optimized_enriched_with_edges.jsonl \
    [--limit N]
"""

import argparse
import base64
import json
import ssl
import urllib.request
import urllib.error


class AuraHTTP:
    def __init__(self, config_path):
        cfg = json.load(open(config_path, encoding="utf-8"))
        uri = cfg["neo4j_uri"].strip()
        self.host = uri.split("://", 1)[1].split("/", 1)[0].split(":", 1)[0].strip()
        self.user = cfg["neo4j_user"].strip()
        self.pw = cfg["neo4j_password"].strip()
        self.db = (cfg.get("neo4j_database") or "").strip() or self.user
        self.endpoint = f"https://{self.host}/db/{self.db}/query/v2"
        self.auth = base64.b64encode(f"{self.user}:{self.pw}".encode()).decode()
        self.ctx = ssl.create_default_context()

    def run(self, cypher, params=None):
        body = {"statement": cypher}
        if params:
            body["parameters"] = params
        req = urllib.request.Request(self.endpoint, data=json.dumps(body).encode(), method="POST")
        req.add_header("Authorization", f"Basic {self.auth}")
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")
        with urllib.request.urlopen(req, timeout=60, context=self.ctx) as r:
            data = json.loads(r.read().decode())["data"]
        return data["values"]


def _edge_exists(client, label_a, name_a, rel, label_b, name_b):
    """通用：核实 (A:label_a{name_a})-[rel]-(B:label_b{name_b}) 是否真实存在（无向匹配）。"""
    rows = client.run(
        f"MATCH (a:{label_a})-[r:{rel}]-(b:{label_b}) "
        "WHERE (toLower(a.name)=$an OR toLower(a.normalized_name)=$an) "
        "AND (toLower(b.name)=$bn OR toLower(b.normalized_name)=$bn) "
        "RETURN count(r) AS c",
        {"an": name_a.strip().lower(), "bn": name_b.strip().lower()},
    )
    return rows and rows[0][0] > 0


def _bridge_reachable(client, label_a, name_a, rel1, label_mid, rel2, label_b, name_b):
    """核实两跳可达：(A{name_a})-[rel1]-(mid)-[rel2]-(B{name_b})。"""
    rows = client.run(
        f"MATCH (a:{label_a})-[:{rel1}]-(m:{label_mid})-[:{rel2}]-(b:{label_b}) "
        "WHERE (toLower(a.name)=$an OR toLower(a.normalized_name)=$an) "
        "AND (toLower(b.name)=$bn OR toLower(b.normalized_name)=$bn) "
        "RETURN count(*) AS c",
        {"an": name_a.strip().lower(), "bn": name_b.strip().lower()},
    )
    return rows and rows[0][0] > 0


def build_edges_for_case(client, case):
    """按题型（disease/gene/pathway-centered）以焦点实体为中心造边，逐条 KG 核实。"""
    task = (case.get("task_type") or "").lower()
    edges = []
    stats = {"gene_checked": 0, "gene_kept": 0, "pathway_checked": 0, "pathway_kept": 0,
             "disease_checked": 0, "disease_kept": 0}

    def add_gene_disease(disease, gene):
        stats["gene_checked"] += 1
        try:
            if _edge_exists(client, "Disease", disease, "ASSOCIATED_WITH", "Gene", gene):
                edges.append([disease, gene, "ASSOCIATED_WITH"]); stats["gene_kept"] += 1
        except Exception as e:
            print(f"    [warn] disease-gene ({gene}): {str(e)[:70]}")

    def add_disease_pathway(disease, pathway):
        stats["pathway_checked"] += 1
        try:
            if _bridge_reachable(client, "Disease", disease, "ASSOCIATED_WITH", "Gene", "INVOLVED_IN", "Pathway", pathway):
                edges.append([disease, pathway, "INVOLVED_IN"]); stats["pathway_kept"] += 1
        except Exception as e:
            print(f"    [warn] disease-pathway ({pathway[:25]}): {str(e)[:70]}")

    def add_gene_pathway(gene, pathway):
        stats["pathway_checked"] += 1
        try:
            if _edge_exists(client, "Gene", gene, "INVOLVED_IN", "Pathway", pathway):
                edges.append([gene, pathway, "INVOLVED_IN"]); stats["pathway_kept"] += 1
        except Exception as e:
            print(f"    [warn] gene-pathway ({pathway[:25]}): {str(e)[:70]}")

    def add_gene_disease_from_gene(gene, disease):
        stats["disease_checked"] += 1
        try:
            if _edge_exists(client, "Gene", gene, "ASSOCIATED_WITH", "Disease", disease):
                edges.append([gene, disease, "ASSOCIATED_WITH"]); stats["disease_kept"] += 1
        except Exception as e:
            print(f"    [warn] gene-disease ({disease[:25]}): {str(e)[:70]}")

    def add_pathway_gene(pathway, gene):
        stats["gene_checked"] += 1
        try:
            if _edge_exists(client, "Pathway", pathway, "INVOLVED_IN", "Gene", gene):
                edges.append([pathway, gene, "INVOLVED_IN"]); stats["gene_kept"] += 1
        except Exception as e:
            print(f"    [warn] pathway-gene ({gene}): {str(e)[:70]}")

    if task == "disease-centered" or case.get("disease_focus"):
        disease = (case.get("disease_focus") or case.get("disease") or "").strip()
        if disease:
            for g in case.get("gold_genes", []) or []:
                add_gene_disease(disease, g)
            for p in case.get("gold_pathways", []) or []:
                add_disease_pathway(disease, p)

    elif task == "gene-centered" or case.get("gene_focus"):
        gene = (case.get("gene_focus") or "").strip()
        if gene:
            for d in case.get("gold_diseases", []) or []:
                add_gene_disease_from_gene(gene, d)
            for p in case.get("gold_pathways", []) or []:
                add_gene_pathway(gene, p)

    elif task == "pathway-centered" or case.get("pathway_focus"):
        pathway = (case.get("pathway_focus") or "").strip()
        if pathway:
            for g in case.get("gold_genes", []) or []:
                add_pathway_gene(pathway, g)

    return edges, stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--gold", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=0, help="仅处理前 N 题（0=全部）")
    args = ap.parse_args()

    client = AuraHTTP(args.config)
    client.run("RETURN 1")
    print(f"✅ 连接 Aura: {client.endpoint}\n")

    cases = [json.loads(l) for l in open(args.gold, encoding="utf-8") if l.strip()]
    if args.limit:
        cases = cases[: args.limit]

    total_edges = 0
    out_cases = []
    for i, case in enumerate(cases, 1):
        edges, stats = build_edges_for_case(client, case)
        case["expected_kg_edges"] = edges
        out_cases.append(case)
        total_edges += len(edges)
        print(f"[{i}/{len(cases)}] {case.get('id')}  "
              f"gene {stats['gene_kept']}/{stats['gene_checked']}  "
              f"pathway {stats['pathway_kept']}/{stats['pathway_checked']}  "
              f"→ {len(edges)} 条 expected 边")

    with open(args.out, "w", encoding="utf-8") as f:
        for c in out_cases:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    n_empty = sum(1 for c in out_cases if not c.get("expected_kg_edges"))
    print(f"\n✅ 完成：{len(out_cases)} 题，共 {total_edges} 条 expected_kg_edges")
    print(f"   平均每题 {total_edges/max(len(out_cases),1):.1f} 条；空边的题 {n_empty} 个")
    print(f"   输出：{args.out}")


if __name__ == "__main__":
    main()
