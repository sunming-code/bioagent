"""GDgpt visual report rendering and its downstream contract, with synthetic inputs."""
from pathlib import Path
import json
import tempfile
import unittest

from egene_pipeline import gdgpt
from egene_pipeline.gdgpt_graph import graph_data
from egene_pipeline.gdgpt_report import render_plain, render_professional

KG_ONE = """[Neo4j_KG] intent=gene_disease rows=2
- disease=Hypertrophic cardiomyopathy, gene=MYH7, relation=ASSOCIATED_WITH, source=ClinVar
- disease=Hypertrophic cardiomyopathy, pathway=Cardiac muscle contraction, genes=MYH7;TNNT2, gene_count=2
"""

KG_MANY = "[Neo4j_KG] intent=gene_disease rows=5\n" + "".join(
    f"- disease=Disease {n}, gene=MYH7, relation=ASSOCIATED_WITH, source=OMIM\n" for n in range(5))


def payload(limitations=("仅基因层面知识，不含变异层面证据。",)):
    return {
        "schema_version": "1.0", "sample_id": "SYNTHETIC", "assembly": "GRCh38",
        "case": {"description": "synthetic case"}, "phenotypes": {"terms": []},
        "ancestry": {"superpop": "EUR"}, "frequency_policy": {"af_source": "AF_EUR"},
        "selection": {"candidate_count": 1, "selected_candidate_count": 1,
                      "omitted_candidate_count": 0, "requested_genes": [],
                      "automatic_background_vus_inclusion": False},
        "upstream_summary": {"conclusion": {"finding": "合成上游结论。"}},
        "limitations": list(limitations),
        "tasks": [],
    }


def result(kg=KG_ONE, gene="MYH7", answer="## 机制\n\n正文 [KG-supported] 说明。", **over):
    base = {
        "schema_version": "1.0", "status": "complete", "task_id": "task-" + "0" * 16,
        "sample_id": "SYNTHETIC", "gene": gene, "kind": "disease_candidate",
        "candidate_id": "cand-1", "answer_text": answer,
        "kg_coverage_level": "high", "kg_coverage_ratio": 0.9, "elapsed_seconds": 12.5,
        "tool_calls": [{"role": "Cardiologist", "result": {"text": kg, "runs": [{"rows": 2}]}}],
        "execution_timings": [{"ok": True}],
        "diagnosis_established": False, "classification_labels_modified": False,
        "risk_probability": None,
    }
    base.update(over)
    return base


RUNTIME = {"text_model": "synthetic", "code_version": "test"}


class GDgptReportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="gdgpt report ")
        self.addCleanup(temporary.cleanup)
        self.outdir = Path(temporary.name)

    def write(self, results, pay=None):
        return gdgpt.write_report(self.outdir, pay or payload(), results, RUNTIME)

    def test_writes_every_report_artifact_without_falling_back(self):
        self.write([result()])
        for name in ("report.json", "report.md", "report.html",
                     "report_plain.html", "report_graph.html"):
            self.assertTrue((self.outdir / name).is_file(), f"missing {name}")
        html = (self.outdir / "report.html").read_text(encoding="utf-8")
        # the fallback renderer emits a bare <pre> dump and none of the rich shell
        self.assertIn("kpis", html)
        self.assertNotIn("<pre>", html)

    def test_report_json_keeps_the_contract_atheromap_consumes(self):
        report = self.write([result()])
        stored = json.loads((self.outdir / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(stored, report)
        for key in ("schema_version", "sample_id", "assembly", "analysis_status", "summary",
                    "upstream_summary", "selection", "task_results", "limitations",
                    "diagnosis_established", "classification_labels_modified", "risk_probability"):
            self.assertIn(key, stored)
        self.assertEqual(stored["analysis_status"], "analyzed")
        self.assertEqual(stored["assembly"], "GRCh38")
        self.assertFalse(stored["diagnosis_established"])
        self.assertIsNone(stored["risk_probability"])

    def test_no_eligible_candidates_still_renders(self):
        report = self.write([])
        self.assertEqual(report["analysis_status"], "no_eligible_candidates")
        for name in ("report.html", "report_plain.html", "report_graph.html"):
            self.assertTrue((self.outdir / name).is_file(), f"missing {name}")

    def test_graph_page_embeds_edges_parsed_from_tool_output(self):
        self.write([result()])
        page = (self.outdir / "report_graph.html").read_text(encoding="utf-8")
        self.assertIn("Hypertrophic cardiomyopathy", page)
        self.assertIn("disease", page)
        # a closing tag inside embedded JSON would end the <script> early
        self.assertNotIn("</script>", page.split("__DATA__")[0] if "__DATA__" in page else "")

    def test_every_disease_node_is_distinct_so_labels_cannot_stack(self):
        """Regression: all disease nodes used to collapse onto (0,0) and overlap."""
        data = graph_data([result(kg=KG_MANY)])
        diseases = [n for n in data[0]["nodes"] if n["type"] == "disease"]
        self.assertEqual(len(diseases), 5)
        self.assertEqual(len({n["id"] for n in diseases}), 5)
        # the page must carry the ring-anchor logic, not the collapse-to-origin one
        page = (self.outdir / "report_graph.html")
        self.write([result(kg=KG_MANY)])
        js = page.read_text(encoding="utf-8")
        self.assertIn("n.ax", js)
        self.assertNotIn("n.x*=.9", js)

    HOSTILE = 'bad <script>alert(1)</script> & <img src=x onerror=alert(2)>'

    def test_model_text_cannot_inject_markup_into_the_html_reports(self):
        self.write([result(answer=self.HOSTILE, gene='G<script>x</script>')])
        for name in ("report.html", "report_plain.html"):
            html = (self.outdir / name).read_text(encoding="utf-8")
            # the payload survives only as inert escaped text, never as a live tag
            self.assertNotIn("<script>alert(1)", html)
            self.assertNotIn("<img src=x", html)
            self.assertIn("&lt;script&gt;", html)

    def test_model_text_cannot_break_out_of_the_graph_page_script_block(self):
        """The graph page escapes for a JS string context, not an HTML one."""
        self.write([result(answer=self.HOSTILE, gene='G<script>x</script>')])
        page = (self.outdir / "report_graph.html").read_text(encoding="utf-8")
        data = page.split("const DATA=", 1)[1].rsplit("</script>", 1)[0]
        # a literal </script anywhere in the embedded data would end the block early
        self.assertNotIn("</script", data)
        self.assertIn("<\\/script>", data)
        # exactly one real script element, so nothing was smuggled outside it
        self.assertEqual(page.count("</script>"), 1)

    def test_renderer_failure_degrades_to_the_simple_report(self):
        def boom(*_a, **_k):
            raise RuntimeError("synthetic renderer failure")

        original = gdgpt.write_html_reports
        gdgpt.write_html_reports = boom
        self.addCleanup(setattr, gdgpt, "write_html_reports", original)
        report = self.write([result()])
        # the stage must still complete, with the original plain report on disk
        self.assertEqual(report["analysis_status"], "analyzed")
        html = (self.outdir / "report.html").read_text(encoding="utf-8")
        self.assertIn("<pre>", html)
        self.assertTrue((self.outdir / "report.json").is_file())

    def test_renderers_are_pure_functions_of_the_report(self):
        report = self.write([result()])
        self.assertEqual(render_professional(report), render_professional(report))
        self.assertEqual(render_plain(report), render_plain(report))


if __name__ == "__main__":
    unittest.main()
