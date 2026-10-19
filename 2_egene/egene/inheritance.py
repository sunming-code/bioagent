"""Genotype compatibility and explicit phase/family observations; no ACMG edits."""
from __future__ import annotations

from collections import Counter
from itertools import combinations
import re

SUPPORT = {"Pathogenic": 1.0, "Likely pathogenic": 0.85, "Uncertain significance": 0.2}
MODE_ROOTS = [("HP:0001419", "XLR"), ("HP:0001423", "XLD"), ("HP:0000006", "AD"),
              ("HP:0000007", "AR"), ("HP:0001427", "MT"), ("HP:0001450", "YL"), ("HP:0001417", "XL")]


def modes_from_annotations(annotations, ontology):
    modes = {}
    for row in annotations:
        if row["aspect"] != "I" or row["negated"]:
            continue
        identifier = ontology.canonical(row["hpo_id"])
        name = ontology.terms[identifier]["name"]
        ancestors = ontology.ancestors(identifier)
        if any(word in name.casefold() for word in ("imprint", "digenic", "oligogenic", "somatic", "mosaic")):
            code = "complex"
        else:
            code = next((code for root, code in MODE_ROOTS if root in ancestors), "complex")
        mode = modes.setdefault(code, {"mode": code, "hpo_terms": [], "references": []})
        term = {"id": identifier, "label": name}
        if term not in mode["hpo_terms"]:
            mode["hpo_terms"].append(term)
        if row["reference"] not in mode["references"]:
            mode["references"].append(row["reference"])
    return [modes[key] for key in sorted(modes)]


def genotype(variant):
    source = variant["patient"]
    alleles = re.split(r"[/|]", source["source_GT"])
    if not alleles or any(not allele.isdigit() for allele in alleles) or len(alleles) not in (1, 2):
        raise ValueError("上游保留变异的原始基因型不完整")
    target = int(source["alt_index"])
    positions = [i for i, allele in enumerate(alleles) if int(allele) == target]
    if len(positions) != int(source["alt_dosage"]) or not positions:
        raise ValueError("原始基因型与目标 ALT 剂量不一致")
    return {"ploidy": len(alleles), "dosage": len(positions), "haplotypes": positions}


def parental_call(call):
    if not call or not call.get("callable"):
        return None
    if not call.get("basis", "").strip():
        raise ValueError("父母位点可判读声明需要依据")
    alleles = re.split(r"[/|]", call["gt"])
    if any(allele not in {"0", "1"} for allele in alleles):
        raise ValueError("声明 callable 的父母位点不能含缺失 GT")
    return "alternate" if "1" in alleles else "reference"


def prepare_family(case, known_variants):
    supplied = case.get("family", {})
    observations = {}
    for record in supplied.get("genotypes", []):
        identifier = record["normalized_id"]
        if identifier not in known_variants or identifier in observations:
            raise ValueError(f"家系基因型引用未知或重复变异: {identifier}")
        for role in ("mother", "father"):
            parental_call(record.get(role))
        observations[identifier] = record
    phase = {}
    for record in supplied.get("phase", []):
        key = frozenset(record["variant_ids"])
        if len(key) != 2 or not key <= known_variants or key in phase or not record["basis"].strip():
            raise ValueError("家系相位声明包含未知/重复变异或缺少依据")
        chromosomes = {identifier.split(":")[1] for identifier in key}
        if len(chromosomes) != 1:
            raise ValueError("cis/trans 相位声明必须在同一条染色体")
        phase[key] = record
    return {"relationships_confirmed": supplied.get("relationships_confirmed", False),
            "observations": observations, "phase": phase}


def family_observation(identifier, family, variant=None):
    record = family["observations"].get(identifier, {})
    mother, father = (parental_call(record.get(role)) for role in ("mother", "father"))
    status, origin = "not_evaluated_incomplete_parental_calls", None
    if mother and father:
        if mother == father == "reference":
            status = ("consistent_with_de_novo_confirmed_relationships" if family["relationships_confirmed"]
                      else "consistent_with_de_novo_unconfirmed_relationships")
        elif mother == father == "alternate":
            status = "both_parents_carry"
        else:
            origin = "mother" if mother == "alternate" else "father"
            status = "reported_in_" + origin
        if variant is not None:
            call = genotype(variant)
            if call["dosage"] == call["ploidy"] == 2 and "reference" in (mother, father):
                status, origin = "mendelian_inconsistency_requires_review", None
    return {"status": status, "origin": origin if family["relationships_confirmed"] else None,
            "mother": record.get("mother"), "father": record.get("father"),
            "relationships_confirmed": family["relationships_confirmed"], "acmg_evidence_assigned": False}


def pair_phase(first, second, family):
    observed = []
    a, b = first["patient"], second["patient"]
    ga, gb = genotype(first), genotype(second)
    if (a["record_id"] == b["record_id"] and a.get("source_CHROM") == b.get("source_CHROM") and
            a.get("source_POS") == b.get("source_POS") and a["source_GT"] == b["source_GT"] and
            a["alt_index"] != b["alt_index"] and ga["ploidy"] == gb["ploidy"] == 2 and ga["dosage"] == gb["dosage"] == 1):
        observed.append(("trans", "different ALT alleles in the same original diploid genotype"))
    elif (ga["dosage"] == gb["dosage"] == 1 and a["CHROM"] == b["CHROM"] and
          a.get("original_phased") == b.get("original_phased") == "true" and
          a.get("original_PS") not in (None, "", ".") and a["original_PS"] == b.get("original_PS")):
        observed.append(("cis" if ga["haplotypes"] == gb["haplotypes"] else "trans", "same original phase set"))
    origin_a = family_observation(first["normalized_id"], family, first)["origin"]
    origin_b = family_observation(second["normalized_id"], family, second)["origin"]
    if origin_a and origin_b:
        observed.append(("trans" if origin_a != origin_b else "cis", "confirmed parent-of-origin observations"))
    explicit = family["phase"].get(frozenset((first["normalized_id"], second["normalized_id"])))
    if explicit:
        observed.append((explicit["relation"], explicit["basis"]))
    resolved = {relation for relation, _ in observed if relation != "unknown"}
    if len(resolved) > 1:
        raise ValueError("患者相位与家系相位证据互相矛盾")
    return {"variant_ids": sorted((first["normalized_id"], second["normalized_id"])),
            "relation": next(iter(resolved)) if resolved else "unknown", "basis": [basis for _, basis in observed]}


def strongest(variants):
    return sorted(variants, key=lambda row: (-SUPPORT[row["classification"]], row["normalized_id"]))


def recessive(variants, family):
    homozygous = [row for row in variants if genotype(row)["ploidy"] == genotype(row)["dosage"] == 2]
    heterozygous = [row for row in variants if genotype(row)["ploidy"] == 2 and genotype(row)["dosage"] == 1]
    options = [(SUPPORT[row["classification"]], [row], "compatible_homozygous") for row in homozygous]
    unknown_options, phase_counts, examples = [], Counter(), []
    for first, second in combinations(strongest(heterozygous), 2):
        phase = pair_phase(first, second, family)
        phase_counts[phase["relation"]] += 1
        if len(examples) < 20:
            examples.append(phase)
        strength = min(SUPPORT[first["classification"]], SUPPORT[second["classification"]])
        if phase["relation"] == "trans":
            options.append((strength, [first, second], "compatible_biallelic_trans"))
        elif phase["relation"] == "unknown":
            unknown_options.append((strength, [first, second], "possible_biallelic_phase_unknown"))
    choices = options or unknown_options
    if choices:
        _, selected, status = max(choices, key=lambda option: (option[0], option[2], tuple(row["normalized_id"] for row in option[1])))
    elif heterozygous:
        selected = strongest(heterozygous)[:1]
        status = "cis_only_second_allele_not_established" if phase_counts["cis"] else "single_heterozygous_second_allele_not_identified"
    else:
        selected, status = [], "not_evaluated_unexpected_ploidy"
    return {"status": status, "supporting_variant_ids": [row["normalized_id"] for row in selected],
            "variant_support": min((SUPPORT[row["classification"]] for row in selected), default=0.0),
            "phase_pair_counts": dict(phase_counts), "phase_examples": examples,
            "phase_examples_truncated": sum(phase_counts.values()) > len(examples),
            "carrier_possible": status.startswith(("single_heterozygous", "cis_only")) and any(row["classification"] in ("Pathogenic", "Likely pathogenic") for row in selected)}


def evaluate_mode(mode, variants, case, family):
    code = mode["mode"]
    result = {"mode": code, "status": "not_evaluated_complex_or_unknown_inheritance", "supporting_variant_ids": [], "variant_support": 0.0}
    if code == "AR":
        autosomal = [row for row in variants if row["patient"]["CHROM"] not in {"chrX", "chrY", "chrM"}]
        result.update(recessive(autosomal, family))
    elif code == "AD":
        eligible = [row for row in variants if row["patient"]["CHROM"] not in {"chrX", "chrY", "chrM"} and genotype(row)["ploidy"] == 2]
        if eligible:
            selected = strongest(eligible)[0]
            result.update(status="compatible_monoallelic", supporting_variant_ids=[selected["normalized_id"]], variant_support=SUPPORT[selected["classification"]])
        else:
            result["status"] = "not_evaluated_chromosome_or_ploidy_mismatch"
    elif code in {"XLR", "XLD", "XL"}:
        x_variants = [row for row in variants if row["patient"]["CHROM"] == "chrX"]
        # PAR regions are diploid and require a separately curated inheritance model.
        x_variants = [row for row in x_variants if not (10001 <= int(row["patient"]["POS"]) <= 2781479 or 155701383 <= int(row["patient"]["POS"]) <= 156030895)]
        hemizygous = [row for row in x_variants if genotype(row)["ploidy"] == 1 and case.get("sex") != "female"]
        if case.get("sex") == "male":
            hemizygous += [row for row in x_variants if genotype(row)["ploidy"] == genotype(row)["dosage"] == 2]
        if hemizygous:
            selected = strongest(hemizygous)[0]
            result.update(status="compatible_hemizygous", supporting_variant_ids=[selected["normalized_id"]], variant_support=SUPPORT[selected["classification"]])
        elif code == "XLD" and case.get("sex") == "female" and x_variants:
            selected = strongest(x_variants)[0]
            result.update(status="compatible_monoallelic", supporting_variant_ids=[selected["normalized_id"]], variant_support=SUPPORT[selected["classification"]])
        elif code == "XLR" and case.get("sex") == "female":
            result.update(recessive(x_variants, family))
            result["symptomatic_heterozygous_female_exceptions"] = "requires disease-specific review"
        else:
            result["status"] = "not_evaluated_sex_ploidy_or_PAR_context"
    elif code == "MT":
        result["status"] = "requires_heteroplasmy_tissue_and_maternal_review"
    elif code == "YL":
        eligible = [row for row in variants if row["patient"]["CHROM"] == "chrY" and genotype(row)["ploidy"] == 1]
        if eligible:
            selected = strongest(eligible)[0]
            result.update(status="compatible_hemizygous", supporting_variant_ids=[selected["normalized_id"]], variant_support=SUPPORT[selected["classification"]])
        else:
            result["status"] = "not_evaluated_chromosome_or_ploidy_mismatch"
    return result


def priority_band(result):
    status, support = result["status"], result["variant_support"]
    if status.startswith("compatible_"):
        return 0 if support >= 0.85 else 2
    if status == "possible_biallelic_phase_unknown":
        return 1 if support >= 0.85 else 3
    if status.startswith(("single_heterozygous", "cis_only")):
        return 4
    return 5


def evaluate_inheritance(modes, variants, case, family):
    evaluations = [evaluate_mode(mode, variants, case, family) for mode in modes]
    if not evaluations:
        evaluations = [{"mode": "unknown", "status": "not_evaluated_no_inheritance_annotation",
                        "supporting_variant_ids": [], "variant_support": 0.0}]
    best = min(evaluations, key=lambda row: (priority_band(row), -row["variant_support"], row["mode"]))
    return {"status": best["status"], "mode": best["mode"], "priority_band": priority_band(best),
            "variant_support": best["variant_support"], "supporting_variant_ids": best["supporting_variant_ids"],
            "evaluations": evaluations, "family_observations": {row["normalized_id"]: family_observation(row["normalized_id"], family, row) for row in variants},
            "diagnosis_established": False, "mechanism_and_penetrance_review": "not_evaluated",
            "note": "Genotype compatibility only; InterVar labels are unchanged and do not establish a disease-specific mechanism or patient diagnosis."}
