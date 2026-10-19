"""Final-delivery checks: coverage, unchanged evidence, HTML safety and packaging."""
from __future__ import annotations

import contextlib
import copy
import csv
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from egene import pipeline, reporting
from egene.common import checksum, write_json
import test_intervar as upstream_fixture


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.remote_resources = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and "href" in attrs:
            self.links.append(attrs["href"])
        if tag in {"script", "link", "img", "iframe"} and (attrs.get("src") or attrs.get("href")):
            self.remote_resources.append(attrs.get("src", attrs.get("href")))


class ReportFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="eGene delivery test ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.prepared = self.root / "prepared"
        self.prepared.mkdir()
        self.annotated = self.root / "annotated"
        self.annotated.mkdir()

    @staticmethod
    def files(root):
        return {str(p.relative_to(root)): {"path": str(p.relative_to(root)), "bytes": p.stat().st_size, "sha256": checksum(p)}
                for p in root.rglob("*") if p.is_file() and p.name not in {"status.json", "acmg_manifest.json", "disease_manifest.json"}}

    def fixture(self, *, empty=False, unclassified=False, candidate=False):
        annotation_path = upstream_fixture.PipelineTests.fixture(self, empty=empty)
        annotation = json.loads(annotation_path.read_text())
        prepared_path = self.prepared / "input_manifest.json"
        prepared = json.loads(prepared_path.read_text())
        source_snapshot = self.prepared / "popgen_evidence_pack.json"
        write_json(source_snapshot, {"synthetic_fixture": True})
        prepared["files"][source_snapshot.name] = {"path": source_snapshot.name, "bytes": source_snapshot.stat().st_size, "sha256": checksum(source_snapshot)}
        write_json(prepared_path, prepared)
        annotation["prepared_manifest"]["sha256"] = checksum(prepared_path)
        write_json(annotation_path, annotation)
        with (self.prepared / "patient_variants.tsv").open(newline="") as f:
            sources = list(csv.DictReader(f, delimiter="\t"))
        annotations = [json.loads(line) for line in (self.annotated / "annotated_variants.jsonl").read_text().splitlines()]
        acmg_dir = self.root / "acmg"
        acmg_dir.mkdir()
        labels = ["Pathogenic", "Uncertain significance", "Benign", "Benign"]
        records = []
        if not unclassified:
            for item in annotations:
                occurrences = {}
                for gene in item["annotation"]["Gene.refGene"].replace(";", ",").split(","):
                    occurrences[gene] = occurrences.get(gene, 0) + 1
                    label = labels[len(records)]
                    records.append({**item, "gene": gene, "gene_occurrence": occurrences[gene],
                        "raw": {"classification": label}, "integrated": {"classification": label, "evidence": {"PVS1": int(label == "Pathogenic"), "BA1": int(label == "Benign")}},
                        "evidence_changes": {}, "data_flags": []})
        (acmg_dir / "acmg_results.jsonl").write_text("".join(json.dumps(row) + "\n" for row in records))
        for name in ("acmg_results.tsv", "acmg_summary.json", "frequency_policy.json", "frequency_evidence.jsonl", "evidence_overrides.tsv", "intervar_snapshot.json", "database_snapshot.json", "execution.json"):
            (acmg_dir / name).write_text('{}\n')
        manifest = {"schema_version": "1.0", "status": "complete", "stage": "classify_variants", "producer": {}, "sample_id": "TEST", "assembly": "GRCh38", "annovar_build": "hg38",
            "annotation_manifest": {"path": str(annotation_path), "sha256": checksum(annotation_path)},
            "classifier": {"name": "InterVar", "version": "synthetic fixture", "commit": "fixture", "guidelines": "ACMG-AMP 2015", "vendor_modified": False},
            "scope": "candidates" if unclassified else "all", "counts": {"selected_variants": len({row['normalized_id'] for row in records}), "gene_context_records": len(records), "classification_changed_variants": 0, "evidence_changed_variants": 0},
            "classification_performed": bool(records), "phenotype_and_inheritance_evaluated": False, "frequency_policy": prepared["frequency_policy"], "files": self.files(acmg_dir)}
        acmg_path = acmg_dir / "acmg_manifest.json"
        write_json(acmg_path, manifest)
        write_json(acmg_dir / "status.json", {"status": "complete", "stage": "classify_variants"})
        directory = self.root / "disease"
        directory.mkdir()
        case = {"schema_version": "1.0", "sample_id": "TEST", "sex": "unknown", "clinical_description": "synthetic fixture only", "phenotypes": []}
        normalized = {"sample_id": "TEST", "sex": "unknown", "positive_hpo_ids": [], "negative_hpo_ids": [], "resolved_entries": [], "unresolved_entries": [], "status": "no_resolved_positive_phenotypes"}
        for name, payload in [("case.json", case), ("phenotypes.normalized.json", normalized), ("disease_policy.json", {}),
            ("disease_database_snapshot.json", {"hpo_release": "synthetic", "hgnc_release": "synthetic"}), ("disease_summary.json", {"limitations": []})]:
            write_json(directory / name, payload)
        candidates = []
        if candidate:
            candidates = [{"rank": 1, "candidate_id": "OMIM:100001|TEST1", "disease_id": "OMIM:100001", "disease_name": "Synthetic condition", "gene": "TEST1",
                "inheritance_status": "compatible_monoallelic", "phenotype_score": None, "supporting_variant_ids": [sources[0]["normalized_id"]],
                "inheritance": {"status": "compatible_monoallelic"}, "phenotype": {"score": None}, "association_sources": [], "review_flags": ["mechanism_requires_review"],
                "variants": [{"normalized_id": sources[0]["normalized_id"], "classification": "Pathogenic", "patient": sources[0], "consequence": {"AAChange.refGene": "synthetic"}}]}]
        write_json(directory / "disease_candidates.json", candidates)
        for name in ("variant_disease_links.jsonl", "variant_disease_links.tsv", "disease_candidates.jsonl", "disease_candidates.tsv", "carrier_findings.tsv"):
            (directory / name).write_text("synthetic fixture\n")
        disease = {"schema_version": "1.0", "status": "complete", "stage": "prioritize_diseases", "sample_id": "TEST", "assembly": "GRCh38", "producer": {},
            "counts": {"input_variants": manifest["counts"]["selected_variants"], "gene_context_records": len(records), "candidate_disease_gene_pairs": len(candidates),
                "distinct_candidate_diseases": len(candidates), "carrier_findings": 0, "phenotype_evaluated_candidates": 0, "inheritance_compatible_candidates": len(candidates), "unresolved_patient_phenotypes": 0},
            "acmg_manifest": {"path": str(acmg_path), "sha256": checksum(acmg_path)}, "disease_database": {}, "case_input": {"provided": False},
            "acmg_classifications_modified": False, "phenotype_status": normalized["status"], "files": self.files(directory)}
        self.disease_path = directory / "disease_manifest.json"
        write_json(self.disease_path, disease)
        write_json(directory / "status.json", {"status": "complete", "stage": "prioritize_diseases"})
        return self.disease_path

    def generate(self, **kwargs):
        path = self.fixture(**kwargs)
        destination = self.root / "delivery"
        with contextlib.redirect_stdout(io.StringIO()):
            result = reporting.generate(reporting.argument_parser().parse_args(["--disease-manifest", str(path), "--outdir", str(destination), "--preview-limit", "1"]))
        return destination, result, json.loads((destination / "report.json").read_text())


class ReportTests(ReportFixture):
    def test_counts_distinguish_variants_gene_contexts_and_display_labels(self):
        destination, manifest, report = self.generate()
        counts = report["variant_statistics"]["counts"]
        self.assertEqual(counts["retained_variants"], 2)
        self.assertEqual(counts["acmg_gene_contexts"], 4)
        self.assertEqual(counts["variants_with_plp_context"], 1)
        self.assertEqual(counts["variants_with_vus_context"], 1)
        self.assertEqual(len(report["variant_statistics"]["preview"]), 1)
        with (destination / "variants.tsv").open() as f:
            rows = list(csv.DictReader(f, delimiter="\t"))
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(json.loads(rows[0]["acmg_gene_contexts"])), 2)
        self.assertEqual(json.loads(rows[1]["acmg_gene_contexts"])[1]["occurrence"], 2)
        self.assertFalse(report["analysis_scope"]["classification_labels_modified"])
        self.assertIsNone(report["conclusion"]["risk_probability"])

    def test_candidate_preview_has_supporting_variants_and_sources(self):
        destination, _, report = self.generate(candidate=True)
        html = (destination / "report.html").read_text()
        self.assertIn("Synthetic condition", html)
        self.assertIn("mechanism_requires_review", html)
        self.assertEqual(len(report["disease_candidates"]), 1)

    def test_unclassified_variants_do_not_become_benign_or_vus(self):
        _, _, report = self.generate(unclassified=True)
        self.assertEqual(report["variant_statistics"]["counts"]["variants_not_classified"], 2)
        self.assertEqual(report["variant_statistics"]["variant_display_priority_classifications"], {"not_evaluated": 2})
        self.assertIn("没有变异完成", report["conclusion"]["finding"])

    def test_empty_analysis_still_has_complete_report_and_tables(self):
        destination, _, report = self.generate(empty=True)
        self.assertEqual(report["variant_statistics"]["counts"]["retained_variants"], 0)
        self.assertTrue((destination / "report.html").is_file())
        with (destination / "variants.tsv").open() as f:
            self.assertEqual(len(list(csv.DictReader(f, delimiter="\t"))), 0)

    def test_html_escapes_patient_text_and_all_downloads_are_local_and_exist(self):
        destination, _, report = self.generate()
        report["case"]["clinical_description"] = '<script>alert("patient")</script><img src=x onerror=alert(1)>'
        html = reporting.render_html(report)
        self.assertNotIn('<script>alert("patient")', html)
        self.assertIn("&lt;script&gt;", html)
        parser = LinkParser()
        parser.feed(html)
        self.assertFalse(parser.remote_resources)
        self.assertTrue(all((destination / link).is_file() for link in parser.links))

    def test_changed_disease_file_is_rejected(self):
        path = self.fixture()
        (path.parent / "case.json").write_text("changed")
        with self.assertRaisesRegex(ValueError, "报告输入校验失败"):
            reporting.load_chain(path)

    def test_output_hashes_and_copied_acmg_evidence_are_unchanged(self):
        destination, manifest, _ = self.generate()
        for spec in manifest["files"].values():
            self.assertEqual(checksum(destination / spec["path"]), spec["sha256"])
        self.assertEqual(checksum(destination / "acmg_results.tsv"), checksum(self.root / "acmg/acmg_results.tsv"))


class UnifiedPipelineTests(ReportFixture):
    def args(self, path, *extra):
        return pipeline.argument_parser().parse_args(["--disease-manifest", str(path), "--outdir", str(self.root / "pipeline"), *extra])

    def test_reuse_runs_real_report_subprocess_and_produces_portable_zip(self):
        path = self.fixture()
        with contextlib.redirect_stdout(io.StringIO()):
            result = pipeline.run(self.args(path))
        self.assertEqual(len(result["commands"]), 1)
        self.assertEqual(result["commands"][0]["stage"], "generate_report")
        self.assertTrue(result["stages"]["4"]["reused"])
        self.assertFalse(result["stages"]["6"]["reused"])
        archive_path = self.root / "pipeline/delivery.zip"
        with zipfile.ZipFile(archive_path) as archive:
            self.assertIn("report.html", archive.namelist())
            self.assertIn("report_manifest.json", archive.namelist())
            self.assertTrue(all(not name.startswith("/") and ".." not in Path(name).parts for name in archive.namelist()))
            self.assertEqual(archive.read("report.json"), (self.root / "pipeline/delivery/report.json").read_bytes())

    def test_failed_stage_is_reported_without_success_or_zip(self):
        path = self.fixture()
        with patch("egene.pipeline.subprocess.run", return_value=subprocess.CompletedProcess([], 9)), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(ValueError, "退出码 9"):
                pipeline.run(self.args(path))
        status = json.loads((self.root / "pipeline/status.json").read_text())
        self.assertEqual(status["status"], "failed")
        self.assertEqual(status["failed_stage"], "generate_report")
        self.assertFalse((self.root / "pipeline/delivery.zip").exists())

    def test_reused_disease_result_rejects_silently_ignored_case(self):
        path = self.fixture()
        with self.assertRaisesRegex(ValueError, "不能改变病例"):
            pipeline.run(self.args(path, "--case", "different_case.json"))

    def test_source_selection_is_exclusive_and_stage_options_are_forwarded(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            pipeline.argument_parser().parse_args(["--popgen-pack", "a.json", "--disease-manifest", "b.json", "--outdir", "output"])
        args = pipeline.argument_parser().parse_args(["--popgen-pack", "input.json", "--outdir", "output", "--ref-mismatch", "exclude", "--min-dp", "21", "--threads", "3", "--acmg-scope", "candidates"])
        prep = pipeline.command_for(2, Path("input.json"), Path("output/02_input"), args)
        self.assertEqual(prep[prep.index("--min-dp") + 1], "21")
        self.assertEqual(prep[prep.index("--ref-mismatch") + 1], "exclude")
        annotation = pipeline.command_for(3, Path("prepared.json"), Path("output/03_annotation"), args)
        self.assertEqual(annotation[annotation.index("--threads") + 1], "3")
        acmg = pipeline.command_for(4, Path("annotation.json"), Path("output/04_acmg"), args)
        self.assertEqual(acmg[acmg.index("--scope") + 1], "candidates")


if __name__ == "__main__":
    unittest.main()
