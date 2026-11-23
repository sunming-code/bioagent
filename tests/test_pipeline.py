"""Integration boundary checks using clearly synthetic patient evidence."""
from __future__ import annotations

import argparse
import contextlib
import csv
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from threading import Barrier, Event
import unittest
from unittest.mock import patch
import zipfile

from egene_pipeline import adapter, gdgpt, orchestrator
from egene_pipeline.common import digest, file_spec, files_in, object_digest, read_json, run_command, verify_files, verify_manifest, write_json


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="three stage pipeline ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.delivery = self.root / "source"
        self.delivery.mkdir()

    def pipeline_args(self, values):
        # Synthetic integration tests use the active test interpreter rather
        # than environments that are intentionally absent from a fresh clone.
        return orchestrator.argument_parser().parse_args([
            *values,
            "--popgen-python", sys.executable,
            "--egene-python", sys.executable,
            "--gdgpt-python", sys.executable,
        ])

    def table(self, name, data, fields=None):
        with (self.delivery / name).open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields or list(data[0]), delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows(data)

    def fixture(self, candidate=False, *, ranks=(1,)):
        variant_rows, acmg_rows, link_rows = [], [], []
        labels = ["Pathogenic" if candidate else "Uncertain significance", "Uncertain significance", "Uncertain significance"]
        for index, (gene, label) in enumerate(zip(("TP53", "BRCA1", "NEARBY"), labels), 1):
            vid = f"GRCh38:chr1:{index}:A:G"
            context = {"gene": gene, "occurrence": 1, "classification": label}
            variant_rows.append({"sample_id": "SYNTHETIC", "normalized_id": vid, "source_GT": "0/1",
                "genes_refGene": gene, "Func.refGene": "intronic" if index < 3 else "intergenic",
                "ExonicFunc.refGene": ".", "AAChange.refGene": ".", "CLNSIG": ".", "CLNREVSTAT": ".", "CLNDN": ".",
                "matched_pop": "EAS", "matched_pop_AF": "", "global_AF": "", "af_status": "not_in_reference",
                "use_for_acmg_ba1_bs1": "false", "original_DP": "", "original_GQ": "", "original_QUAL": ".",
                "original_FILTER": ".", "quality_missing": '["DP"]', "acmg_gene_contexts": json.dumps([context])})
            acmg_rows.append({"sample_id": "SYNTHETIC", "normalized_id": vid, "intervar_gene": gene, "gene_occurrence": 1,
                "acmg_classification": label, "raw_classification": label, "source_GT": "0/1",
                "triage_route": "candidate" if candidate and index == 1 else "background",
                "integrated_evidence": '{"PM2": 0}', "data_flags": '["synthetic_fixture"]', "evidence_changes": "{}"})
            link_rows.append({"normalized_id": vid, "original_gene": gene, "gene_occurrence": 1, "resolved_gene": gene,
                "classification": label, "gene_relation": "overlapping_gene_feature" if index < 3 else "nearby_gene_only",
                "gene_mapping_status": "approved_symbol", "eligible_for_candidates": "true" if candidate and index == 1 else "false",
                "exclusion_reasons": "[]" if candidate and index == 1 else '["background_vus_deprioritized_upstream"]'})
        self.table("variants.tsv", variant_rows)
        self.table("acmg_results.tsv", acmg_rows)
        self.table("variant_disease_links.tsv", link_rows)
        case = {"schema_version": "1.0", "sample_id": "SYNTHETIC", "sex": "unknown", "phenotypes": [],
                "clinical_description": "Synthetic test fixture only; <script>alert(1)</script>", "family": {}}
        phenotype = {"sample_id": "SYNTHETIC", "status": "no_resolved_positive_phenotypes",
                     "positive_hpo_ids": [], "negative_hpo_ids": ["HP:0001250"]}
        write_json(self.delivery / "case.json", case)
        write_json(self.delivery / "phenotypes.normalized.json", phenotype)
        candidates = [{"candidate_id": f"OMIM:{rank:06}|TP53", "gene": "TP53", "disease_id": f"OMIM:{rank:06}", "rank": rank,
            "disease_name": "Synthetic condition", "all_variant_ids": [variant_rows[0]["normalized_id"]],
            "acmg_classifications": {variant_rows[0]["normalized_id"]: "Pathogenic"}, "diagnosis_established": False}
            for rank in ranks] if candidate else []
        self.table("disease_candidates.tsv", [{"candidate_id": c["candidate_id"]} for c in candidates], ["candidate_id"])
        self.table("carrier_findings.tsv", [], ["candidate_id"])
        report = {"schema_version": "1.0", "report_id": "synthetic-report", "generated_at": "2026-10-16",
            "sample": {"sample_id": "SYNTHETIC", "sex": "unknown"}, "assembly": "GRCh38",
            "conclusion": {"finding": "Synthetic observations only", "interpretation": "Not a diagnosis", "risk_probability": None,
                "risk_probability_status": "not_estimated", "diagnosis_established": False},
            "analysis_scope": {"classification_labels_modified": False},
            "variant_statistics": {"counts": {"retained_variants": 3, "acmg_gene_contexts": 3},
                "gene_context_classifications": {"Pathogenic": 1, "Uncertain significance": 2} if candidate else {"Uncertain significance": 3},
                "variant_display_priority_classifications": {}, "preview": variant_rows[:1]},
            "disease_candidates": candidates, "case": case, "phenotypes": phenotype,
            "disease_statistics": {"candidate_disease_gene_pairs": len(candidates)}, "input_quality": {"synthetic_fixture": True},
            "versions": {}, "files": {}, "ancestry": {"analysis_based": {"af_population": "EAS", "use_for_acmg_ba1_bs1": False}},
            "frequency_policy": {"missing_AF_semantics": "unknown_not_zero", "use_for_acmg_ba1_bs1": False}, "limitations": []}
        write_json(self.delivery / "report.json", report)
        (self.delivery / "report.html").write_text("<html>Synthetic fixture</html>")
        self.refresh()
        return self.delivery / "report_manifest.json"

    def refresh(self):
        report = read_json(self.delivery / "report.json")
        manifest = {"schema_version": "1.0", "status": "complete", "stage": "generate_report", "sample_id": "SYNTHETIC",
            "assembly": "GRCh38", "producer": {"name": "synthetic_fixture"}, "disease_manifest": {},
            "counts": {"disease_candidates": len(report["disease_candidates"])}, "classification_labels_modified": False,
            "files": files_in(self.delivery, ("report_manifest.json", "status.json"))}
        write_json(self.delivery / "report_manifest.json", manifest)
        write_json(self.delivery / "status.json", {"stage": "generate_report", "status": "complete"})

    def prepare(self, genes=(), candidate=False):
        source = self.fixture(candidate)
        target = self.root / "bridge"
        adapter.prepare(argparse.Namespace(egene_report=source, outdir=target, gene=list(genes), max_candidates=None))
        return target / "input_manifest.json"

    def test_empty_candidates_do_not_promote_background_vus(self):
        data = adapter.build(self.fixture())
        self.assertEqual(data["tasks"], [])
        self.assertFalse(data["selection"]["automatic_background_vus_inclusion"])

    def test_explicit_gene_reads_full_table_outside_report_preview(self):
        data = adapter.build(self.fixture(), ["BRCA1"])
        evidence = data["tasks"][0]["evidence"][0]
        self.assertEqual(evidence["normalized_id"], "GRCh38:chr1:2:A:G")
        self.assertEqual(evidence["classification"], "Uncertain significance")
        self.assertEqual(evidence["triage_route"], "background")
        self.assertEqual(evidence["frequency"]["matched_pop_AF"], "")
        self.assertEqual(data["phenotypes"]["negative_hpo_ids"], ["HP:0001250"])
        self.assertFalse(data["frequency_policy"]["use_for_acmg_ba1_bs1"])

    def test_nearby_gene_is_not_a_variant_target(self):
        with self.assertRaisesRegex(ValueError, "没有唯一"):
            adapter.build(self.fixture(), ["NEARBY"])

    def test_candidate_retains_original_variant_classification(self):
        data = adapter.build(self.fixture(candidate=True))
        self.assertEqual(data["tasks"][0]["kind"], "disease_candidate")
        self.assertEqual(data["tasks"][0]["evidence"][0]["classification"], "Pathogenic")
        question = gdgpt.make_question(data, data["tasks"][0])
        self.assertIn("TP53", question[:600])
        self.assertIn("Synthetic condition", question[:600])
        self.assertIn("[upstream:e-Gene]", question)

    def test_top_three_follow_egene_rank_and_preserve_smaller_limits(self):
        source = self.fixture(candidate=True, ranks=(4, 2, 1, 3))
        for limit, expected in [(None, [1, 2, 3]), (10, [1, 2, 3]), (2, [1, 2])]:
            with self.subTest(limit=limit):
                payload = adapter.build(source, genes=["BRCA1"], max_candidates=limit)
                tasks = payload["tasks"]
                self.assertEqual([t["candidate"]["rank"] for t in tasks if t["candidate"]], expected)
                self.assertEqual(len(tasks), 3)
                self.assertEqual(payload["selection"]["selected_candidate_count"], len(expected))
                self.assertEqual(payload["selection"]["omitted_candidate_count"], 4 - len(expected))
                if limit == 2:
                    self.assertEqual(tasks[-1]["gene"], "BRCA1")
                else:
                    self.assertEqual(payload["selection"]["omitted_exploration_genes"], ["BRCA1"])
        self.assertEqual(len(read_json(self.delivery / "report.json")["disease_candidates"]), 4)

    def test_two_and_three_candidates_are_all_selected(self):
        for count in (2, 3):
            with self.subTest(count=count):
                payload = adapter.build(self.fixture(candidate=True, ranks=range(1, count + 1)))
                self.assertEqual(len(payload["tasks"]), count)
                self.assertEqual(payload["selection"]["omitted_candidate_count"], 0)

    def test_old_handoff_is_capped_before_model_execution(self):
        source = self.fixture(candidate=True, ranks=(6, 5, 4, 3, 2, 1))
        handoff = self.root / "handoff"
        with patch.object(adapter, "MAX_GDGPT_TASKS", 6):
            manifest = adapter.prepare(argparse.Namespace(egene_report=source, outdir=handoff, gene=[], max_candidates=None))
        self.assertEqual(manifest["task_count"], 6)
        path = handoff / "input_manifest.json"
        data = gdgpt.load_input(path)
        self.assertEqual([t["candidate"]["rank"] for t in data["tasks"]], [1, 2, 3])
        self.assertEqual(data["selection"]["omitted_candidate_count"], 3)
        self.assertEqual(len(read_json(handoff / "gdgpt_input.json")["tasks"]), 6)

    def test_changed_file_is_rejected(self):
        source = self.fixture()
        with (self.delivery / "variants.tsv").open("a") as handle:
            handle.write("tampered\n")
        with self.assertRaisesRegex(ValueError, "完整性校验失败"):
            adapter.build(source)

    def test_sample_mismatch_is_rejected_even_with_updated_hashes(self):
        source = self.fixture()
        case = read_json(self.delivery / "case.json")
        case["sample_id"] = "OTHER"
        write_json(self.delivery / "case.json", case)
        self.refresh()
        with self.assertRaisesRegex(ValueError, "样本不一致"):
            adapter.build(source)

    def test_completed_task_resumes_without_a_model_request(self):
        source = self.prepare(["BRCA1"])
        payload = gdgpt.load_input(source)
        task = payload["tasks"][0]
        old = self.root / "partial"
        old.mkdir()
        runtime = {"model": "synthetic_model"}
        parameters = {"max_rounds": 6, "prompt_variants": 20}
        result = {"status": "complete", "sample_id": "SYNTHETIC", "task_id": task["id"],
            "runtime": runtime, "parameters": parameters, "task_sha256": object_digest(task), "input_sha256": object_digest(payload),
            "gene": "BRCA1", "kind": task["kind"], "kg_coverage_level": "low", "answer_text": "Synthetic cached result <script>unsafe</script>"}
        target = old / "result.json"
        write_json(target, result)
        write_json(old / "gdgpt_manifest.json", {"sample_id": "SYNTHETIC", "input_manifest": file_spec(source),
            "tasks": {task["id"]: {"status": "complete", "file": file_spec(target, old)}}})
        args = argparse.Namespace(input_manifest=source, outdir=self.root / "resumed", resume_results=old,
            max_rounds=6, prompt_variants=20, task_timeout=10)
        with patch.object(gdgpt, "runtime_signature", return_value=({}, runtime)), patch.object(gdgpt, "run_command") as invoke:
            gdgpt.run(args)
            invoke.assert_not_called()
        _, files = verify_manifest(args.outdir / "gdgpt_manifest.json", "gdgpt_analysis")
        self.assertNotIn("<script>unsafe", files["report.html"].read_text())
        self.assertIn("&lt;script&gt;unsafe", files["report.html"].read_text())

    def test_parallel_candidates_checkpoint_siblings_and_resume_in_rank_order(self):
        source = self.fixture(candidate=True, ranks=(3, 2, 1))
        bridge = self.root / "bridge"
        adapter.prepare(argparse.Namespace(egene_report=source, outdir=bridge, gene=[], max_candidates=None))
        source = bridge / "input_manifest.json"
        payload = gdgpt.load_input(source)
        tasks = {t["id"]: t for t in payload["tasks"]}
        rank_order = list(tasks)
        middle = rank_order[1]
        runtime = {"model": "synthetic_parallel"}
        partial = self.root / "partial"
        args = argparse.Namespace(input_manifest=source, outdir=partial, resume_results=None,
            max_rounds=6, prompt_variants=20, task_timeout=45)
        started = Barrier(3, timeout=5)

        def worker(argv, cwd, log_path, *, timeout, cancel_event):
            task_id = argv[argv.index("--task-id") + 1]
            task = tasks[task_id]
            target = argv[argv.index("--task-output") + 1]
            self.assertEqual(target, args.outdir / "tasks" / (task_id + ".json"))
            self.assertEqual(log_path, args.outdir / "logs" / (task_id + ".log"))
            self.assertEqual(timeout, args.task_timeout)
            self.assertFalse(cancel_event.is_set())
            if args.outdir == partial:
                self.assertEqual(read_json(partial / "status.json")["active_tasks"], rank_order)
                started.wait()  # All three processes must be dispatched before any can complete.
                if task_id == middle:
                    raise RuntimeError("synthetic candidate failure")
            write_json(target, {"status": "complete", "task_id": task_id, "sample_id": payload["sample_id"],
                "task_sha256": object_digest(task), "input_sha256": object_digest(payload), "runtime": runtime,
                "parameters": {"max_rounds": 6, "prompt_variants": 20}, "candidate_id": task["candidate_id"],
                "kind": task["kind"], "gene": task["gene"], "kg_coverage_level": "low", "answer_text": "Synthetic."})

        with patch.object(gdgpt, "runtime_signature", return_value=({}, runtime)), patch.object(gdgpt, "run_command", side_effect=worker) as invoke:
            with self.assertRaisesRegex(RuntimeError, "synthetic candidate failure"):
                gdgpt.run(args)
            self.assertEqual(invoke.call_count, 3)
            check = read_json(partial / "gdgpt_manifest.json")
            self.assertEqual(check["failed_task"], middle)
            self.assertEqual([check["tasks"][i]["status"] for i in rank_order], ["complete", "failed", "complete"])
            args.outdir = self.root / "resumed"
            args.resume_results = partial
            invoke.reset_mock()
            gdgpt.run(args)
            invoke.assert_called_once()
            self.assertIn(middle, invoke.call_args.args[0])
        _, files = verify_manifest(args.outdir / "gdgpt_manifest.json", "gdgpt_analysis")
        self.assertEqual([r["task_id"] for r in read_json(files["report.json"])["task_results"]], rank_order)

    def test_integrated_delivery_and_completed_resume_are_portable(self):
        source = self.fixture()
        destination = self.root / "integrated"
        args = self.pipeline_args(["--egene-report", str(source), "--without-atheromap", "--outdir", str(destination)])
        with contextlib.redirect_stdout(io.StringIO()):
            first = orchestrator.run(args)
            again = orchestrator.run(self.pipeline_args([
                "--resume-from", str(destination / "pipeline_manifest.json"), "--without-atheromap", "--outdir", str(self.root / "again")]))
        self.assertEqual(first["status"], "complete")
        self.assertEqual(first["gdgpt_analysis_status"], "no_eligible_candidates")
        self.assertEqual(again["commands"], [])
        verify_files(destination, first["files"])
        with zipfile.ZipFile(destination / "delivery.zip") as bundle:
            self.assertEqual(len(bundle.namelist()), len(set(bundle.namelist())))
            bundle.extractall(self.root / "unpacked")
        moved = self.root / "unpacked/delivery"
        verify_files(moved, read_json(moved / "delivery_manifest.json")["files"])
        self.assertTrue((moved / "egene/report.html").is_file())
        self.assertTrue((moved / "gdgpt/report.html").is_file())
        self.assertTrue((moved / "popgen/report.html").is_file())
        index = (moved / "index.html").read_text()
        self.assertLess(index.index('href="popgen/report.html"'), index.index('href="egene/report.html"'))
        self.assertEqual(read_json(moved / "pipeline_report.json")["files"]["popgen_report"], "popgen/report.html")

    def test_failure_stops_before_gdgpt_and_does_not_publish_archive(self):
        source = self.fixture()
        destination = self.root / "failed"
        args = self.pipeline_args(["--egene-report", str(source), "--gene", "NEARBY", "--end-stage", "gdgpt", "--outdir", str(destination)])
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(RuntimeError):
            orchestrator.run(args)
        result = read_json(destination / "pipeline_manifest.json")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failed_stage"], "bridge")
        status = read_json(destination / "status.json")
        html = (destination / status["error_report"]).read_text()
        self.assertIn('href="logs/bridge.log"', html)
        self.assertIn('NEARBY', html)
        self.assertEqual(result["failure"]["completed"], ["egene"])
        self.assertNotIn("gdgpt", result["stages"])
        self.assertFalse((destination / "delivery.zip").exists())

    def test_default_fourth_stage_from_legacy_resume_and_gdgpt_manifest(self):
        source = self.fixture()
        legacy = self.root / "legacy"
        ref = self.root / "reference.json"
        write_json(ref, {"synthetic": True})
        refs = ["--atheromap-reference", str(ref), "--atheromap-gsmap-root", str(self.root)]
        three = orchestrator.run(self.pipeline_args(["--egene-report", str(source), *refs,
            "--without-atheromap", "--outdir", str(legacy)]))
        gdgpt_path = three["stages"]["gdgpt"]["artifact"]["path"]

        def fourth(command, cwd, log, **kwargs):
            self.assertEqual(command[2], "egene_pipeline.atheromap")
            self.assertEqual(str(command[command.index("--gdgpt-manifest") + 1]), gdgpt_path)
            folder = Path(command[command.index("--outdir") + 1])
            folder.mkdir()
            write_json(folder / "report.json", {"status": "complete", "limitations": []})
            (folder / "report.html").write_text("Synthetic reference report")
            status = {"stage": "atheromap", "status": "complete"}
            write_json(folder / "atheromap_manifest.json", {**status, "schema_version": "1.0",
                "sample_id": "SYNTHETIC", "assembly": "GRCh38", "files": files_in(folder)})
            write_json(folder / "status.json", status)

        cases = [("--resume-from", legacy / "pipeline_manifest.json"), ("--gdgpt-manifest", gdgpt_path)]
        for flag, path in cases:
            out = self.root / flag.strip("-")
            with self.subTest(entry=flag), patch.object(orchestrator, "run_command", side_effect=fourth) as invoke:
                new = orchestrator.run(self.pipeline_args([flag, str(path), *refs, "--outdir", str(out)]))
                invoke.assert_called_once()
                self.assertTrue(new["stages"]["gdgpt"]["reused"])
                self.assertTrue(new["stages"]["egene"]["reused"])
                self.assertEqual([c["stage"] for c in new["commands"]], ["atheromap"])
                self.assertTrue((out / "delivery/atheromap/report.html").is_file())
                self.assertTrue((out / "delivery.zip").is_file())

        # A copied standalone GDgpt bundle can still deliver the fourth-stage report.
        source.rename(self.root / "original_manifest.json")
        out = self.root / "standalone"
        with patch.object(orchestrator, "run_command", side_effect=fourth):
            standalone = orchestrator.run(self.pipeline_args(["--gdgpt-manifest", gdgpt_path, *refs, "--outdir", str(out)]))
        self.assertEqual(standalone["end_stage"], "atheromap")
        self.assertEqual(standalone["status"], "complete")
        self.assertTrue((out / "05_atheromap/report.html").is_file())

    def test_startup_failure_writes_report_without_touching_an_existing_run(self):
        output = self.root / "startup"
        args = self.pipeline_args(["--vcf", str(self.root / "absent.vcf"), "--outdir", str(output)])
        with self.assertRaises(FileNotFoundError):
            orchestrator.run(args)
        status = read_json(output / "status.json")
        self.assertEqual(status["active_stage"], "startup")
        report = output / status["error_report"]
        original = report.read_bytes()
        self.assertIn(b"absent.vcf", original)
        with self.assertRaisesRegex(ValueError, "拒绝覆盖"):
            orchestrator.run(args)
        self.assertEqual(report.read_bytes(), original)

    def test_resume_rejects_a_changed_successful_stage_manifest(self):
        source = self.fixture()
        destination = self.root / "first"
        with contextlib.redirect_stdout(io.StringIO()):
            first = orchestrator.run(self.pipeline_args([
                "--egene-report", str(source), "--without-atheromap", "--outdir", str(destination)]))
        bridge_path = Path(first["stages"]["bridge"]["artifact"]["path"])
        bridge_path.write_text(bridge_path.read_text() + " ")
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(ValueError, "清单被修改"):
            orchestrator.run(self.pipeline_args([
                "--resume-from", str(destination / "pipeline_manifest.json"), "--without-atheromap", "--outdir", str(self.root / "rejected")]))
        self.assertFalse((self.root / "rejected/delivery.zip").exists())

    def test_hard_timeout_stops_child_process(self):
        import subprocess
        pidfile = self.root / "pid"
        with self.assertRaises(subprocess.TimeoutExpired):
            run_command([sys.executable, "-c", "import os,time,pathlib; pathlib.Path('pid').write_text(str(os.getpid())); time.sleep(60)"],
                        self.root, self.root / "timeout.log", timeout=0.5)
        pid = int(pidfile.read_text())
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def test_parallel_worker_cancellation_stops_child_process(self):
        cancel = Event()
        pidfile = self.root / "pid"
        def cancel_after_launch(timeout):
            if pidfile.exists():
                cancel.set()
            return Event.wait(cancel, timeout)
        with patch.object(cancel, "wait", side_effect=cancel_after_launch), self.assertRaises(InterruptedError):
            run_command([sys.executable, "-c", "import os,time,pathlib; pathlib.Path('pid').write_text(str(os.getpid())); time.sleep(60)"],
                        self.root, self.root / "cancel.log", timeout=5, cancel_event=cancel)
        with self.assertRaises(ProcessLookupError):
            os.kill(int(pidfile.read_text()), 0)


if __name__ == "__main__":
    unittest.main()
