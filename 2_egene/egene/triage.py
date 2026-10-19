"""Transparent annotation prioritization. This module never assigns ACMG classes."""
from __future__ import annotations

import math
import re

MISSING = {"", ".", "na", "nan", "none", "null"}


def terms(value: str) -> set[str]:
    decoded = value.replace("\\x2c", ",").replace("_", " ").lower()
    return {" ".join(item.strip().split()) for item in re.split(r"[|/;,]", decoded) if item.strip()}


def clinvar_summary(annotation: dict[str, str]) -> dict:
    labels = terms(annotation.get("CLNSIG", "."))
    review = annotation.get("CLNREVSTAT", ".").replace("\\x2c", ",").replace("_", " ").lower()
    raw = " ".join(labels)
    conflict = (("conflict" in raw) or ("conflict" in review.replace("no conflicts", "")) or
                bool(labels & {"pathogenic", "likely pathogenic"} and labels & {"benign", "likely benign"}))
    if "practice guideline" in review:
        stars = 4
    elif "reviewed by expert panel" in review:
        stars = 3
    elif "multiple submitters" in review and "no conflicts" in review:
        stars = 2
    elif "criteria provided" in review and "no assertion criteria" not in review:
        stars = 1
    else:
        stars = 0
    benign_labels = {"benign", "likely benign"}
    return {
        "labels": sorted(labels - MISSING), "review_stars": stars, "conflict": conflict,
        "pathogenic_assertion": bool(labels & {"pathogenic", "likely pathogenic"}),
        "benign_only": bool(labels - MISSING) and (labels - MISSING) <= benign_labels and not conflict,
        "special_context": any(item in raw for item in (
            "risk factor", "risk allele", "drug response", "association", "protective",
            "low penetrance", "affects", "established risk", "uncertain risk",
        )),
    }


def frequency_values(value: str, source: str) -> list[float]:
    if value.strip().lower() in MISSING:
        return []
    result = []
    for token in re.split(r"[;,|]", value):
        if token.strip().lower() in MISSING:
            continue
        try:
            number = float(token)
        except ValueError as error:
            raise ValueError(f"{source} 含无效频率: {value}") from error
        if not math.isfinite(number) or not 0 <= number <= 1:
            raise ValueError(f"{source} 频率不在 [0,1]: {value}")
        result.append(number)
    return result


def consequence_summary(annotation: dict[str, str], policy: dict) -> dict:
    functions, exonic = set(), set()
    for protocol in policy["gene_protocols"]:
        functions.update(terms(annotation.get("Func." + protocol, ".")) - MISSING)
        exonic.update(terms(annotation.get("ExonicFunc." + protocol, ".")) - MISSING)
    splice = bool(functions & {"splicing", "ncrna splicing"})
    protein = bool(exonic & {value.lower() for value in policy["protein_altering"]})
    high = splice or bool(exonic & {value.lower() for value in policy["high_impact"]})
    incomplete = not functions or "unknown" in exonic or ("exonic" in functions and not exonic)
    return {"functions": sorted(functions), "exonic_functions": sorted(exonic),
            "protein_or_splice": protein or splice, "high_impact": high, "incomplete": incomplete}


def prioritize(source: dict[str, str], annotation: dict[str, str], policy: dict,
               *, frequency_permission: bool, curated_exception: bool = False) -> dict:
    clinical = clinvar_summary(annotation)
    consequence = consequence_summary(annotation, policy)
    frequencies = {}
    # Legacy ANNOVAR sources remain independent annotations. Do not count their
    # agreement as multiple independent ACMG evidence items.
    for name in ("gnomAD_genome_ALL", "esp6500siv2_all", "1000g2015aug_all"):
        values = frequency_values(annotation.get(name, "."), name)
        if values:
            frequencies[name] = max(values)
    if frequency_permission and source.get("af_status") == "available":
        values = frequency_values(source.get("matched_pop_AF", ""), "popgen_matched")
        if values:
            frequencies["popgen_matched"] = max(values)
    cutoff = policy["frequency_screen_cutoff"]
    maximum = max(frequencies.values()) if frequencies else None
    frequency_status = "unknown" if maximum is None else ("common" if maximum >= cutoff else "below_screen_cutoff")
    discordant = bool(frequencies) and max(frequencies.values()) >= cutoff > min(frequencies.values())
    reasons = []
    is_priority = False
    route = "background"
    rank = 100
    if clinical["conflict"]:
        route, rank, kind, is_priority = "review", 20, "clinvar_conflict", True
        reasons.append("ClinVar 分类存在冲突，保留复核，未据频率直接排除")
    elif clinical["special_context"]:
        route, rank, kind = "review", 35, "clinical_context_annotation"
        reasons.append("ClinVar 涉及风险、药物反应、低外显率或其他特定背景；单列复核")
        is_priority = clinical["pathogenic_assertion"]
    elif clinical["pathogenic_assertion"]:
        route, rank, kind, is_priority = "candidate", 10, "clinvar_pathogenic_assertion", True
        reasons.append("ClinVar 有致病/可能致病提交，保留核对疾病、审核状态与原始证据")
    elif curated_exception:
        route, rank, kind, is_priority = "review", 25, "curated_frequency_exception", True
        reasons.append("命中固定 InterVar 频率例外表，保留复核")
    elif consequence["high_impact"] and (
        frequency_status == "common" or
        (clinical["benign_only"] and clinical["review_stars"] >= policy["trusted_benign_min_stars"])
    ):
        route, rank, kind, is_priority = "review", 30, "high_impact_contradiction", True
        reasons.append("高影响/剪接注释与常见频率或良性提交并存，需核对转录本及适用背景")
    elif clinical["benign_only"] and clinical["review_stars"] >= policy["trusted_benign_min_stars"]:
        kind = "clinvar_benign_deprioritized"
        reasons.append("ClinVar 为无冲突良性/可能良性，审核状态达到配置要求；移出重点清单")
    elif frequency_status == "common":
        kind = "frequency_deprioritized"
        reasons.append("可用于筛选的来源中频率达到初筛阈值；只降低优先级，不赋予良性分类")
    elif consequence["high_impact"]:
        route, rank, kind, is_priority = "candidate", 40, "high_impact_candidate", True
        reasons.append("保留高影响/剪接变异，后续评估疾病机制与 ACMG 证据")
    elif consequence["protein_or_splice"]:
        route, rank, kind = "candidate", 50, "protein_altering_candidate"
        reasons.append("保留可能改变蛋白的变异，后续结合判级、表型与遗传模式")
    elif consequence["incomplete"]:
        route, rank, kind = "review", 60, "annotation_incomplete"
        reasons.append("功能注释不完整，保留补充注释，未推断为无影响")
    else:
        kind = "consequence_deprioritized"
        reasons.append("当前注释未给出蛋白改变/剪接或已知临床保护条件，保留全表供后续按病例回查")
    if frequency_status == "unknown":
        reasons.append("频率未知，未视为罕见，也未生成 PM2")
    if discordant:
        reasons.append("频率来源跨越初筛阈值，存在来源或人群差异")
    return {
        "triage_route": route, "triage_kind": kind, "triage_rank": rank,
        "priority_review": is_priority, "triage_reasons": reasons,
        "screen_frequency_status": frequency_status, "screen_max_AF": maximum,
        "screen_frequency_sources": frequencies, "frequency_sources_discordant": discordant,
        "clinvar_review_stars": clinical["review_stars"], "clinvar_labels": clinical["labels"],
        "consequence_functions": consequence["functions"], "consequence_exonic_functions": consequence["exonic_functions"],
        "acmg_classification": "not_evaluated",
    }
