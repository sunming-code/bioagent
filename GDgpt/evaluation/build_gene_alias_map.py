#!/usr/bin/env python3
"""
构建基因别名映射表，用于跨数据源的基因匹配。

从 Neo4j PrimeKG 导出所有基因名及别名，生成标准化映射：
  gene_name → canonical_symbol
  alias → canonical_symbol

用法:
  python evaluation/build_gene_alias_map.py --output evaluation/gene_alias_map.json
"""

import argparse
import json
from pathlib import Path


def build_from_neo4j(uri="neo4j://localhost:7687", user="neo4j", password="password"):
    from neo4j import GraphDatabase
    driver = GraphDatabase.driver(uri, auth=(user, password))

    alias_map = {}  # lowercase -> canonical

    with driver.session() as session:
        result = session.run("""
            MATCH (g:Gene)
            RETURN g.name AS name, g.normalized_name AS norm, g.aliases AS aliases, g.id AS gid
        """)
        for rec in result:
            name = (rec["name"] or "").strip()
            norm = (rec["norm"] or "").strip()
            aliases_str = (rec["aliases"] or "").strip()
            gid = (rec["gid"] or "").strip()

            canonical = norm if norm else name
            if not canonical:
                continue

            # 主名
            alias_map[name.lower()] = canonical
            alias_map[canonical.lower()] = canonical

            # normalized_name
            if norm:
                alias_map[norm.lower()] = canonical

            # aliases（以 | 分割）
            if aliases_str:
                for alias in aliases_str.split("|"):
                    alias = alias.strip()
                    if alias:
                        alias_map[alias.lower()] = canonical

            # Gene ID (如 Gene:7157 -> 7157)
            if gid and gid.startswith("Gene:"):
                ncbi_id = gid.replace("Gene:", "")
                alias_map[ncbi_id] = canonical

    driver.close()
    return alias_map


def build_common_aliases():
    """常见基因别名的手动补充"""
    manual = {
        # 常见变体
        "her2": "ERBB2",
        "her-2": "ERBB2",
        "erbb-2": "ERBB2",
        "neu": "ERBB2",
        "p53": "TP53",
        "tp-53": "TP53",
        "brca-1": "BRCA1",
        "brca-2": "BRCA2",
        "k-ras": "KRAS",
        "kras": "KRAS",
        "n-ras": "NRAS",
        "h-ras": "HRAS",
        "b-raf": "BRAF",
        "c-kit": "KIT",
        "c-met": "MET",
        "vegfr-1": "FLT1",
        "vegfr-2": "KDR",
        "vegfr-3": "FLT4",
        "pdgfr-b": "PDGFRB",
        "pdgfr-a": "PDGFRA",
        "alk-1": "ALK",
        "egfr": "EGFR",
        "er-alpha": "ESR1",
        "er-beta": "ESR2",
    }
    return {k.lower(): v for k, v in manual.items()}


def main():
    parser = argparse.ArgumentParser(description="构建基因别名映射表")
    parser.add_argument("--output", default="evaluation/gene_alias_map.json")
    parser.add_argument("--neo4j-uri", default="neo4j://localhost:7687")
    parser.add_argument("--neo4j-user", default="neo4j")
    parser.add_argument("--neo4j-password", default="password")
    args = parser.parse_args()

    print("从 Neo4j 导出基因映射...")
    neo4j_map = build_from_neo4j(args.neo4j_uri, args.neo4j_user, args.neo4j_password)
    print(f"  Neo4j 映射: {len(neo4j_map)} 条")

    manual_map = build_common_aliases()
    print(f"  手动补充: {len(manual_map)} 条")

    # 合并（手动优先级低于 Neo4j）
    combined = {**manual_map, **neo4j_map}
    print(f"  合并后: {len(combined)} 条")

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(combined, f, ensure_ascii=False, indent=0)

    print(f"已保存到 {args.output}")


if __name__ == "__main__":
    main()
