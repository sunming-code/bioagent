"""Checks for annotation identity, evidence handling and candidate prioritization."""
from __future__ import annotations

import contextlib
import csv
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from egene import annotation
from egene.common import checksum
from egene.triage import clinvar_summary, prioritize

POLICY = json.loads((ROOT / "config/annotation_triage.json").read_text())


class TriageTests(unittest.TestCase):
    def source(self, af="0.0001"):
        return {"af_status": "available", "matched_pop_AF": af}

    def annotated(self, *, frequency="0.0001", function="exonic", exonic="nonsynonymous SNV", **extra):
        result = {"gnomAD_genome_ALL": frequency, "Func.refGene": function, "ExonicFunc.refGene": exonic,
                  "CLNSIG": ".", "CLNREVSTAT": "."}
        result.update(extra)
        return result

    def test_common_variant_deprioritized_without_benign_classification(self):
        result = prioritize(self.source("0.2"), self.annotated(frequency="0.3"), POLICY, frequency_permission=True)
        self.assertEqual(result["triage_route"], "background")
        self.assertEqual(result["acmg_classification"], "not_evaluated")

    def test_known_pathogenic_noncoding_common_variant_is_retained(self):
        row = self.annotated(frequency="0.2", function="intronic", exonic=".",
                             CLNSIG="Pathogenic/Likely_pathogenic", CLNREVSTAT="reviewed_by_expert_panel")
        result = prioritize(self.source("0.2"), row, POLICY, frequency_permission=True)
        self.assertEqual(result["triage_route"], "candidate")
        self.assertTrue(result["priority_review"])
        self.assertEqual(result["clinvar_review_stars"], 3)

    def test_conflict_does_not_become_pathogenic_by_substring_matching(self):
        row = self.annotated(frequency="0.2", CLNSIG="Conflicting_interpretations_of_pathogenicity",
                             CLNREVSTAT="criteria_provided,_conflicting_interpretations")
        self.assertFalse(clinvar_summary(row)["pathogenic_assertion"])
        result = prioritize(self.source("0.2"), row, POLICY, frequency_permission=True)
        self.assertEqual(result["triage_route"], "review")
        self.assertEqual(result["triage_kind"], "clinvar_conflict")

    def test_missing_frequency_is_unknown_not_zero_or_pm2(self):
        result = prioritize({"af_status": "missing", "matched_pop_AF": ""},
                            self.annotated(frequency="."), POLICY, frequency_permission=True)
        self.assertEqual(result["screen_frequency_status"], "unknown")
        self.assertIsNone(result["screen_max_AF"])
        self.assertEqual(result["acmg_classification"], "not_evaluated")
        self.assertEqual(result["triage_route"], "candidate")

    def test_genuine_zero_is_preserved(self):
        result = prioritize(self.source("0"), self.annotated(frequency="0"), POLICY, frequency_permission=True)
        self.assertEqual(result["screen_max_AF"], 0.0)
        self.assertEqual(result["screen_frequency_status"], "below_screen_cutoff")

    def test_population_permission_false_blocks_popgen_frequency_use(self):
        result = prioritize(self.source("0.9"), self.annotated(), POLICY, frequency_permission=False)
        self.assertNotIn("popgen_matched", result["screen_frequency_sources"])
        self.assertEqual(result["triage_route"], "candidate")

    def test_synonymous_is_not_misread_as_nonsynonymous(self):
        result = prioritize(self.source(), self.annotated(exonic="synonymous SNV"), POLICY, frequency_permission=True)
        self.assertEqual(result["triage_kind"], "consequence_deprioritized")

    def test_other_transcripts_are_not_dropped(self):
        row = self.annotated(function="intronic", exonic=".")
        row.update({"Func.ensGene": "exonic", "ExonicFunc.ensGene": "stopgain"})
        result = prioritize(self.source(), row, POLICY, frequency_permission=True)
        self.assertTrue(result["priority_review"])
        self.assertEqual(result["triage_route"], "candidate")

    def test_curated_exception_bypasses_common_frequency(self):
        result = prioritize(self.source("0.3"), self.annotated(frequency="0.3", function="intergenic", exonic="."),
                            POLICY, frequency_permission=True, curated_exception=True)
        self.assertEqual(result["triage_kind"], "curated_frequency_exception")
        self.assertTrue(result["priority_review"])

    def test_high_impact_common_or_benign_annotation_is_reviewed(self):
        row = self.annotated(frequency="0.3", exonic="stopgain",
                             CLNSIG="Benign/Likely_benign",
                             CLNREVSTAT="criteria_provided,_multiple_submitters,_no_conflicts")
        result = prioritize(self.source("0.3"), row, POLICY, frequency_permission=True)
        self.assertEqual(result["triage_kind"], "high_impact_contradiction")
        self.assertEqual(result["triage_route"], "review")

    def test_vus_is_not_promoted_to_pathogenic(self):
        row = self.annotated(CLNSIG="Uncertain_significance", CLNREVSTAT="criteria_provided,_single_submitter")
        result = prioritize(self.source(), row, POLICY, frequency_permission=True)
        self.assertEqual(result["triage_kind"], "protein_altering_candidate")
        self.assertEqual(result["acmg_classification"], "not_evaluated")

    def test_missing_function_annotation_is_reviewed(self):
        result = prioritize(self.source(), self.annotated(function=".", exonic="."),
                            POLICY, frequency_permission=True)
        self.assertEqual(result["triage_kind"], "annotation_incomplete")

    def test_non_mendelian_context_stays_separate(self):
        result = prioritize(self.source("0.3"), self.annotated(frequency="0.3", CLNSIG="drug_response"),
                            POLICY, frequency_permission=True)
        self.assertEqual(result["triage_route"], "review")
        self.assertFalse(result["priority_review"])


class AnnotationMappingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        self.prepared_dir = self.root / "prepared with spaces"
        self.prepared_dir.mkdir()
        self.sources = [
            {"sample_id": "TEST", "record_id": "1", "alt_index": "1", "decision": "retained",
             "normalized_id": "GRCh38:chr1:1:CA:C", "CHROM": "chr1", "POS": "1", "REF": "CA", "ALT": "C",
             "ANNOVAR_CHROM": "chr1", "ANNOVAR_START": "2", "ANNOVAR_END": "2", "ANNOVAR_REF": "A", "ANNOVAR_ALT": "-",
             "matched_pop": "EAS", "matched_pop_AF": "0.0001", "af_status": "available",
             "use_for_acmg_ba1_bs1": "false", "source_GT": "0|1", "original_PS": "6",
             "original_DP": "", "original_AD": ".", "quality_missing": '["DP","AD"]'},
            {"sample_id": "TEST", "record_id": "2", "alt_index": "1", "decision": "retained",
             "normalized_id": "GRCh38:chr2:234:A:G", "CHROM": "chr2", "POS": "234", "REF": "A", "ALT": "G",
             "ANNOVAR_CHROM": "chr2", "ANNOVAR_START": "234", "ANNOVAR_END": "234", "ANNOVAR_REF": "A", "ANNOVAR_ALT": "G",
             "matched_pop": "EAS", "matched_pop_AF": "", "af_status": "missing",
             "use_for_acmg_ba1_bs1": "false", "source_GT": "0/1", "original_PS": ".",
             "original_DP": "", "original_AD": ".", "quality_missing": '["DP","AD"]'},
        ]
        self.avinput = ["chr1\t2\t2\tA\t-\thet\t.\t.", "chr2\t234\t234\tA\tG\thet\t.\t."]

    def fixture(self, *, empty=False):
        sources = [] if empty else self.sources
        with (self.prepared_dir / "patient_variants.tsv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(self.sources[0]), delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows(sources)
        (self.prepared_dir / "patient.avinput").write_text("" if empty else "\n".join(self.avinput) + "\n")
        (self.prepared_dir / "input_qc.json").write_text(json.dumps({"warnings": ["fixture quality unknown"]}))
        for name in ("normalized.vcf.gz", "normalized.vcf.gz.tbi", "source_records.tsv", "variant_mapping.tsv",
                     "allele_freq.tsv", "reference_mismatches.tsv"):
            (self.prepared_dir / name).write_text("test fixture\n")
        files = {p.name: {"path": p.name, "bytes": p.stat().st_size, "sha256": checksum(p)}
                 for p in self.prepared_dir.iterdir()}
        manifest = {
            "schema_version": "1.0", "status": "complete", "stage": "prepare_input", "producer": {},
            "sample_id": "TEST", "assembly": "GRCh38", "annovar_build": "hg38",
            "inputs": {"evidence_pack": {}, "patient_vcf": {}, "allele_frequency": {}},
            "reference": {"path": "fixture.fa", "sha256": "0" * 64, "fai_sha256": "0" * 64},
            "tools": {"bcftools_version": "fixture", "convert2annovar_sha256": "0" * 64},
            "frequency_policy": {"lookup_population": "EAS", "use_for_acmg_ba1_bs1": False,
                                 "missing_AF_semantics": "unknown_not_zero", "classification_performed": False},
            "counts": {"input_records": len(sources), "input_alleles": len(sources),
                       "frequency_rows": len(sources), "retained_variants": len(sources)}, "files": files,
        }
        path = self.prepared_dir / "input_manifest.json"
        path.write_text(json.dumps(manifest))
        (self.prepared_dir / "status.json").write_text(json.dumps({"status": "complete", "stage": "prepare_input"}))
        return path

    def raw_table(self, target, *, missing_row=False, wrong_genotype=False):
        values = []
        for i, source in enumerate(self.sources):
            row = dict.fromkeys(annotation.REQUIRED_ANNOTATION, ".")
            row.update(dict(zip(("Chr", "Start", "End", "Ref", "Alt"),
                                [source["ANNOVAR_" + name] for name in ("CHROM", "START", "END", "REF", "ALT")])))
            # ANNOVAR can omit the chr prefix; indel Start is not VCF POS.
            row["Chr"] = row["Chr"].removeprefix("chr")
            row.update({"Func.refGene": "exonic", "Gene.refGene": "TESTGENE",
                        "ExonicFunc.refGene": "frameshift deletion" if i == 0 else "nonsynonymous SNV",
                        "Otherinfo1": "hom" if wrong_genotype else "het", "Otherinfo2": ".", "Otherinfo3": ".",
                        "gnomAD_genome_ALL": "0.0001" if i == 0 else "0.3"})
            values.append(row)
        with target.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=annotation.REQUIRED_ANNOTATION, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows(values[:1] if missing_row else values)

    def database(self):
        db = sqlite3.connect(self.root / "test.sqlite")
        db.row_factory = sqlite3.Row
        self.addCleanup(db.close)
        return db

    def test_indel_annotation_maps_back_to_original_genotype_and_quality(self):
        path = self.fixture()
        manifest, files = annotation.validate_prepared(path)
        db = self.database()
        source_header, count = annotation.load_sources(db, files, manifest)
        raw = self.root / "multianno.txt"
        self.raw_table(raw)
        anno_header, summary = annotation.parse_annotations(db, raw, manifest, POLICY, set(), count)
        out = self.root / "output"
        out.mkdir()
        annotation.export_results(db, out, source_header, anno_header)
        with (out / "all_variants.tsv").open() as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
        self.assertEqual(rows[0]["normalized_id"], "GRCh38:chr1:1:CA:C")
        self.assertEqual((rows[0]["Start"], rows[0]["POS"]), ("2", "1"))
        self.assertEqual((rows[0]["source_GT"], rows[0]["original_PS"], rows[0]["original_DP"]), ("0|1", "6", ""))
        self.assertEqual(summary["counts"]["annotated_variants"], 2)
        self.assertEqual(summary["counts"]["candidate_variants"], 1)
        self.assertEqual(summary["counts"]["priority_variants"], 1)
        self.assertEqual((out / "candidate.avinput").read_text(), self.avinput[0] + "\n")

    def test_missing_annotation_rows_are_rejected(self):
        manifest, files = annotation.validate_prepared(self.fixture())
        db = self.database()
        _, count = annotation.load_sources(db, files, manifest)
        raw = self.root / "multianno.txt"
        self.raw_table(raw, missing_row=True)
        with self.assertRaisesRegex(ValueError, "不完整"):
            annotation.parse_annotations(db, raw, manifest, POLICY, set(), count)

    def test_changed_genotype_is_rejected(self):
        manifest, files = annotation.validate_prepared(self.fixture())
        db = self.database()
        _, count = annotation.load_sources(db, files, manifest)
        raw = self.root / "multianno.txt"
        self.raw_table(raw, wrong_genotype=True)
        with self.assertRaisesRegex(ValueError, "Otherinfo"):
            annotation.parse_annotations(db, raw, manifest, POLICY, set(), count)

    def test_modified_prepared_file_is_rejected(self):
        path = self.fixture()
        (self.prepared_dir / "patient.avinput").write_text("modified\n")
        with self.assertRaisesRegex(ValueError, "校验失败"):
            annotation.validate_prepared(path)

    def test_empty_input_produces_valid_empty_outputs(self):
        path = self.fixture(empty=True)
        args = annotation.argument_parser().parse_args(["--prepared-manifest", str(path),
                                                       "--outdir", str(self.root / "empty output")])
        snapshot = {"scripts": {}, "databases": {}, "annotation_profile": "fixture"}
        with patch.object(annotation, "database_snapshot", return_value=snapshot), \
                patch.object(annotation, "frequency_exceptions", return_value=(set(), {})), \
                contextlib.redirect_stdout(io.StringIO()):
            result = annotation.annotate(args)
        self.assertEqual(result["counts"]["candidate_variants"], 0)
        self.assertEqual(result["counts"]["annotated_variants"], 0)
        self.assertFalse(result["classification_performed"])
        self.assertTrue((self.root / "empty output/annotation_manifest.json").is_file())
        self.assertEqual((self.root / "empty output/candidate.avinput").read_text(), "")


if __name__ == "__main__":
    unittest.main()
