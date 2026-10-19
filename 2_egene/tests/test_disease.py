"""Step-5 behavior checks using synthetic cases, not clinical performance claims."""
from __future__ import annotations

import contextlib
import copy
import csv
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from egene import disease
from egene.common import checksum, write_json
from egene.disease_db import DiseaseDatabase, build_index
from egene.inheritance import evaluate_inheritance, family_observation, pair_phase, prepare_family
from egene.phenotype import Ontology, PhenotypeScorer, resolve_case


def variant(position=100, *, gene="GENE1", label="Pathogenic", gt="0/1", phase=".", chrom="chr1", alt="G", alt_index=1, record_id=None):
    identifier = f"GRCh38:{chrom}:{position}:A:{alt}"
    dosage = sum(value == str(alt_index) for value in gt.replace("|", "/").split("/"))
    patient = {"sample_id": "TEST", "normalized_id": identifier, "CHROM": chrom, "POS": str(position),
               "REF": "A", "ALT": alt, "source_CHROM": chrom, "source_POS": str(position),
               "source_GT": gt, "alt_index": str(alt_index), "alt_dosage": str(dosage),
               "record_id": str(position) if record_id is None else record_id,
               "original_phased": str("|" in gt).lower(), "original_PS": phase, "original_DP": "35",
               "quality_missing": "[]"}
    return {"normalized_id": identifier, "gene": gene, "gene_occurrence": 1, "patient": patient,
            "integrated": {"classification": label}, "raw": {"classification": label},
            "annotation": {"Func.refGene": "exonic", "ExonicFunc.refGene": "nonsynonymous SNV", "CLNDISDB": "OMIM:100001"},
            "triage": {"triage_route": "candidate"}, "data_flags": []}


def compact(*args, **kwargs):
    return disease.compact_variant(variant(*args, **kwargs))


class DiseaseFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="egene disease test ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        directory = self.root / "database"
        directory.mkdir()
        terms = [("HP:0000001", "All", None), ("HP:0000118", "Phenotypic abnormality", "HP:0000001"),
                 ("HP:0001250", "Seizure", "HP:0000118"), ("HP:0000365", "Hearing impairment", "HP:0000118"),
                 ("HP:0000005", "Mode of inheritance", "HP:0000001"), ("HP:0000006", "Autosomal dominant inheritance", "HP:0000005"),
                 ("HP:0000007", "Autosomal recessive inheritance", "HP:0000005")]
        obo = "format-version: 1.2\n"
        for identifier, name, parent in terms:
            obo += f"\n[Term]\nid: {identifier}\nname: {name}\n"
            if parent:
                obo += f"is_a: {parent}\n"
            if identifier == "HP:0001250":
                obo += 'alt_id: HP:9999999\nsynonym: "Convulsions" EXACT []\n'
        (directory / "hp-international.obo").write_text(obo)
        (directory / "hgnc_complete_set.tsv").write_text("symbol\tstatus\tentrez_id\thgnc_id\talias_symbol\tprev_symbol\n"
            "GENE1\tApproved\t1\tHGNC:1\tAMB\tOLD1\nGENE2\tApproved\t2\tHGNC:2\tAMB\t\n")
        (directory / "genes_to_disease.txt").write_text("ncbi_gene_id\tgene_symbol\tassociation_type\tdisease_id\tsource\n"
            "NCBIGene:1\tGENE1\tMENDELIAN\tOMIM:100001\tfixture:association1\n"
            "NCBIGene:2\tGENE2\tMENDELIAN\tOMIM:100002\tfixture:association2\n"
            "NCBIGene:1\tGENE1\tMENDELIAN\tORPHA:1\tfixture:association3\n"
            "NCBIGene:1\tGENE1\tPOLYGENIC\tOMIM:100003\tfixture:polygenic\n")
        fields = ["database_id", "disease_name", "qualifier", "hpo_id", "reference", "evidence", "onset", "frequency", "sex", "modifier", "aspect", "biocuration"]
        records = [("OMIM:100001", "Synthetic AD seizure condition", "HP:0001250", "P"),
                   ("OMIM:100001", "Synthetic AD seizure condition", "HP:0000006", "I"),
                   ("OMIM:100002", "Synthetic AR hearing condition", "HP:0000365", "P"),
                   ("OMIM:100002", "Synthetic AR hearing condition", "HP:0000007", "I"),
                   ("ORPHA:1", "Synthetic separate identifier", "HP:0000365", "P"),
                   ("ORPHA:1", "Synthetic separate identifier", "HP:0000006", "I")]
        with (directory / "phenotype.hpoa").open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields, delimiter="\t")
            writer.writeheader()
            for identifier, name, hpo, aspect in records:
                writer.writerow(dict.fromkeys(fields, "") | {"database_id": identifier, "disease_name": name, "hpo_id": hpo,
                    "reference": "PMID:fixture", "evidence": "PCS", "frequency": "1/1" if aspect == "P" else "", "aspect": aspect})
        target = directory / "disease.sqlite"
        counts = build_index(directory, target)
        self.database_path = directory / "disease_database_manifest.json"
        write_json(self.database_path, {"schema_version": "1.0", "status": "complete", "hpo_release": "synthetic", "hgnc_release": "synthetic",
                "counts": counts, "database": {"path": target.name, "bytes": target.stat().st_size, "sha256": checksum(target)}})
        self.database = DiseaseDatabase(self.database_path)
        self.addCleanup(self.database.close)
        self.ontology = Ontology(self.database.terms)
        self.aliases = self.root / "aliases.json"
        write_json(self.aliases, {"schema_version": "1.0", "aliases": {"癫痫": "HP:0001250"}})

    def make_manifest(self, records):
        directory = self.root / "acmg"
        directory.mkdir()
        with (directory / "acmg_results.jsonl").open("w") as f:
            for record in records:
                f.write(json.dumps(record) + "\n")
        for name in ["acmg_results.tsv", "acmg_summary.json", "frequency_policy.json", "frequency_evidence.jsonl", "evidence_overrides.tsv", "intervar_snapshot.json", "database_snapshot.json", "execution.json"]:
            (directory / name).write_text('{}\n')
        annotation = self.root / "annotation_manifest.json"
        annotation.write_text('{}\n')
        manifest = {"schema_version": "1.0", "status": "complete", "stage": "classify_variants", "sample_id": "TEST",
                    "producer": {}, "assembly": "GRCh38", "annovar_build": "hg38", "scope": "all", "frequency_policy": {},
                    "classification_performed": bool(records), "phenotype_and_inheritance_evaluated": False,
                    "classifier": {"name": "InterVar", "version": "synthetic", "commit": "fixture", "guidelines": "ACMG-AMP 2015", "vendor_modified": False},
                    "annotation_manifest": {"path": str(annotation), "sha256": checksum(annotation)},
                    "counts": {"selected_variants": len({row["normalized_id"] for row in records}), "gene_context_records": len(records),
                               "classification_changed_variants": 0, "evidence_changed_variants": 0},
                    "files": {p.name: {"path": p.name, "bytes": p.stat().st_size, "sha256": checksum(p)} for p in directory.iterdir()}}
        path = directory / "acmg_manifest.json"
        write_json(path, manifest)
        write_json(directory / "status.json", {"status": "complete", "stage": "classify_variants"})
        return path

    def run_pipeline(self, records, case=None, extra=()):
        path = self.make_manifest(records)
        argv = ["--acmg-manifest", str(path), "--outdir", str(self.root / "output with spaces"),
                "--disease-database", str(self.database_path), "--phenotype-aliases", str(self.aliases), *extra]
        if case is not None:
            case_path = self.root / "case.json"
            write_json(case_path, case)
            argv += ["--case", str(case_path)]
        upstream = ({"sample_id": "TEST"}, {}, {"frequency_policy": {}}, {})
        with patch("egene.disease.validate_annotation", return_value=upstream), contextlib.redirect_stdout(io.StringIO()):
            result = disease.prioritize(disease.argument_parser().parse_args(argv))
        output = self.root / "output with spaces"
        return result, json.loads((output / "disease_candidates.json").read_text())


class PhenotypeTests(DiseaseFixture):
    def test_alias_alt_id_and_explicit_negation_are_resolved(self):
        case = {"sample_id": "TEST", "phenotypes": [{"label": "癫痫", "observed": True}, {"id": "HP:0000365", "observed": False}]}
        resolved = resolve_case(case, self.ontology, {"癫痫": "HP:9999999"})
        self.assertEqual(resolved["positive_hpo_ids"], ["HP:0001250"])
        self.assertEqual(resolved["negative_hpo_ids"], ["HP:0000365"])

    def test_unknown_label_is_retained_and_narrative_is_not_invented(self):
        case = {"sample_id": "TEST", "clinical_description": "无癫痫", "phenotypes": [{"label": "Unrecognized finding", "observed": True}]}
        resolved = resolve_case(case, self.ontology, {})
        self.assertFalse(resolved["positive_hpo_ids"])
        self.assertEqual(len(resolved["unresolved_entries"]), 1)
        self.assertFalse(resolved["clinical_description_interpreted"])

    def test_contradictory_patient_phenotypes_fail(self):
        with self.assertRaisesRegex(ValueError, "同时肯定和否定"):
            resolve_case({"sample_id": "TEST", "phenotypes": [{"id": "HP:0001250", "observed": True}, {"id": "HP:0001250", "observed": False}]}, self.ontology, {})

    def test_similarity_uses_only_phenotypes_and_penalizes_explicit_absence(self):
        scorer = PhenotypeScorer(self.database, self.ontology)
        resolved = resolve_case({"sample_id": "TEST", "phenotypes": [{"id": "HP:0001250", "observed": True}]}, self.ontology, {})
        seizure = scorer.score(resolved, self.database.annotations("OMIM:100001"))
        hearing = scorer.score(resolved, self.database.annotations("OMIM:100002"))
        self.assertGreater(seizure["score"], hearing["score"])
        self.assertEqual(len(seizure["matches"]), 1)
        resolved["negative_hpo_ids"] = ["HP:0000365"]
        conflict = scorer.score(resolved, self.database.annotations("OMIM:100002"))
        self.assertTrue(conflict["contradictions"])

    def test_gene_aliases_are_unique_and_ambiguous_aliases_are_not_guessed(self):
        self.assertEqual(self.database.resolve_gene("OLD1")["symbol"], "GENE1")
        self.assertEqual(self.database.resolve_gene("AMB")["status"], "ambiguous_alias")


class InheritanceTests(unittest.TestCase):
    def family(self, variants, **extras):
        return prepare_family({"family": extras}, {row["normalized_id"] for row in variants})

    def test_unphased_variants_are_not_assumed_compound_heterozygous(self):
        variants = [compact(100), compact(200)]
        result = evaluate_inheritance([{"mode": "AR"}], variants, {}, self.family(variants))
        self.assertEqual(result["status"], "possible_biallelic_phase_unknown")

    def test_same_phase_set_distinguishes_cis_and_trans(self):
        variants = [compact(100, gt="0|1", phase="42"), compact(200, gt="0|1", phase="42")]
        family = self.family(variants)
        self.assertEqual(pair_phase(*variants, family)["relation"], "cis")
        variants[1]["patient"]["source_GT"] = "1|0"
        self.assertEqual(pair_phase(*variants, family)["relation"], "trans")
        variants[1]["patient"]["original_PS"] = "43"
        self.assertEqual(pair_phase(*variants, family)["relation"], "unknown")

    def test_two_alt_alleles_from_original_one_two_gt_are_trans(self):
        variants = [compact(100, gt="1/2", alt="C", alt_index=1), compact(100, gt="1/2", alt="G", alt_index=2)]
        self.assertEqual(pair_phase(*variants, self.family(variants))["relation"], "trans")

    def test_single_recessive_pathogenic_allele_is_carrier_possibility(self):
        variants = [compact()]
        result = evaluate_inheritance([{"mode": "AR"}], variants, {}, self.family(variants))
        self.assertIn("single_heterozygous", result["status"])
        self.assertTrue(result["evaluations"][0]["carrier_possible"])
        self.assertFalse(result["diagnosis_established"])

    def test_homozygous_vus_is_compatible_without_becoming_pathogenic(self):
        variants = [compact(gt="1/1", label="Uncertain significance")]
        result = evaluate_inheritance([{"mode": "AR"}], variants, {}, self.family(variants))
        self.assertEqual(result["status"], "compatible_homozygous")
        self.assertEqual(result["priority_band"], 2)
        self.assertEqual(variants[0]["classification"], "Uncertain significance")

    def test_missing_parent_is_unknown_and_confirmed_calls_do_not_assign_ps2(self):
        variants = [compact()]
        identifier = variants[0]["normalized_id"]
        reference = {"gt": "0/0", "callable": True, "basis": "Synthetic reviewed full-coverage call"}
        family = self.family(variants, relationships_confirmed=True, genotypes=[{"normalized_id": identifier, "mother": reference}])
        self.assertIn("incomplete", family_observation(identifier, family)["status"])
        family = self.family(variants, relationships_confirmed=True, genotypes=[{"normalized_id": identifier, "mother": reference, "father": reference}])
        observation = family_observation(identifier, family)
        self.assertIn("confirmed_relationships", observation["status"])
        self.assertFalse(observation["acmg_evidence_assigned"])

    def test_unreadable_parental_call_is_not_reference_evidence(self):
        variants = [compact()]
        identifier = variants[0]["normalized_id"]
        family = self.family(variants, genotypes=[{"normalized_id": identifier, "mother": {"gt": "0/0", "callable": False}}])
        self.assertIn("incomplete", family_observation(identifier, family)["status"])

    def test_contradictory_explicit_phase_fails(self):
        variants = [compact(100, gt="0|1", phase="42"), compact(200, gt="0|1", phase="42")]
        family = self.family(variants, phase=[{"variant_ids": [row["normalized_id"] for row in variants], "relation": "trans", "basis": "synthetic contradictory assertion"}])
        with self.assertRaisesRegex(ValueError, "互相矛盾"):
            pair_phase(*variants, family)

    def test_confirmed_parental_origin_resolves_trans_and_cis(self):
        variants = [compact(100), compact(200)]
        reference = {"gt": "0/0", "callable": True, "basis": "synthetic reviewed call"}
        alternate = {"gt": "0/1", "callable": True, "basis": "synthetic reviewed call"}
        calls = [{"normalized_id": variants[0]["normalized_id"], "mother": alternate, "father": reference},
                 {"normalized_id": variants[1]["normalized_id"], "mother": reference, "father": alternate}]
        family = self.family(variants, relationships_confirmed=True, genotypes=calls)
        self.assertEqual(pair_phase(*variants, family)["relation"], "trans")
        calls[1].update(mother=alternate, father=reference)
        family = self.family(variants, relationships_confirmed=True, genotypes=calls)
        self.assertEqual(pair_phase(*variants, family)["relation"], "cis")

    def test_homozygous_child_with_reference_parents_is_not_simple_de_novo(self):
        variants = [compact(gt="1/1")]
        identifier = variants[0]["normalized_id"]
        reference = {"gt": "0/0", "callable": True, "basis": "synthetic reviewed call"}
        family = self.family(variants, relationships_confirmed=True, genotypes=[{"normalized_id": identifier, "mother": reference, "father": reference}])
        self.assertEqual(family_observation(identifier, family, variants[0])["status"], "mendelian_inconsistency_requires_review")

    def test_x_linked_PAR_and_heterozygous_unknown_sex_are_unresolved(self):
        variants = [compact(10001, chrom="chrX", gt="1")]
        result = evaluate_inheritance([{"mode": "XLR"}], variants, {"sex": "male"}, self.family(variants))
        self.assertFalse(result["status"].startswith("compatible"))
        variants = [compact(10000000, chrom="chrX")]
        result = evaluate_inheritance([{"mode": "XLR"}], variants, {}, self.family(variants))
        self.assertFalse(result["status"].startswith("compatible"))


class PipelineTests(DiseaseFixture):
    def test_full_pipeline_ranks_phenotype_and_preserves_disease_specific_flags(self):
        result, rows = self.run_pipeline([variant()], {"schema_version": "1.0", "sample_id": "TEST", "phenotypes": [{"label": "癫痫", "observed": True}]})
        self.assertEqual(rows[0]["disease_id"], "OMIM:100001")
        self.assertEqual(rows[0]["phenotype_status"], "evaluated")
        self.assertGreater(rows[0]["phenotype_score"], rows[1]["phenotype_score"])
        self.assertTrue(rows[0]["variants"][0]["clinvar_disease_match"])
        self.assertFalse(rows[1]["variants"][0]["clinvar_disease_match"])
        self.assertFalse(result["acmg_classifications_modified"])
        self.assertIsNone(rows[0]["risk_probability"])
        self.assertEqual(result["counts"]["candidate_disease_gene_pairs"], 2)

    def test_no_phenotype_is_explicitly_unscored(self):
        _, rows = self.run_pipeline([variant()])
        self.assertTrue(rows)
        self.assertTrue(all(row["phenotype_score"] is None for row in rows))

    def test_benign_and_nearest_gene_are_audit_only(self):
        nearby = variant(200)
        nearby["annotation"]["Func.refGene"] = "intergenic"
        result, rows = self.run_pipeline([variant(label="Benign"), nearby])
        self.assertEqual(rows, [])
        self.assertGreater(result["counts"]["gene_disease_link_records"], 0)

    def test_background_vus_is_excluded_by_default(self):
        record = variant(label="Uncertain significance")
        record["triage"]["triage_route"] = "background"
        _, rows = self.run_pipeline([record])
        self.assertEqual(rows, [])

    def test_explicit_background_vus_inclusion_remains_uncertain(self):
        record = variant(label="Uncertain significance")
        record["triage"]["triage_route"] = "background"
        _, rows = self.run_pipeline([record], extra=["--include-background-vus"])
        self.assertTrue(rows)
        self.assertTrue(all(row["priority_band"] == 2 for row in rows))
        self.assertIn("vus_is_not_diagnostic_evidence", rows[0]["review_flags"])

    def test_empty_input_produces_valid_empty_results(self):
        result, rows = self.run_pipeline([])
        self.assertEqual(rows, [])
        self.assertEqual(result["counts"]["input_variants"], 0)

    def test_case_sample_mismatch_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "样本 ID 不一致"):
            self.run_pipeline([variant()], {"schema_version": "1.0", "sample_id": "OTHER"})

    def test_modified_acmg_output_is_rejected(self):
        path = self.make_manifest([variant()])
        (path.parent / "acmg_results.jsonl").write_text("changed\n")
        with self.assertRaisesRegex(ValueError, "第四步产物校验失败"):
            disease.validate_acmg(path)

    def test_family_schema_requires_basis_for_callable_parent(self):
        case = {"schema_version": "1.0", "sample_id": "TEST", "family": {"genotypes": [{"normalized_id": "GRCh38:chr1:100:A:G", "mother": {"gt": "0/0", "callable": True}}]}}
        with self.assertRaises(jsonschema.ValidationError):
            self.run_pipeline([variant()], case)


if __name__ == "__main__":
    unittest.main()
