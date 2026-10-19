"""Step 5: disease associations, genotype compatibility and HPO prioritization."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import re
import sqlite3
import sys

import jsonschema

from . import __version__
from .common import ROOT, checksum, now, write_json
from .disease_db import DiseaseDatabase
from .ingest import read_json, tsv_value
from .inheritance import SUPPORT, evaluate_inheritance, genotype, modes_from_annotations, prepare_family
from .intervar import validate_annotation
from .phenotype import Ontology, PhenotypeScorer, resolve_case

CLASSIFICATIONS = set(SUPPORT) | {"Benign", "Likely benign"}
NEARBY_FUNCTIONS = {"intergenic", "upstream", "downstream", "upstream;downstream"}
DIRECT_FUNCTIONS = {"exonic", "splicing", "intronic", "UTR3", "UTR5", "ncRNA_exonic", "ncRNA_splicing", "ncRNA_intronic"}
CANDIDATE_COLUMNS = ["rank", "candidate_id", "disease_id", "disease_name", "gene", "ncbi_gene_id",
                     "association_type", "priority_band", "inheritance_status", "inheritance_mode",
                     "phenotype_status", "phenotype_score", "variant_support", "supporting_variant_ids",
                     "all_variant_ids", "acmg_classifications", "carrier_possible", "review_flags"]
LINK_COLUMNS = ["normalized_id", "original_gene", "gene_occurrence", "resolved_gene", "gene_mapping_status",
                "classification", "gene_relation", "eligible_for_candidates", "exclusion_reasons", "associations"]


def validate_acmg(path):
    manifest = read_json(path)
    jsonschema.Draft7Validator(read_json(ROOT / "contracts/acmg_results.schema.json")).validate(manifest)
    status = read_json(path.parent / "status.json")
    if status.get("status") != "complete" or status.get("stage") != "classify_variants":
        raise ValueError("第四步尚未成功完成")
    paths = {}
    for name, spec in manifest["files"].items():
        file = (path.parent / spec["path"]).resolve(strict=True)
        if file.stat().st_size != spec["bytes"] or checksum(file) != spec["sha256"]:
            raise ValueError(f"第四步产物校验失败: {name}")
        paths[name] = file
    annotation_spec = manifest["annotation_manifest"]
    annotation_path = (path.parent / annotation_spec["path"]).resolve(strict=True)
    if checksum(annotation_path) != annotation_spec["sha256"]:
        raise ValueError("第四步引用的第三步清单校验失败")
    annotation, _, prepared, _ = validate_annotation(annotation_path)
    if manifest["sample_id"] != annotation["sample_id"] or manifest["frequency_policy"] != prepared["frequency_policy"]:
        raise ValueError("上游样本或 PopGen 频率策略不一致")
    return manifest, paths


def gene_relation(annotation):
    functions = set(filter(None, re.split(r"[,;]", annotation.get("Func.refGene", ""))))
    if functions & DIRECT_FUNCTIONS:
        return "overlapping_gene_feature"
    if functions & NEARBY_FUNCTIONS:
        return "nearby_gene_only"
    return "unresolved_gene_relation"


def eligibility(record, mapped, include_background):
    reasons = []
    if record["integrated"]["classification"] not in SUPPORT:
        reasons.append("benign_or_likely_benign_classification")
    relation = gene_relation(record["annotation"])
    if relation != "overlapping_gene_feature":
        reasons.append(relation)
    if not mapped.get("symbol"):
        reasons.append(mapped["status"])
    if "special_clinical_context_requires_review" in record["data_flags"]:
        reasons.append("special_clinical_context_requires_separate_interpretation")
    if (record["integrated"]["classification"] == "Uncertain significance" and
            record["triage"]["triage_route"] == "background" and not include_background):
        reasons.append("background_vus_deprioritized_upstream")
    return relation, reasons


def compact_variant(record):
    annotation = record["annotation"]
    disease_ids = sorted(set(re.findall(r"(?:OMIM|MIM):\d+", annotation.get("CLNDISDB", ""))))
    disease_ids = [identifier.replace("MIM:", "OMIM:") if identifier.startswith("MIM:") else identifier for identifier in disease_ids]
    disease_ids += ["ORPHA:" + value for value in re.findall(r"(?:Orphanet|ORPHA):([0-9]+)", annotation.get("CLNDISDB", ""))]
    return {"normalized_id": record["normalized_id"], "original_gene": record["gene"],
            "classification": record["integrated"]["classification"], "patient": record["patient"],
            "consequence": {key: annotation.get(key, ".") for key in ("Func.refGene", "ExonicFunc.refGene", "AAChange.refGene")},
            "clinvar": {key: annotation.get(key, ".") for key in ("CLNSIG", "CLNREVSTAT", "CLNDN", "CLNDISDB")},
            "clinvar_disease_ids": sorted(set(disease_ids)), "triage": record["triage"], "data_flags": record["data_flags"]}


def collect_links(paths, manifest, database, outdir, include_background):
    groups = {}
    seen_variants, seen_contexts = set(), set()
    mapped_cache, association_cache = {}, {}
    counts = Counter({name: 0 for name in ("gene_context_records", "gene_contexts_with_disease_links",
                     "gene_disease_link_records", "non_mendelian_links_audit_only")})
    exclusions, mapping_counts = Counter(), Counter()
    with (outdir / "variant_disease_links.jsonl").open("w") as structured, (outdir / "variant_disease_links.tsv").open("w", newline="") as tab:
        writer = csv.DictWriter(tab, fieldnames=LINK_COLUMNS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        with paths["acmg_results.jsonl"].open() as handle:
            for line in handle:
                record = json.loads(line)
                source = record["patient"]
                if source["sample_id"] != manifest["sample_id"] or source["normalized_id"] != record["normalized_id"]:
                    raise ValueError("第四步基因上下文包含其他样本或不同标准化变异")
                if record["integrated"]["classification"] not in CLASSIFICATIONS:
                    raise ValueError("第四步包含未知分类")
                context = (record["normalized_id"], record["gene"], record["gene_occurrence"])
                if context in seen_contexts:
                    raise ValueError("第四步包含重复基因上下文")
                seen_contexts.add(context)
                seen_variants.add(record["normalized_id"])
                gene = record["gene"]
                if gene not in mapped_cache:
                    mapped_cache[gene] = database.resolve_gene(gene)
                mapped = mapped_cache[gene]
                cache_key = (mapped.get("gene_id"), mapped.get("symbol"))
                if cache_key not in association_cache:
                    association_cache[cache_key] = database.associations(mapped)
                associations = association_cache[cache_key]
                relation, reasons = eligibility(record, mapped, include_background)
                mapping_counts[mapped["status"]] += 1
                counts["gene_context_records"] += 1
                counts["gene_contexts_with_disease_links"] += bool(associations)
                counts["gene_disease_link_records"] += len(associations)
                if not associations:
                    reasons.append("no_gene_disease_association_in_snapshot")
                exclusions.update(reasons)
                link = {"normalized_id": record["normalized_id"], "original_gene": gene,
                        "gene_occurrence": record["gene_occurrence"], "resolved_gene": mapped.get("symbol"),
                        "gene_mapping_status": mapped["status"], "classification": record["integrated"]["classification"],
                        "gene_relation": relation, "eligible_for_candidates": not reasons,
                        "exclusion_reasons": reasons, "associations": associations,
                        "gene_resolution": mapped, "association_source": "HPO genes_to_disease; original source retained per link"}
                structured.write(json.dumps(link, ensure_ascii=False, allow_nan=False) + "\n")
                writer.writerow({key: tsv_value(link[key]) for key in LINK_COLUMNS})
                if reasons:
                    continue
                variant = compact_variant(record)
                genotype(variant)
                for association in associations:
                    if association["association_type"] != "MENDELIAN":
                        counts["non_mendelian_links_audit_only"] += 1
                        continue
                    key = (mapped["symbol"], association["disease_id"])
                    group = groups.setdefault(key, {"gene": mapped, "disease_id": association["disease_id"],
                        "disease_name": association["disease_name"], "associations": [], "variants": {}})
                    if association not in group["associations"]:
                        group["associations"].append(association)
                    previous = group["variants"].get(variant["normalized_id"])
                    if previous and previous["classification"] != variant["classification"]:
                        raise ValueError("基因别名归一化后同一变异的分类不一致，需要先复核上游")
                    group["variants"][variant["normalized_id"]] = variant
    counts["input_variants"] = len(seen_variants)
    if counts["gene_context_records"] != manifest["counts"]["gene_context_records"] or counts["input_variants"] != manifest["counts"]["selected_variants"]:
        raise ValueError("第四步变异/基因上下文数量与清单不一致")
    return groups, seen_variants, counts, dict(exclusions), dict(mapping_counts)


def make_candidates(groups, database, ontology, resolved, case, family, policy):
    scorer = PhenotypeScorer(database, ontology, policy["negative_phenotype_penalty"]) if resolved["positive_hpo_ids"] else None
    phenotype_cache, annotation_cache = {}, {}
    rows = []
    for (symbol, identifier), group in sorted(groups.items()):
        if identifier not in annotation_cache:
            annotation_cache[identifier] = database.annotations(identifier)
        annotations = annotation_cache[identifier]
        modes = modes_from_annotations(annotations, ontology)
        # Each condition owns its ClinVar match flag even when the same variant
        # participates in several gene-disease hypotheses.
        variants = [dict(row) for row in sorted(group["variants"].values(), key=lambda row: row["normalized_id"])]
        inheritance = evaluate_inheritance(modes, variants, case, family)
        if identifier not in phenotype_cache:
            phenotype_cache[identifier] = scorer.score(resolved, annotations) if scorer else {
                "status": "not_evaluated_no_positive_phenotypes", "score": None, "positive_score": None,
                "negative_conflict_fraction": None, "matches": [], "contradictions": [],
                "method": "Lin symmetric best-match average; corpus IC; not a diagnostic probability"}
        phenotype = phenotype_cache[identifier]
        carrier_possible = any(row.get("carrier_possible", False) for row in inheritance["evaluations"]
                               if row["mode"] == inheritance["mode"])
        flags = {"gene_disease_clinical_validity_not_curated", "disease_specific_mechanism_not_evaluated",
                 "historical_intervar_classification_unchanged"}
        if any(row["classification"] == "Uncertain significance" for row in variants):
            flags.add("vus_is_not_diagnostic_evidence")
        if any("source_quality_incomplete" in row["data_flags"] for row in variants):
            flags.add("source_quality_incomplete")
        if any(row["triage"]["triage_route"] == "background" for row in variants):
            flags.add("background_vus_explicitly_included")
        if phenotype["status"] != "evaluated":
            flags.add(phenotype["status"])
        if not inheritance["status"].startswith("compatible_"):
            flags.add("inheritance_incomplete_or_requires_review")
        if resolved["unresolved_entries"]:
            flags.add("unresolved_patient_phenotypes")
        if phenotype["contradictions"]:
            flags.add("explicit_phenotype_conflicts")
        for variant in variants:
            variant["clinvar_disease_match"] = identifier in variant["clinvar_disease_ids"]
        row = {"candidate_id": identifier + "|" + symbol, "disease_id": identifier, "disease_name": group["disease_name"],
               "gene": symbol, "ncbi_gene_id": group["gene"]["gene_id"], "association_type": "MENDELIAN",
               "association_sources": group["associations"], "inheritance_annotations": modes,
               "priority_band": inheritance["priority_band"], "inheritance_status": inheritance["status"],
               "inheritance_mode": inheritance["mode"], "inheritance": inheritance,
               "phenotype_status": phenotype["status"], "phenotype_score": phenotype["score"], "phenotype": phenotype,
               "variant_support": inheritance["variant_support"], "supporting_variant_ids": inheritance["supporting_variant_ids"],
               "all_variant_ids": [variant["normalized_id"] for variant in variants],
               "acmg_classifications": {variant["normalized_id"]: variant["classification"] for variant in variants},
               "variants": variants, "carrier_possible": carrier_possible, "review_flags": sorted(flags),
               "diagnosis_established": False, "risk_probability": None,
               "interpretation": ("Carrier possibility or a missing second allele; not an established recessive diagnosis." if carrier_possible else
                                  "Gene-disease hypothesis for review; verify variant mechanism, phenotype and analytical quality.")}
        rows.append(row)
    rows.sort(key=lambda row: (row["priority_band"], -(row["phenotype_score"] if row["phenotype_score"] is not None else -1),
                               -row["variant_support"], row["disease_id"], row["gene"]))
    for rank, row in enumerate(rows, 1):
        row["rank"] = rank
    return rows


def write_candidates(outdir, rows):
    write_json(outdir / "disease_candidates.json", rows)
    with (outdir / "disease_candidates.jsonl").open("w") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
    for name, selected in (("disease_candidates.tsv", rows), ("carrier_findings.tsv", [row for row in rows if row["carrier_possible"]])):
        with (outdir / name).open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=CANDIDATE_COLUMNS, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            for row in selected:
                writer.writerow({key: tsv_value(row[key]) for key in CANDIDATE_COLUMNS})


def prioritize(args):
    input_path = args.acmg_manifest.expanduser().resolve(strict=True)
    manifest_hash = checksum(input_path)
    manifest, paths = validate_acmg(input_path)
    database_path = args.disease_database.expanduser().resolve(strict=True)
    database_hash = checksum(database_path)
    database = DiseaseDatabase(database_path)
    outdir = args.outdir.expanduser().absolute()
    try:
        case_path = args.case.expanduser().resolve(strict=True) if args.case else None
        case_hash = checksum(case_path) if case_path else None
        case = read_json(case_path) if case_path else {"schema_version": "1.0", "sample_id": manifest["sample_id"],
                "sex": "unknown", "phenotypes": [], "family": {"relationships_confirmed": False, "genotypes": [], "phase": []}}
        jsonschema.Draft7Validator(read_json(ROOT / "contracts/case.schema.json")).validate(case)
        if case["sample_id"] != manifest["sample_id"]:
            raise ValueError("病例与第四步样本 ID 不一致")
        if case.get("age_years") is not None and case.get("onset_age_years") is not None and case["onset_age_years"] > case["age_years"]:
            raise ValueError("发病年龄不能大于当前年龄")
        policy_path, alias_path = args.policy.expanduser().resolve(strict=True), args.phenotype_aliases.expanduser().resolve(strict=True)
        policy, aliases = read_json(policy_path), read_json(alias_path)
        policy_hash, alias_hash = checksum(policy_path), checksum(alias_path)
        if (policy.get("schema_version") != "1.0" or policy.get("variant_support") != SUPPORT or
                not isinstance(policy.get("negative_phenotype_penalty"), (int, float)) or
                not 0 <= policy["negative_phenotype_penalty"] <= 1 or not isinstance(policy.get("include_background_vus"), bool)):
            raise ValueError("疾病排序策略不符合固定语义")
        policy = {**policy, "include_background_vus": args.include_background_vus or policy["include_background_vus"]}
        if aliases.get("schema_version") != "1.0" or not isinstance(aliases.get("aliases"), dict):
            raise ValueError("表型词典不符合契约")
        ontology = Ontology(database.terms)
        resolved = resolve_case(case, ontology, aliases["aliases"])
        if outdir.exists():
            raise ValueError(f"输出目录已存在，拒绝覆盖: {outdir}")
        outdir.mkdir(parents=True, exist_ok=False)
        write_json(outdir / "status.json", {"stage": "prioritize_diseases", "status": "running", "started_at": now()})
        try:
            write_json(outdir / "case.json", case)
            write_json(outdir / "phenotypes.normalized.json", resolved)
            write_json(outdir / "disease_policy.json", policy)
            write_json(outdir / "disease_database_snapshot.json", database.manifest)
            groups, identifiers, counts, exclusions, mapping_counts = collect_links(paths, manifest, database, outdir, policy["include_background_vus"])
            family = prepare_family(case, identifiers)
            rows = make_candidates(groups, database, ontology, resolved, case, family, policy)
            write_candidates(outdir, rows)
            counts.update(candidate_disease_gene_pairs=len(rows), distinct_candidate_diseases=len({row["disease_id"] for row in rows}),
                          carrier_findings=sum(row["carrier_possible"] for row in rows),
                          phenotype_evaluated_candidates=sum(row["phenotype_status"] == "evaluated" for row in rows),
                          inheritance_compatible_candidates=sum(row["inheritance_status"].startswith("compatible_") for row in rows),
                          unresolved_patient_phenotypes=len(resolved["unresolved_entries"]))
            summary = {"sample_id": manifest["sample_id"], "counts": dict(counts), "exclusion_reasons": exclusions,
                       "gene_mapping_status": mapping_counts, "case_provided": case_path is not None,
                       "phenotype_status": resolved["status"], "ranking_semantics": policy["score_semantics"],
                       "acmg_classifications_modified": False, "upstream_scope": manifest["scope"],
                       "upstream_input_qc": read_json(paths["acmg_summary.json"]).get("upstream_input_qc"),
                       "limitations": [
                           "Disease candidates are review hypotheses, not patient diagnoses or risk probabilities.",
                           "HPO source associations are not ClinGen clinical-validity or disease-specific mechanism curation.",
                           "OMIM and ORPHA disease IDs are kept separate; equivalent conditions can appear more than once.",
                           "InterVar historical ACMG2015 classifications and upstream quality limitations are unchanged.",
                           "Absent parental calls, phase or phenotype data remain unknown; no de novo ACMG code is assigned.",
                           "Clinical narrative is retained; structured HPO IDs or exact configured labels drive matching.",
                           "Age/onset are retained for review; sex/PAR, heteroplasmy and complex inheritance require relevant context.",
                           "Candidate selection excludes B/LB, nearest-gene-only, special clinical contexts, non-Mendelian mappings and default background VUS; all mappings remain in audit outputs.",
                           "An empty candidate list does not exclude genetic disease or establish a negative diagnosis."]}
            write_json(outdir / "disease_summary.json", summary)
            if checksum(input_path) != manifest_hash or checksum(database_path) != database_hash:
                raise ValueError("处理期间输入或疾病数据库清单发生变化")
            for name, path in paths.items():
                if checksum(path) != manifest["files"][name]["sha256"]:
                    raise ValueError(f"处理期间第四步产物发生变化: {name}")
            if case_path and checksum(case_path) != case_hash:
                raise ValueError("处理期间病例信息发生变化")
            if checksum(policy_path) != policy_hash or checksum(alias_path) != alias_hash:
                raise ValueError("处理期间排序策略或表型词典发生变化")
            db_spec = database.manifest["database"]
            if checksum((database_path.parent / db_spec["path"]).resolve()) != db_spec["sha256"]:
                raise ValueError("处理期间疾病数据库发生变化")
            output_names = ["case.json", "phenotypes.normalized.json", "disease_policy.json", "disease_database_snapshot.json",
                            "variant_disease_links.jsonl", "variant_disease_links.tsv", "disease_candidates.json",
                            "disease_candidates.jsonl", "disease_candidates.tsv", "carrier_findings.tsv", "disease_summary.json"]
            modules = ["disease.py", "disease_db.py", "phenotype.py", "inheritance.py"]
            result = {"schema_version": "1.0", "status": "complete", "stage": "prioritize_diseases",
                      "sample_id": manifest["sample_id"], "assembly": "GRCh38", "counts": dict(counts),
                      "producer": {"name": "egene.disease", "version": __version__, "finished_at": now(),
                                   "source_sha256": {name: checksum(ROOT / "egene" / name) for name in modules}},
                      "acmg_manifest": {"path": str(input_path), "sha256": manifest_hash},
                      "disease_database": {"path": str(database_path), "sha256": database_hash,
                                           "hpo_release": database.manifest["hpo_release"], "hgnc_release": database.manifest["hgnc_release"]},
                      "case_input": {"path": str(case_path) if case_path else None, "sha256": case_hash, "provided": case_path is not None},
                      "policy_input": {"path": str(policy_path), "sha256": policy_hash},
                      "phenotype_aliases_input": {"path": str(alias_path), "sha256": alias_hash},
                      "acmg_classifications_modified": False, "phenotype_status": resolved["status"],
                      "files": {name: {"path": name, "bytes": (outdir / name).stat().st_size, "sha256": checksum(outdir / name)} for name in output_names}}
            jsonschema.Draft7Validator(read_json(ROOT / "contracts/disease_results.schema.json")).validate(result)
            write_json(outdir / "disease_manifest.json", result)
            write_json(outdir / "status.json", {"stage": "prioritize_diseases", "status": "complete", "finished_at": now(), "counts": dict(counts)})
            print(f"第五步完成：{counts['input_variants']:,} 个变异，{counts['candidate_disease_gene_pairs']:,} 个疾病—基因候选；表型状态 {resolved['status']}\n输出目录：{outdir}", flush=True)
            return result
        except BaseException as error:
            write_json(outdir / "status.json", {"stage": "prioritize_diseases", "status": "failed", "failed_at": now(), "error": str(error)})
            raise
    finally:
        database.close()


def argument_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acmg-manifest", required=True, type=Path)
    parser.add_argument("--outdir", required=True, type=Path, help="New output directory")
    parser.add_argument("--case", type=Path, help="Structured case JSON; absent data remain unknown")
    parser.add_argument("--disease-database", type=Path, default=ROOT / "data/disease/disease_database_manifest.json")
    parser.add_argument("--policy", type=Path, default=ROOT / "config/disease_prioritization.json")
    parser.add_argument("--phenotype-aliases", type=Path, default=ROOT / "config/phenotype_aliases.json")
    parser.add_argument("--include-background-vus", action="store_true", help="Explicit exploratory inclusion of overlapping background VUS; flags and other eligibility gates remain")
    return parser


def main(argv=None):
    args = argument_parser().parse_args(argv)
    try:
        prioritize(args)
    except (ValueError, OSError, KeyError, TypeError, sqlite3.Error, jsonschema.ValidationError) as error:
        print(f"疾病关联与排序失败：{error}", file=sys.stderr)
        return 2
    return 0
