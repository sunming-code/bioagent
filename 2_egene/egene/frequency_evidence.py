"""PopGen evidence adapter; thresholds must have an explicit variant context."""
from __future__ import annotations

import math

EXTERNAL_FREQUENCIES = [
    "1000g2015aug_all", "esp6500siv2_all", "gnomAD_genome_ALL",
] + ["gnomAD_genome_" + name for name in ("AFR", "AMR", "EAS", "FIN", "NFE", "OTH", "ASJ")]


def numeric_af(value: str, field: str) -> float | None:
    if value.strip() in {"", "."}:
        return None
    try:
        result = float(value)
    except ValueError as error:
        raise ValueError(f"无效频率 {field}: {value}") from error
    if not math.isfinite(result) or not 0 <= result <= 1:
        raise ValueError(f"频率不在 [0,1] 范围: {field}={value}")
    return result


def adapt_frequency(source: dict, annotation: dict, policy: dict, *, permission: bool,
                    historical_exception: bool = False) -> dict:
    """Add supported benign evidence; never infer PM2 from a missing lookup.

    Independent InterVar frequency sources remain unchanged. Missing evidence is
    recorded as unknown even though InterVar's binary interface uses PM2=0 to
    withhold unsupported evidence from its combination algorithm.
    """
    external = {name: numeric_af(annotation[name], name) for name in EXTERNAL_FREQUENCIES}
    matched = numeric_af(source["matched_pop_AF"], "matched_pop_AF")
    numeric_af(source.get("global_AF", ""), "global_AF")  # Validate, never use to retarget ancestry.
    if source["af_status"] not in {"available", "missing", "no_row"}:
        raise ValueError("未知的 PopGen af_status")
    if (source["af_status"] == "available") != (matched is not None):
        raise ValueError("PopGen af_status 与 matched_pop_AF 不一致")
    rule = policy["variants"].get(source["normalized_id"])
    overrides, decisions = {}, []
    for code, threshold_name in (("BA1", "ba1_threshold"), ("BS1", "bs1_threshold")):
        threshold = rule.get(threshold_name) if rule else None
        if not permission:
            status = "permission_blocked"
        elif matched is None:
            status = "frequency_unknown"
        elif historical_exception:
            status = "historical_frequency_exception"
        elif threshold is None:
            status = "threshold_not_provided"
        elif not rule["population_adequacy_confirmed"]:
            status = "population_adequacy_unconfirmed"
        elif not rule["exceptions_reviewed"]:
            status = "exceptions_not_reviewed"
        else:
            met = matched > threshold if code == "BA1" else matched >= threshold
            status = "met" if met else "below_threshold"
            if met:
                overrides[code] = 1
        decisions.append({
            "code": code, "status": status, "frequency": matched, "threshold": threshold,
            "comparison": ">" if code == "BA1" else ">=",
            "context": rule["context"] if rule else None, "basis": rule["basis"] if rule else None,
            "effect": "set_to_1" if status == "met" else "retain_independent_intervar_evidence",
        })
    # InterVar treats '.' in every external frequency column as PM2. A failed or
    # absent annotation lookup alone does not establish adequate reference coverage.
    all_missing = all(value is None for value in external.values())
    incompatible = bool(overrides)
    if all_missing or incompatible:
        overrides["PM2"] = 0
    pm2_status = ("contradicted_by_supported_popgen_frequency" if incompatible else
                  "insufficient_coverage_evidence" if all_missing else "retained_from_intervar")
    decisions.append({
        "code": "PM2", "status": pm2_status,
        "effect": "withhold_PM2" if all_missing or incompatible else "unchanged",
        "reason": "validated_PopGen_BA1_or_BS1_in_same_variant_context" if incompatible else
                  "all_external_frequency_annotations_missing; absence_not_established" if all_missing
                  else "independent_external_frequency_annotations_available",
    })
    return {"normalized_id": source["normalized_id"], "matched_pop": source["matched_pop"],
            "permission": permission, "matched_pop_AF": matched, "af_status": source["af_status"],
            "external_frequencies": external, "historical_exception": historical_exception,
            "overrides": overrides, "decisions": decisions,
            "gnn_usage": "supplementary_ancestry_only; never_used_for_evidence"}
