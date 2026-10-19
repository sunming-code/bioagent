"""
Extract structured predictions from raw GDgpt tool calls.

The batch runner stores raw tool call traces in each prediction row. This script
fills predicted_* fields, bridge_found, and cited_edges so downstream metrics can
evaluate entity recall and KG traceability without re-running the model.
"""

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set, Tuple


BRIDGE_INTENTS = {
    "DiseaseGenePathwayBridge",
    "GenePhenotypeBridge",
    "DrugTargetDiseaseBridge",
}


def _normalize(s: str) -> str:
    if not s or not isinstance(s, str):
        return ""
    return s.strip().lower()


def _safe_str(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    return str(v).strip()


def _as_list(v: Any) -> List[Any]:
    if v is None:
        return []
    if isinstance(v, list):
        return v
    return [v]


def _relation_label(raw: Any, default: str) -> str:
    rel = _safe_str(raw) or default
    rel = rel.strip().upper().replace("-", "_").replace(" ", "_")
    aliases = {
        "TARGET": "TARGETS",
        "TARGET_OF": "TARGETS",
        "ASSOCIATION": "ASSOCIATED_WITH",
        "ASSOCIATED_WITH": "ASSOCIATED_WITH",
        "INVOLVED_IN": "INVOLVED_IN",
        "PART_OF": "INVOLVED_IN",
    }
    return aliases.get(rel, rel)


def _collect_from_record(record: Dict[str, Any], key: str, out: Set[str]) -> None:
    if key not in record:
        return
    val = record[key]
    if val is None:
        return
    for item in _as_list(val):
        s = _safe_str(item)
        if s:
            out.add(_normalize(s))


def _add_edge(edges: Set[Tuple[str, str, str]], a: Any, b: Any, rel: Any, default_rel: str) -> None:
    a_s = _safe_str(a)
    b_s = _safe_str(b)
    if not a_s or not b_s:
        return
    edges.add((a_s, b_s, _relation_label(rel, default_rel)))


def _first_relation(record: Dict[str, Any], keys: Iterable[str], default: str) -> str:
    for key in keys:
        for val in _as_list(record.get(key)):
            rel = _safe_str(val)
            if rel:
                return rel
    return default


def _collect_edges_from_record(intent: str, record: Dict[str, Any], edges: Set[Tuple[str, str, str]]) -> None:
    disease = record.get("disease")
    gene = record.get("gene")
    pathway = record.get("pathway")
    phenotype = record.get("phenotype")
    drug = record.get("drug")

    if intent == "DiseaseToGene":
        _add_edge(edges, gene, disease, record.get("relation"), "ASSOCIATED_WITH")
    elif intent == "GeneToPathway":
        _add_edge(edges, gene, pathway, record.get("relation"), "INVOLVED_IN")
    elif intent == "GeneToDrug":
        _add_edge(edges, drug, gene, record.get("relation"), "TARGETS")
    elif intent == "DiseaseToDrug":
        _add_edge(edges, drug, disease, record.get("relation"), "INDICATED_FOR")
    elif intent == "DiseaseToPhenotype":
        _add_edge(edges, disease, phenotype, record.get("relation"), "ASSOCIATED_WITH")
    elif intent == "GeneToPhenotype":
        _add_edge(edges, gene, phenotype, record.get("relation"), "ASSOCIATED_WITH")
    elif intent == "DiseaseGenePathwayBridge":
        dg_rel = _first_relation(record, ["disease_gene_relations", "relation"], "ASSOCIATED_WITH")
        gp_rel = _first_relation(record, ["gene_pathway_relations", "pathway_relation"], "INVOLVED_IN")
        for g in _as_list(record.get("genes")):
            _add_edge(edges, g, disease, dg_rel, "ASSOCIATED_WITH")
            _add_edge(edges, g, pathway, gp_rel, "INVOLVED_IN")
    elif intent == "GenePhenotypeBridge":
        _add_edge(edges, gene, disease, record.get("disease_relation"), "ASSOCIATED_WITH")
        _add_edge(edges, gene, phenotype, record.get("phenotype_relation"), "ASSOCIATED_WITH")
    elif intent == "DrugTargetDiseaseBridge":
        dt_rel = _first_relation(record, ["drug_gene_relations", "relation"], "TARGETS")
        gd_rel = _first_relation(record, ["gene_disease_relations", "disease_gene_relations"], "ASSOCIATED_WITH")
        for g in _as_list(record.get("genes")):
            _add_edge(edges, drug, g, dt_rel, "TARGETS")
            _add_edge(edges, g, disease, gd_rel, "ASSOCIATED_WITH")


def _parse_result(result_raw: Any) -> Dict[str, Any]:
    if result_raw is None:
        return {}
    if isinstance(result_raw, str):
        try:
            return json.loads(result_raw)
        except json.JSONDecodeError:
            return {}
    if isinstance(result_raw, dict):
        return result_raw
    return {}


def extract_entities_from_tool_calls(tool_calls: List[Dict[str, Any]]) -> Dict[str, Any]:
    genes: Set[str] = set()
    pathways: Set[str] = set()
    phenotypes: Set[str] = set()
    drugs: Set[str] = set()
    relations: Set[str] = set()
    cited_edges: Set[Tuple[str, str, str]] = set()
    bridge_found = False

    for tc in tool_calls or []:
        result = _parse_result(tc.get("result"))
        for run in result.get("runs") or []:
            intent = _safe_str(run.get("intent", ""))
            if intent in BRIDGE_INTENTS:
                bridge_found = True

            for rec in run.get("records") or []:
                _collect_from_record(rec, "gene", genes)
                _collect_from_record(rec, "genes", genes)
                _collect_from_record(rec, "pathway", pathways)
                _collect_from_record(rec, "phenotype", phenotypes)
                _collect_from_record(rec, "drug", drugs)

                for rel_key in ("relation", "disease_relation", "phenotype_relation"):
                    if rel_key in rec and rec[rel_key]:
                        relations.add(_relation_label(rec[rel_key], "RELATED_TO"))
                _collect_edges_from_record(intent, rec, cited_edges)

    return {
        "predicted_genes": sorted(genes),
        "predicted_pathways": sorted(pathways),
        "predicted_phenotypes": sorted(phenotypes),
        "predicted_drugs": sorted(drugs),
        "predicted_relations": sorted(relations),
        "cited_edges": [list(e) for e in sorted(cited_edges)],
        "bridge_found": bridge_found,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract predicted entities, bridge flag, and cited KG edges from raw prediction JSONL."
    )
    parser.add_argument("--pred", required=True, help="Input prediction JSONL with tool_calls.")
    parser.add_argument("--out", required=True, help="Output prediction JSONL.")
    parser.add_argument("--inplace", action="store_true", help="Overwrite --pred directly.")
    args = parser.parse_args()

    pred_path = Path(args.pred)
    out_path = pred_path if args.inplace else Path(args.out)

    if not pred_path.exists():
        raise FileNotFoundError(f"File not found: {pred_path}")

    rows = []
    with pred_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))

    out_rows = []
    for row in rows:
        tool_calls = row.get("tool_calls") or []
        extracted = extract_entities_from_tool_calls(tool_calls)

        new_row = dict(row)
        # gene_reranker: if kg_reranked_genes is non-empty, put them first (LLM-prioritised order),
        # then append any remaining KG genes not already in the reranked list.
        reranked = [g.lower() for g in (row.get("kg_reranked_genes") or []) if g]
        if reranked:
            reranked_set = set(reranked)
            remainder = [g for g in extracted["predicted_genes"] if g not in reranked_set]
            new_row["predicted_genes"] = reranked + remainder
        else:
            new_row["predicted_genes"] = extracted["predicted_genes"] or row.get("predicted_genes") or []
        new_row["predicted_pathways"] = extracted["predicted_pathways"] or row.get("predicted_pathways") or []
        new_row["predicted_phenotypes"] = extracted["predicted_phenotypes"] or row.get("predicted_phenotypes") or []
        new_row["predicted_drugs"] = extracted["predicted_drugs"] or row.get("predicted_drugs") or []
        new_row["predicted_relations"] = extracted["predicted_relations"] or row.get("predicted_relations") or []
        new_row["cited_edges"] = extracted["cited_edges"] or row.get("cited_edges") or []
        new_row["bridge_found"] = extracted["bridge_found"] if tool_calls else row.get("bridge_found", False)
        out_rows.append(new_row)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for row in out_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"[saved] {out_path}")
    print(f"[rows] {len(out_rows)}")


if __name__ == "__main__":
    main()
