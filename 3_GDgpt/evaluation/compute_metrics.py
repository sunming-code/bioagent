import argparse
import json
from pathlib import Path
from statistics import mean

# 全局别名映射（延迟加载）
_GENE_ALIAS_MAP = None
_PATHWAY_ALIAS_MAP = None


def _load_gene_alias_map(path: str = None):
    """加载基因别名映射表 (lowercase -> canonical)"""
    global _GENE_ALIAS_MAP
    if _GENE_ALIAS_MAP is not None:
        return _GENE_ALIAS_MAP
    candidates = [
        path,
        "evaluation/gene_alias_map.json",
        str(Path(__file__).parent / "gene_alias_map.json"),
    ]
    for p in candidates:
        if p and Path(p).exists():
            with open(p, "r", encoding="utf-8") as f:
                _GENE_ALIAS_MAP = json.load(f)
            return _GENE_ALIAS_MAP
    _GENE_ALIAS_MAP = {}
    return _GENE_ALIAS_MAP


def _canonicalize_gene(name: str, alias_map: dict) -> str:
    """将基因名标准化为 canonical symbol"""
    s = str(name).strip().lower()
    if not s:
        return ""
    # 查别名映射
    canonical = alias_map.get(s)
    if canonical:
        return canonical.lower()
    # 去除常见后缀 (如 "CD274 gene" -> "cd274")
    for suffix in [" gene", " protein", " receptor"]:
        if s.endswith(suffix):
            trimmed = s[:-len(suffix)].strip()
            canonical = alias_map.get(trimmed)
            if canonical:
                return canonical.lower()
            return trimmed
    return s


def _canonicalize_pathway(name: str) -> str:
    """通路名模糊标准化：去除 'pathway'/'signaling'/'process' 等后缀，统一格式"""
    s = str(name).strip().lower()
    if not s:
        return ""
    # 去除常见无信息后缀
    for suffix in [" pathway", " signaling pathway", " process", " cascade"]:
        if s.endswith(suffix):
            s = s[:-len(suffix)].strip()
    # 统一分隔符
    s = s.replace("_", " ").replace("-", " ")
    # 去除多余空格
    s = " ".join(s.split())
    return s


def load_jsonl(path: Path):
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def normalize_items(items, canonicalizer=None):
    """标准化实体列表，可选使用 canonicalizer 函数"""
    result = set()
    for item in items:
        s = str(item).strip()
        if not s:
            continue
        if canonicalizer:
            s = canonicalizer(s)
        else:
            s = s.lower()
        if s:
            result.add(s)
    return result


def normalize_genes(items, alias_map=None):
    """专用于基因的标准化"""
    if alias_map is None:
        alias_map = _load_gene_alias_map()
    return normalize_items(items, lambda x: _canonicalize_gene(x, alias_map))


def normalize_pathways(items):
    """专用于通路的标准化"""
    return normalize_items(items, _canonicalize_pathway)


def _pathway_fuzzy_match(gold_set: set, pred_set: set) -> int:
    """通路的模糊匹配：如果 gold 通路名是 pred 通路名的子串（或反过来），算命中"""
    hits = 0
    matched_pred = set()
    for g in gold_set:
        for p in pred_set:
            if p in matched_pred:
                continue
            # 精确匹配
            if g == p:
                hits += 1
                matched_pred.add(p)
                break
            # 子串匹配（任一方向）
            if g in p or p in g:
                hits += 1
                matched_pred.add(p)
                break
    return hits


def prf1(gold, pred, entity_type="generic"):
    """计算 Precision, Recall, F1。
    entity_type: 'gene' | 'pathway' | 'generic'
    当 gold 和 pred 都为空时返回 None（跳过该样本）。
    """
    alias_map = _load_gene_alias_map()

    if entity_type == "gene":
        gold_set = normalize_genes(gold, alias_map)
        pred_set = normalize_genes(pred, alias_map)
    elif entity_type == "pathway":
        gold_set = normalize_pathways(gold)
        pred_set = normalize_pathways(pred)
    else:
        gold_set = normalize_items(gold)
        pred_set = normalize_items(pred)

    if not gold_set and not pred_set:
        return None, None, None  # 跳过：双方都没有数据
    if not pred_set:
        return 0.0, 0.0, 0.0
    if not gold_set:
        return 0.0, 0.0, 0.0

    if entity_type == "pathway":
        hit = _pathway_fuzzy_match(gold_set, pred_set)
    else:
        hit = len(gold_set & pred_set)

    precision = hit / len(pred_set) if pred_set else 0.0
    recall = hit / len(gold_set) if gold_set else 0.0
    f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
    return precision, recall, f1


def recall_at_k(gold, pred, k, entity_type="generic"):
    alias_map = _load_gene_alias_map()

    if entity_type == "gene":
        gold_set = normalize_genes(gold, alias_map)
        pred_canon = [_canonicalize_gene(str(x), alias_map) for x in pred[:k] if str(x).strip()]
        pred_set = {x for x in pred_canon if x}
    elif entity_type == "pathway":
        gold_set = normalize_pathways(gold)
        pred_set = normalize_pathways(pred[:k])
    else:
        gold_set = normalize_items(gold)
        pred_set = {str(x).strip().lower() for x in pred[:k] if str(x).strip()}

    if not gold_set:
        return None  # 跳过

    if entity_type == "pathway":
        hit = _pathway_fuzzy_match(gold_set, pred_set)
    else:
        hit = len(gold_set & pred_set)
    return hit / len(gold_set)


def precision_at_k(gold, pred, k, entity_type="generic"):
    alias_map = _load_gene_alias_map()

    if entity_type == "gene":
        gold_set = normalize_genes(gold, alias_map)
        pred_canon = [_canonicalize_gene(str(x), alias_map) for x in pred[:k] if str(x).strip()]
        pred_list = [x for x in pred_canon if x]
    elif entity_type == "pathway":
        gold_set = normalize_pathways(gold)
        pred_list = list(normalize_pathways(pred[:k]))
    else:
        gold_set = normalize_items(gold)
        pred_list = [str(x).strip().lower() for x in pred[:k] if str(x).strip()]

    if not pred_list:
        return 0.0

    if entity_type == "pathway":
        hit = _pathway_fuzzy_match(gold_set, set(pred_list))
    else:
        hit = len(gold_set & set(pred_list))
    return hit / len(pred_list)


def safe_score(value, lo, hi):
    try:
        v = float(value)
    except Exception:
        return None
    if v < lo or v > hi:
        return None
    return v


def main():
    parser = argparse.ArgumentParser(description="Compute Task KG evaluation metrics from gold and prediction JSONL files.")
    parser.add_argument("--gold", required=True, help="Path to gold JSONL")
    parser.add_argument("--pred", required=True, help="Path to predictions JSONL")
    parser.add_argument("--k", type=int, default=5, help="Top-k cutoff for retrieval metrics")
    parser.add_argument("--alias-map", default=None, help="Path to gene alias map JSON (optional)")
    args = parser.parse_args()

    # 预加载别名映射
    if args.alias_map:
        _load_gene_alias_map(args.alias_map)
    else:
        _load_gene_alias_map()

    gold_rows = load_jsonl(Path(args.gold))
    pred_rows = {row["id"]: row for row in load_jsonl(Path(args.pred))}

    retrieval_gene_recall = []
    retrieval_gene_precision = []
    retrieval_pathway_recall = []
    retrieval_pathway_precision = []
    bridge_hits = []
    coverage_scores = []

    answer_gene_f1 = []
    answer_pathway_f1 = []
    answer_phenotype_f1 = []
    mechanism_scores = []
    faithfulness_scores = []
    utility_scores = []

    missing_predictions = []

    for gold in gold_rows:
        pred = pred_rows.get(gold["id"])
        if pred is None:
            missing_predictions.append(gold["id"])
            continue

        pred_genes = pred.get("predicted_genes", [])
        pred_pathways = pred.get("predicted_pathways", [])
        pred_phenotypes = pred.get("predicted_phenotypes", [])
        pred_drugs = pred.get("predicted_drugs", [])

        # 检索层指标（使用 entity_type 做标准化匹配）
        gr = recall_at_k(gold.get("gold_genes", []), pred_genes, args.k, entity_type="gene")
        gp = precision_at_k(gold.get("gold_genes", []), pred_genes, args.k, entity_type="gene")
        pr = recall_at_k(gold.get("gold_pathways", []), pred_pathways, args.k, entity_type="pathway")
        pp = precision_at_k(gold.get("gold_pathways", []), pred_pathways, args.k, entity_type="pathway")

        if gr is not None:
            retrieval_gene_recall.append(gr)
        if gp is not None:
            retrieval_gene_precision.append(gp)
        if pr is not None:
            retrieval_pathway_recall.append(pr)
        if pp is not None:
            retrieval_pathway_precision.append(pp)

        bridge_hits.append(
            1.0 if bool(pred.get("bridge_found", False)) == bool(gold.get("gold_bridge", False)) else 0.0
        )

        coverage = 0
        if pred_genes:
            coverage += 1
        if pred_pathways:
            coverage += 1
        if pred_phenotypes:
            coverage += 1
        if pred_drugs:
            coverage += 1
        coverage_scores.append(coverage / 4.0)

        # 端到端指标（使用 entity_type）
        _, _, gene_f1 = prf1(gold.get("gold_genes", []), pred_genes, entity_type="gene")
        _, _, pathway_f1 = prf1(gold.get("gold_pathways", []), pred_pathways, entity_type="pathway")
        _, _, phenotype_f1 = prf1(gold.get("gold_phenotypes", []), pred_phenotypes, entity_type="generic")

        if gene_f1 is not None:
            answer_gene_f1.append(gene_f1)
        if pathway_f1 is not None:
            answer_pathway_f1.append(pathway_f1)
        if phenotype_f1 is not None:
            answer_phenotype_f1.append(phenotype_f1)

        mech = safe_score(pred.get("mechanism_completeness"), 0, 2)
        faith = safe_score(pred.get("graph_faithfulness"), 0, 2)
        utility = safe_score(pred.get("utility_score"), 1, 5)
        if mech is not None:
            mechanism_scores.append(mech)
        if faith is not None:
            faithfulness_scores.append(faith)
        if utility is not None:
            utility_scores.append(utility)

    result = {
        "num_gold": len(gold_rows),
        "num_predictions": len(pred_rows),
        "missing_predictions": missing_predictions,
        "retrieval": {
            f"gene_recall@{args.k}": mean(retrieval_gene_recall) if retrieval_gene_recall else 0.0,
            f"gene_precision@{args.k}": mean(retrieval_gene_precision) if retrieval_gene_precision else 0.0,
            f"pathway_recall@{args.k}": mean(retrieval_pathway_recall) if retrieval_pathway_recall else 0.0,
            f"pathway_precision@{args.k}": mean(retrieval_pathway_precision) if retrieval_pathway_precision else 0.0,
            "bridge_hit_rate": mean(bridge_hits) if bridge_hits else 0.0,
            "coverage": mean(coverage_scores) if coverage_scores else 0.0
        },
        "end_to_end": {
            "gene_f1": mean(answer_gene_f1) if answer_gene_f1 else 0.0,
            "pathway_f1": mean(answer_pathway_f1) if answer_pathway_f1 else 0.0,
            "phenotype_f1": mean(answer_phenotype_f1) if answer_phenotype_f1 else 0.0,
            "mechanism_completeness": mean(mechanism_scores) if mechanism_scores else None,
            "graph_faithfulness": mean(faithfulness_scores) if faithfulness_scores else None,
            "utility_score": mean(utility_scores) if utility_scores else None
        }
    }

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
