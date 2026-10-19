"""Functional checks for evidence gating, pinned InterVar and patient identity."""
from __future__ import annotations

import contextlib
import csv
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from egene import annotation, intervar
from egene.common import checksum
from egene.frequency_evidence import EXTERNAL_FREQUENCIES, adapt_frequency
from egene.intervar_worker import install_scalar_adapter


class FrequencyTests(unittest.TestCase):
    def setUp(self):
        self.source = {"normalized_id": "GRCh38:chr1:123:A:G", "matched_pop": "EAS",
                       "matched_pop_AF": "0.9", "global_AF": "0.1", "af_status": "available"}
        self.annotation = dict.fromkeys(EXTERNAL_FREQUENCIES, ".")
        self.annotation["gnomAD_genome_ALL"] = "0.0001"
        self.rule = {"context": "TEST disease", "basis": "explicit test threshold; not a clinical recommendation",
                     "population_adequacy_confirmed": True, "exceptions_reviewed": True,
                     "ba1_threshold": 0.05, "bs1_threshold": 0.005}
        self.policy = {"schema_version": "1.0", "variants": {self.source["normalized_id"]: self.rule}}

    def adapt(self, *, permission=True, exception=False):
        return adapt_frequency(self.source, self.annotation, self.policy, permission=permission,
                               historical_exception=exception)

    def test_explicit_supported_thresholds_generate_real_overrides(self):
        self.assertEqual(self.adapt()["overrides"], {"BA1": 1, "BS1": 1, "PM2": 0})
        self.assertEqual(self.adapt()["decisions"][-1]["status"], "contradicted_by_supported_popgen_frequency")

    def test_permission_false_blocks_popgen_not_independent_sources(self):
        result = self.adapt(permission=False)
        self.assertEqual(result["overrides"], {})
        self.assertEqual(result["external_frequencies"]["gnomAD_genome_ALL"], 0.0001)

    def test_default_policy_does_not_invent_a_universal_disease_threshold(self):
        self.policy["variants"] = {}
        self.assertEqual(self.adapt()["decisions"][0]["status"], "threshold_not_provided")
        self.assertEqual(self.adapt()["overrides"], {})

    def test_historical_exception_cannot_be_reenabled_by_policy(self):
        self.assertEqual(self.adapt(exception=True)["overrides"], {})
        self.assertEqual(self.adapt(exception=True)["decisions"][0]["status"], "historical_frequency_exception")

    def test_adequacy_and_exception_review_are_required(self):
        self.rule["population_adequacy_confirmed"] = False
        self.assertEqual(self.adapt()["overrides"], {})
        self.rule["population_adequacy_confirmed"] = True
        self.rule["exceptions_reviewed"] = False
        self.assertEqual(self.adapt()["overrides"], {})

    def test_missing_lookup_is_unknown_and_never_positive_pm2(self):
        self.source.update(matched_pop_AF="", af_status="missing")
        self.annotation = dict.fromkeys(EXTERNAL_FREQUENCIES, ".")
        result = self.adapt()
        self.assertIsNone(result["matched_pop_AF"])
        self.assertEqual(result["overrides"], {"PM2": 0})
        self.assertEqual(result["decisions"][-1]["status"], "insufficient_coverage_evidence")

    def test_genuine_zero_is_distinct_from_unknown(self):
        self.source["matched_pop_AF"] = "0"
        self.annotation["gnomAD_genome_ALL"] = "0"
        self.assertEqual(self.adapt()["matched_pop_AF"], 0.0)
        self.assertEqual(self.adapt()["overrides"], {})

    def test_ba1_is_strict_and_bs1_inclusive_at_explicit_threshold(self):
        self.source["matched_pop_AF"] = "0.05"
        self.rule["bs1_threshold"] = 0.05
        self.assertEqual(self.adapt()["overrides"], {"BS1": 1, "PM2": 0})

    def test_invalid_frequency_and_status_fail_closed(self):
        for value in ("nan", "inf", "-0.1", "1.1", "unknown"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.source["matched_pop_AF"] = value
                self.adapt()
        self.source.update(matched_pop_AF="0.1", af_status="missing")
        with self.assertRaises(ValueError):
            self.adapt()


class PinnedClassifierTests(unittest.TestCase):
    def setUp(self):
        path = ROOT / "vendor/InterVar/Intervar.py"
        if not path.is_file():
            self.skipTest("pinned InterVar is not installed")
        spec = importlib.util.spec_from_file_location("test_intervar_vendor", path)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        evidence = Path(self.temp.name) / "evidence.tsv"
        evidence.write_text("1\t123\tA\tG\tBA1=1\n")
        self.module.paras = {"evidence_file": str(evidence), "exclude_snps": str(evidence) + ".absent"}
        for prefix, size in (("PVS", 1), ("PS", 4), ("PM", 6), ("PP", 5), ("BA", 1), ("BS", 4), ("BP", 7)):
            for i in range(1, size + 1):
                setattr(self.module, "check_" + prefix + str(i), lambda *args: 0)
        self.allele = dict(zip(("Chr", "Start", "End", "Ref", "Alt"), range(5)))

    def assign(self, evidence):
        self.module.user_evidence_dict = {"1_123_A_G": evidence}
        return self.module.assign("UNK", "1\t123\t123\tA\tG", {}, {}, self.allele)

    def test_actual_vendor_ba1_override_is_fixed_without_source_edits(self):
        before = self.assign("BA1=1")
        self.assertEqual(intervar.parse_evidence(before)[0], "Uncertain significance")
        counts = install_scalar_adapter(self.module)
        after = self.assign("BA1=1")
        self.assertEqual(intervar.parse_evidence(after)[0], "Benign")
        self.assertEqual(counts["BA1"], 1)

    def test_actual_vendor_pvs1_override_is_fixed(self):
        install_scalar_adapter(self.module)
        result = self.assign("PVS1=1;PS1=1")
        label, evidence = intervar.parse_evidence(result)
        self.assertEqual(label, "Pathogenic")
        self.assertEqual(evidence["PVS1"], 1)
        self.assertEqual(len(evidence), 28)

    def test_parser_rejects_malformed_labels_arrays_and_extra_criteria(self):
        valid = self.assign("BA1=0")
        for text in ("Pathogenic", valid.replace("PS=[0, 0, 0, 0, 0]", "PS=[True, 0, 0, 0, 0]"),
                     valid.replace("PS=[0, 0, 0, 0, 0]", "PS=[0, 0, 0, 0, 1]")):
            with self.subTest(text=text), self.assertRaises(ValueError):
                intervar.parse_evidence(text)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        if not (ROOT / "vendor/InterVar/Intervar.py").is_file():
            self.skipTest("pinned InterVar is not installed")
        self.temp = tempfile.TemporaryDirectory(prefix="intervar test ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.prepared = self.root / "prepared"
        self.prepared.mkdir()
        self.annotated = self.root / "annotated"
        self.annotated.mkdir()

    def fixture(self, *, background=False, permission=True, empty=False):
        variants = [] if empty else [
            ("chr1", "123", "123", "A", "G", "GRCh38:chr1:123:A:G", "TEST1;TEST2", "0.01"),
            ("chr2", "235", "235", "A", "-", "GRCh38:chr2:234:CA:C", "NONE,NONE", "."),
        ]
        sources, annotations = [], []
        first = ["Chr", "Start", "End", "Ref", "Alt", "Func.refGene", "Gene.refGene", "GeneDetail.refGene", "ExonicFunc.refGene", "AAChange.refGene"]
        header = list(dict.fromkeys(first + annotation.REQUIRED_ANNOTATION + EXTERNAL_FREQUENCIES + ["SIFT_score", "CADD_raw", "CADD_phred"]))
        for i, (chrom, start, end, ref, alt, normalized, gene, af) in enumerate(variants):
            source = {"sample_id": "TEST", "record_id": str(i + 1), "alt_index": "1", "decision": "retained",
                      "normalized_id": normalized, "ANNOVAR_CHROM": chrom, "ANNOVAR_START": start, "ANNOVAR_END": end,
                      "ANNOVAR_REF": ref, "ANNOVAR_ALT": alt, "matched_pop": "EAS", "matched_pop_AF": "0.9",
                      "global_AF": "0.1", "af_status": "available", "use_for_acmg_ba1_bs1": str(permission).lower(),
                      "source_GT": "0|1", "original_DP": "37", "original_PS": "100", "quality_missing": '[]'}
            row = dict.fromkeys(header, ".")
            row.update(dict(zip(first[:5], (chrom, start, end, ref, alt))))
            row.update({"Func.refGene": "exonic", "Gene.refGene": gene, "ExonicFunc.refGene": "nonsynonymous SNV",
                        "AAChange.refGene": "TEST:NM_000001:exon1:c.1A>G:p.K1R",
                        "Otherinfo1": "het", "Otherinfo2": ".", "Otherinfo3": "37", "gnomAD_genome_ALL": af})
            sources.append(source)
            annotations.append(row)
        with (self.prepared / "patient_variants.tsv").open("w", newline="") as f:
            names = list(sources[0]) if sources else ["sample_id", "normalized_id", "ANNOVAR_CHROM", "ANNOVAR_START", "ANNOVAR_END", "ANNOVAR_REF", "ANNOVAR_ALT", "use_for_acmg_ba1_bs1", "af_status", "matched_pop_AF", "matched_pop"]
            w = csv.DictWriter(f, fieldnames=names, delimiter="\t"); w.writeheader(); w.writerows(sources)
        (self.prepared / "patient.avinput").write_text("".join("\t".join([s["ANNOVAR_" + k] for k in ("CHROM", "START", "END", "REF", "ALT")] + ["het", ".", "37"]) + "\n" for s in sources))
        (self.prepared / "input_qc.json").write_text(json.dumps({"warnings": []}))
        for name in ("normalized.vcf.gz", "normalized.vcf.gz.tbi", "source_records.tsv", "variant_mapping.tsv", "allele_freq.tsv", "reference_mismatches.tsv"):
            (self.prepared / name).write_text("fixture\n")
        freq = {"lookup_population": "EAS", "use_for_acmg_ba1_bs1": permission, "missing_AF_semantics": "unknown_not_zero", "classification_performed": False}
        prepared = {"schema_version": "1.0", "status": "complete", "stage": "prepare_input", "producer": {}, "sample_id": "TEST", "assembly": "GRCh38", "annovar_build": "hg38",
                    "inputs": {"evidence_pack": {}, "patient_vcf": {}, "allele_frequency": {}}, "reference": {"path": "fixture.fa", "sha256": "0" * 64, "fai_sha256": "0" * 64},
                    "tools": {"bcftools_version": "fixture", "convert2annovar_sha256": "0" * 64}, "frequency_policy": freq,
                    "counts": {"input_records": len(sources), "input_alleles": len(sources), "frequency_rows": len(sources), "retained_variants": len(sources)},
                    "files": self.files(self.prepared)}
        prep_path = self.prepared / "input_manifest.json"
        prep_path.write_text(json.dumps(prepared))
        (self.prepared / "status.json").write_text(json.dumps({"status": "complete", "stage": "prepare_input"}))
        raw = self.annotated / "raw/annovar.hg38_multianno.txt"
        raw.parent.mkdir()
        with raw.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=header, delimiter="\t"); w.writeheader(); w.writerows(annotations)
        with (self.annotated / "annotated_variants.jsonl").open("w") as f:
            for source, row in zip(sources, annotations):
                f.write(json.dumps({"normalized_id": source["normalized_id"], "patient": source, "annotation": row,
                                    "triage": {"triage_route": "background" if background else "candidate"}}) + "\n")
        for name in ("all_variants.tsv", "candidate_variants.tsv", "priority_variants.tsv", "review_variants.tsv", "candidate.avinput", "candidate.hg38_multianno.txt", "annotation_summary.json", "database_snapshot.json", "triage_policy.json"):
            (self.annotated / name).write_text("{}\n")
        anno = {"schema_version": "1.0", "status": "complete", "stage": "annotate_variants", "producer": {}, "sample_id": "TEST", "assembly": "GRCh38", "annovar_build": "hg38",
                "prepared_manifest": {"path": str(prep_path), "sha256": checksum(prep_path)},
                "counts": {"annotated_variants": len(sources), "candidate_variants": 0 if background else len(sources), "priority_variants": 0, "review_variants": 0, "background_variants": len(sources) if background else 0},
                "classification_performed": False, "database_snapshot_sha256": checksum(self.annotated / "database_snapshot.json"),
                "triage_policy_sha256": checksum(self.annotated / "triage_policy.json"), "frequency_policy": freq, "files": self.files(self.annotated)}
        path = self.annotated / "annotation_manifest.json"
        path.write_text(json.dumps(anno))
        (self.annotated / "status.json").write_text(json.dumps({"status": "complete", "stage": "annotate_variants"}))
        return path

    @staticmethod
    def files(root):
        return {str(p.relative_to(root)): {"path": str(p.relative_to(root)), "bytes": p.stat().st_size, "sha256": checksum(p)}
                for p in root.rglob("*") if p.is_file()}

    def args(self, manifest, scope="all", policy=None):
        argv = ["--annotation-manifest", str(manifest), "--outdir", str(self.root / "output with spaces"), "--scope", scope]
        if policy:
            argv += ["--frequency-policy", str(policy)]
        return intervar.argument_parser().parse_args(argv)

    def test_real_intervar_overrides_indels_gene_multiplicity_and_patient_quality(self):
        manifest = self.fixture()
        policy = self.root / "policy.json"
        policy.write_text(json.dumps({"schema_version": "1.0", "variants": {"GRCh38:chr1:123:A:G": {
            "context": "TEST disease", "basis": "functional test only", "population_adequacy_confirmed": True,
            "exceptions_reviewed": True, "ba1_threshold": 0.05}}}))
        with contextlib.redirect_stdout(io.StringIO()):
            result = intervar.classify(self.args(manifest, policy=policy))
        self.assertEqual(result["counts"]["selected_variants"], 2)
        self.assertEqual(result["counts"]["gene_context_records"], 4)
        records = [json.loads(line) for line in (self.root / "output with spaces/acmg_results.jsonl").read_text().splitlines()]
        snv = [r for r in records if r["normalized_id"] == "GRCh38:chr1:123:A:G"]
        self.assertTrue(all(r["integrated"]["classification"] == "Benign" and r["integrated"]["evidence"]["BA1"] == 1 for r in snv))
        deletion = [r for r in records if r["normalized_id"] == "GRCh38:chr2:234:CA:C"]
        self.assertEqual([r["gene_occurrence"] for r in deletion], [1, 2])
        self.assertTrue(all(r["patient"]["source_GT"] == "0|1" and r["patient"]["original_DP"] == "37" for r in records))
        self.assertTrue(all(r["integrated"]["evidence"]["PM2"] == 0 and r["raw"]["evidence"]["PM2"] == 1 for r in deletion))
        self.assertIn("\n2\t235\tA\t-\tPM2=0\n", (self.root / "output with spaces/evidence_overrides.tsv").read_text())

    def test_empty_candidate_selection_skips_engine_and_remains_valid(self):
        manifest = self.fixture(background=True)
        with contextlib.redirect_stdout(io.StringIO()), patch("egene.intervar.subprocess.run", wraps=__import__("subprocess").run) as run:
            result = intervar.classify(self.args(manifest, scope="candidates"))
        self.assertFalse(result["classification_performed"])
        self.assertEqual(result["counts"]["gene_context_records"], 0)
        self.assertFalse(any("--script" in call.args[0] for call in run.call_args_list))

    def test_empty_prepared_input_produces_empty_outputs(self):
        manifest = self.fixture(empty=True)
        with contextlib.redirect_stdout(io.StringIO()):
            result = intervar.classify(self.args(manifest))
        self.assertEqual(result["counts"]["selected_variants"], 0)

    def test_modified_input_is_rejected(self):
        manifest = self.fixture()
        (self.annotated / "annotated_variants.jsonl").write_text("changed\n")
        with self.assertRaisesRegex(ValueError, "第三步产物校验失败"):
            intervar.classify(self.args(manifest))

    def test_unknown_policy_variant_fails_without_success_manifest(self):
        manifest = self.fixture()
        policy = self.root / "policy.json"
        policy.write_text(json.dumps({"schema_version": "1.0", "variants": {"GRCh38:chr9:123:A:G": {
            "context": "TEST", "basis": "test", "population_adequacy_confirmed": True,
            "exceptions_reviewed": True, "ba1_threshold": 0.05}}}))
        with self.assertRaisesRegex(ValueError, "不存在的变异"):
            intervar.classify(self.args(manifest, policy=policy))
        out = self.root / "output with spaces"
        self.assertEqual(json.loads((out / "status.json").read_text())["status"], "failed")
        self.assertFalse((out / "acmg_manifest.json").exists())

    def test_existing_results_are_not_overwritten(self):
        manifest = self.fixture()
        (self.root / "output with spaces").mkdir()
        with self.assertRaisesRegex(ValueError, "拒绝覆盖"):
            intervar.classify(self.args(manifest))


if __name__ == "__main__":
    unittest.main()
