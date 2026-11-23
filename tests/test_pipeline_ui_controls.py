"""Regression tests for submission controls and abnormal worker exits."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


@unittest.skipUnless(importlib.util.find_spec("starlette"), "requires the pipeline UI environment")
class RunControlsTests(unittest.TestCase):
    def setUp(self):
        from pipeline_ui import app
        self.app = app
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        source = self.root / "input.vcf"
        source.touch()
        self.payload = dict(start_stage="popgen", end_stage="popgen", input_type="vcf",
                            vcf=str(source), reference=str(source))

    def test_scientific_options_reach_platform_parser(self):
        from egene_pipeline.orchestrator import argument_parser
        request = self.app._validate_request(dict(self.payload, popgen_af_percent=0, popgen_min_dp=12,
            popgen_min_gq=0, popgen_keep_missing_quality=True, popgen_cv_max_k=3))
        argv = self.app._command_for(request, self.root / "output")
        args = argument_parser().parse_args(argv[2:])
        self.assertEqual((args.popgen_af_percent, args.popgen_min_dp, args.popgen_min_gq,
                          args.popgen_keep_missing_quality, args.popgen_cv_max_k), (0, 12, 0, True, 3))

    def test_invalid_controls_return_a_submission_error(self):
        from starlette.exceptions import HTTPException
        for wrong in ({"popgen_af_percent": 101}, {"popgen_min_dp": -1}, {"popgen_min_gq": 1.5},
                      {"popgen_cv_max_k": 11}, {"popgen_keep_missing_quality": "false"}):
            with self.subTest(wrong=wrong), self.assertRaises(HTTPException) as error:
                self.app._validate_request(dict(self.payload, **wrong))
            self.assertEqual(error.exception.status_code, 400)

    def test_worker_exiting_early_publishes_a_report_visible_in_history(self):
        run_id = "ui_abnormal_test"
        directory = self.root / run_id
        output = directory / "output"
        output.mkdir(parents=True)
        self.app._write_json(output / "status.json", {"status": "running", "active_stage": "popgen"})
        with patch.object(self.app, "RUNS", self.root):
            self.app._run_job(run_id, [sys.executable, "-c", "raise SystemExit(17)"], directory,
                              {"status": "queued", "output_dir": str(output)})
            snapshot = self.app.snapshot(run_id)
        self.assertEqual(snapshot["status"], "failed")
        self.assertEqual(snapshot["error_report_url"], f"/api/runs/{run_id}/files/error_report.html")
        self.assertIn("17", (output / "error_report.html").read_text())
        self.assertIsNone(snapshot["report_url"])
