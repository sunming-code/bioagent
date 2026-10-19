"""Interface checks with synthetic evidence; no model or scientific computation."""
from __future__ import annotations

import argparse
import contextlib
import io
from pathlib import Path
import unittest

import test_pipeline as upstream_tests
from egene_pipeline import adapter
from egene_pipeline import atheromap_adapter as bridge
from egene_pipeline.atheromap_reference import ROLES
from egene_pipeline.atheromap_scdrs import normalize_h5ad_metadata
from egene_pipeline.common import digest, file_spec, files_in, object_digest, read_json, write_json


class AtheromapInterfaceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = upstream_tests.PipelineTests(methodName="runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.source = self.root / "gdgpt"
        self.source.mkdir()
        self.atlas = self.root / "synthetic atlas"
        self.atlas.mkdir()
        # These files exercise checksum contracts only, not H5AD parsing.
        for role in ROLES:
            (self.atlas / role).write_text(f"SYNTHETIC checksum fixture only: {role}\n")
        self.reference = self.root / "reference.json"
        self.ref = {"schema_version": "1.0", "stage": "scdrs_reference", "producer": {"name": "synthetic_fixture"},
            "reference_dataset_id": "GSE159677", "reference_scope": "external_cohort", "species": "human",
            "tissue": "synthetic reference", "expression_genome_build": None, "data_root": self.atlas.name,
            "files": {role: file_spec(self.atlas / role, self.atlas) for role in ROLES},
            "annotation_validation": {"status": "passed", "cells": 1, "clusters": 1, "subtypes": {}},
            "trait": {"id": "local:z_score", "score_label": "z_score", "provenance_status": "unverified",
                "disease_name": None, "gwas_study_id": None, "gwas_genome_build": None,
                "mapped_disease_ids": [], "source_records": [], "note": "SYNTHETIC fixture only"}}
        write_json(self.reference, self.ref)

    def make_source(self, *, candidate=False, genes=("BRCA1",)):
        payload = adapter.build(self.fixture.fixture(candidate), list(genes))
        results = [{"schema_version": "1.0", "status": "complete", "sample_id": "SYNTHETIC",
            "task_id": task["id"], "kind": task["kind"], "gene": task["gene"], "candidate_id": task["candidate_id"],
            "task_sha256": object_digest(task), "input_sha256": object_digest(payload),
            "answer_text": "SYNTHETIC mechanism result; no model call"} for task in payload["tasks"]]
        report = {key: payload[key] for key in ("sample_id", "assembly", "case", "phenotypes", "ancestry",
            "frequency_policy", "upstream_summary", "selection")}
        report.update(schema_version="1.0", analysis_status="analyzed" if results else "no_eligible_candidates", task_results=results)
        write_json(self.source / "gdgpt_input.json", payload)
        write_json(self.source / "report.json", report)
        self.records = {}
        for result in results:
            name = f"{result['task_id']}.json"
            write_json(self.source / name, result)
            self.records[result["task_id"]] = {"status": "complete", "file": file_spec(self.source / name, self.source)}
        self.refresh_source()
        return self.source / "gdgpt_manifest.json"

    def refresh_source(self):
        report = read_json(self.source / "report.json")
        write_json(self.source / "gdgpt_manifest.json", {"schema_version": "1.0", "stage": "gdgpt_analysis",
            "status": "complete", "sample_id": "SYNTHETIC", "assembly": "GRCh38", "tasks": self.records,
            "analysis_status": report["analysis_status"], "files": files_in(self.source, ("gdgpt_manifest.json", "status.json"))})
        write_json(self.source / "status.json", {"stage": "gdgpt_analysis", "status": "complete"})

    def prepare(self, *, scope="reference-context", name="handoff"):
        out = self.root / name
        with contextlib.redirect_stdout(io.StringIO()):
            bridge.prepare(argparse.Namespace(gdgpt_manifest=self.source / "gdgpt_manifest.json",
                reference=self.reference, scope=scope, outdir=out))
        return out / "input_manifest.json"

    def verified_trait(self, disease_id="OMIM:000001"):
        self.ref["trait"].update(provenance_status="verified", disease_name="Synthetic condition",
            gwas_study_id="SYNTHETIC-STUDY", mapped_disease_ids=[disease_id], source_records=["synthetic:test-only"])
        write_json(self.reference, self.ref)

    def change_handoff(self, path, change):
        payload_file = path.parent / "atheromap_input.json"
        value = read_json(payload_file)
        change(value)
        write_json(payload_file, value)
        manifest = read_json(path)
        manifest["files"]["atheromap_input.json"] = file_spec(payload_file, path.parent)
        write_json(path, manifest)

    def test_preserves_patient_evidence_and_external_reference(self):
        self.make_source()
        path = self.prepare()
        value, ref, root, _ = bridge.load_input(path)
        evidence = value["tasks"][0]["variant_evidence"][0]
        self.assertEqual(value["sample_id"], "SYNTHETIC")
        self.assertEqual(ref["reference_scope"], "external_cohort")
        self.assertEqual(root, self.atlas)
        self.assertEqual(evidence["classification"], "Uncertain significance")
        self.assertEqual(evidence["triage_route"], "background")
        self.assertEqual(evidence["frequency"]["matched_pop_AF"], "")
        self.assertFalse(value["frequency_policy"]["use_for_acmg_ba1_bs1"])
        self.assertEqual(value["phenotypes"]["negative_hpo_ids"], ["HP:0001250"])
        self.assertEqual(value["tasks"][0]["applicability"]["reason"], "trait_provenance_unverified")
        self.assertFalse(value["classification_labels_modified"])
        self.assertIsNone(value["risk_probability"])

    def test_empty_upstream_stays_empty(self):
        self.make_source(genes=())
        value, *_ = bridge.load_input(self.prepare())
        self.assertEqual(value["tasks"], [])
        self.assertEqual(value["gdgpt_analysis_status"], "no_eligible_candidates")

    def test_matched_scope_requires_verified_exact_identifier(self):
        self.make_source(candidate=True)
        with self.assertRaisesRegex(ValueError, "没有来源已确认"):
            self.prepare(scope="matched-trait", name="unverified")
        self.assertFalse((self.root / "unverified").exists())
        self.verified_trait("OMIM:999999")
        with self.assertRaisesRegex(ValueError, "没有来源已确认"):
            self.prepare(scope="matched-trait", name="wrong disease")
        self.verified_trait()
        value, *_ = bridge.load_input(self.prepare(scope="matched-trait"))
        self.assertEqual([task["gene"] for task in value["tasks"]], ["TP53"])
        self.assertEqual(value["tasks"][0]["applicability"]["status"], "trait_matched")
        self.assertEqual(value["selection"]["excluded_tasks"][0]["gene"], "BRCA1")
        self.assertEqual(value["selection"]["source_task_count"], 2)

    def test_upstream_other_patient_rejected_after_checksum_refresh(self):
        self.make_source()
        report = read_json(self.source / "report.json")
        report["sample_id"] = "OTHER_PATIENT"
        write_json(self.source / "report.json", report)
        self.refresh_source()
        with self.assertRaisesRegex(ValueError, "患者 ID"):
            self.prepare()

    def test_upstream_gene_mismatch_rejected(self):
        self.make_source()
        report = read_json(self.source / "report.json")
        result = report["task_results"][0]
        result["gene"] = "TP53"
        write_json(self.source / "report.json", report)
        write_json(self.source / self.records[result["task_id"]]["file"]["path"], result)
        self.refresh_source()
        with self.assertRaisesRegex(ValueError, "校验值不一致"):
            self.prepare()

    def test_changed_variant_evidence_rejected_after_checksum_refresh(self):
        self.make_source()
        path = self.prepare()
        self.change_handoff(path, lambda value: value["tasks"][0]["variant_evidence"][0].update(classification="Pathogenic"))
        with self.assertRaisesRegex(ValueError, "变异证据"):
            bridge.load_input(path)

    def test_changed_task_selection_rejected_after_checksum_refresh(self):
        self.make_source()
        path = self.prepare()
        self.change_handoff(path, lambda value: value["selection"].update(source_task_count=0))
        with self.assertRaisesRegex(ValueError, "任务选择"):
            bridge.load_input(path)

    def test_background_cannot_be_relabelled_as_matched_scope(self):
        self.make_source()
        path = self.prepare()
        self.change_handoff(path, lambda value: value.update(analysis_scope="matched_trait_reference_context"))
        with self.assertRaisesRegex(ValueError, "分析范围"):
            bridge.load_input(path)

    def test_reference_tampering_rejected(self):
        self.make_source()
        path = self.prepare()
        (self.atlas / "score").write_text("SYNTHETIC altered score")
        with self.assertRaisesRegex(ValueError, "完整性校验失败"):
            bridge.load_input(path)

    def test_existing_output_and_original_reference_are_protected(self):
        self.make_source()
        self.prepare()
        with self.assertRaisesRegex(ValueError, "新目录"):
            self.prepare()
        with self.assertRaisesRegex(ValueError, "新目录"):
            self.prepare(name=str(self.atlas / "new run"))
        self.assertFalse((self.atlas / "new run").exists())

    def test_h5ad_null_metadata_conversion_preserves_matrix_and_source(self):
        try:
            import anndata as ad
            import h5py
            import numpy as np
        except ImportError:
            self.skipTest("Run in atheromap_scdrs to test real HDF5 compatibility")
        import shutil
        original = self.root / "original.h5ad"
        copy = self.root / "copy.h5ad"
        data = ad.AnnData(X=np.array([[1., 2.], [0., 3.]]))
        data.layers["raw_counts"] = data.X.copy()
        data.obs["final_label"] = ["A", "B"]
        data.uns["pca"] = {"params": {"use_highly_variable": False}}
        data.write_h5ad(original)
        with h5py.File(original, "r+") as f:
            node = f["uns/pca/params"].create_dataset("mask_var", data=h5py.Empty("f"))
            node.attrs.update({"encoding-type": "null", "encoding-version": "0.1.0"})
        checksum = digest(original)
        shutil.copyfile(original, copy)
        changes = normalize_h5ad_metadata(copy)
        self.assertEqual(changes, [{"hdf5_path": "uns/pca/params/mask_var", "original_value": None,
                                  "action": "omit_null_uns_key_for_anndata_0_10"}])
        result = ad.read_h5ad(copy)
        np.testing.assert_array_equal(result.X, data.X)
        np.testing.assert_array_equal(result.layers["raw_counts"], data.layers["raw_counts"])
        self.assertTrue(result.obs.equals(data.obs))
        self.assertEqual(digest(original), checksum)


if __name__ == "__main__":
    unittest.main()
