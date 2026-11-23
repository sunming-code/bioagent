"""PopGen report semantics and portable integrated delivery, with synthetic inputs."""
import csv
import gzip
from html.parser import HTMLParser
from importlib import import_module
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from egene_pipeline.common import file_spec
from egene_pipeline.popgen import deliver_popgen

reporting = import_module("1_popgen.reporting")


class Links(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.links = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href", "")
            if href and not href.startswith("#"):
                self.links.append(href)


class PopGenReportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="popgen report ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.results = self.root / "results"
        self.delivery = self.results / "delivery"
        self.delivery.mkdir(parents=True)
        self.pack_path = self.delivery / "evidence_pack.json"
        self.pack = {
            "schema_version": "1.0", "metadata": {"sample_id": "SYNTHETIC", "sample_alias": "Sample <script>unsafe</script>",
                "genome_build": "GRCh38", "variant_count": 28, "reference_panel": "synthetic"},
            "producer": {"pack_built_at": "2026-11-03T00:00:00Z"},
            "ancestry": {"analysis_based": {"pca_nearest": "EUR", "af_population": "EUR", "assignment": "admixed",
                "use_for_acmg_ba1_bs1": False, "reason": "pca_EUR_admixture_EAS_discordant", "q": {"EAS": 1},
                "pca_d_nearest": .01, "pca_d_second": .02, "pca_d_second_over_nearest": 2},
                "gnn_based": {"predicted": "EAS", "q": dict(zip(reporting.POPS, (.1, .1, .5, .2, .1))),
                    "n_snps": 30000, "n_snps_observed": 200, "concordant_with_pca3": False,
                    "pca3_nearest": "EUR", "usable_for_lookup": False, "discordance_reason": "synthetic disagreement"},
                "confidence": .5},
            "structure": {"unsupervised_best_k": 9},
            "allele_frequency": {"path": "allele_freq.tsv", "matched_pop": "EUR"},
            "files": {"pca": "../ancestry_pca.tsv", "admixture_supervised": "../admixture_results_K5.tsv",
                "partial_evidence": "../partial_evidence.json", "af_coverage": "../af_coverage.json",
                "gnn_decision": "../gnn_decision.json", "allele_frequency": "allele_freq.tsv",
                "patient_vcf": "../patient.vcf.gz", "interface": "INTERFACE.md", "report": "popgen_report.html"}}
        self.write_json(self.pack_path, self.pack)
        self.write_json(self.results / "af_coverage.json", {"input_alleles": 30, "matched_reference_alleles": 29,
            "unmatched_reference_alleles": 1, "unsupported_contigs": ["chrM"]})
        self.write_json(self.results / "gnn_decision.json", {"status": "OK", "n_snps_observed": 200})
        self.write_json(self.results / "partial_evidence.json", {"findings": {"pca": {"pc_distance": {"EUR": .01, "SAS": .02, "EAS": .05}}}})
        (self.delivery / "INTERFACE.md").write_text("Synthetic interface")
        with gzip.open(self.results / "patient.vcf.gz", "wt") as vcf:
            vcf.write("##fileformat=VCFv4.2\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSYNTHETIC\n"
                      "chr1\t2\t.\tA\tG\t.\tPASS\t.\tGT:DP:GQ:AD\t0/1:10:50:6,4\n"
                      "chr1\t3\t.\tA\tG\t.\t.\t.\tGT\t0/0\n"
                      "chr1\t4\t.\tA\tG,C\t.\t.\t.\tGT:DP:GQ:AD\t1/2:0:0:0,0,0\n"
                      "chr1\t5\t.\tA\tG\t.\t.\t.\tGT\t./1\n"
                      "chrM\t30\t.\tA\tG\t.\t.\t.\tGT\t1\n")
        (self.results / "patient.vcf.gz.tbi").write_bytes(b"synthetic VCF index placeholder")
        self.write_tsv(self.results / "admixture_results_K5.tsv", ["Sample", *reporting.POPS],
                       [["patient", .1, .2, .4, .2, .1]])
        self.write_tsv(self.results / "ancestry_pca.tsv", ["IID", "PC1", "PC2", "PC3", "SUPERPOP"],
            [[pop, i * .1, i * .2, i * .05, pop] for i, pop in enumerate(reporting.POPS)]
            + [["__POPGEN_PATIENT__", .12, .23, .06, "PATIENT"]])
        self.write_tsv(self.delivery / "allele_freq.tsv", ["CHROM", "POS", "REF", "ALT", "matched_pop", "matched_pop_AF", "global_AF"],
            [["chr1" if i < 29 else "chrM", i + 1, "A", "G", "EUR", "" if i in (0, 29) else 0 if i == 1 else .001 if i == 2 else 1, ""]
             for i in range(30)])

    def write_json(self, path, value):
        path.write_text(json.dumps(value))

    def write_tsv(self, path, header, rows):
        with path.open("w", newline="") as handle:
            writer = csv.writer(handle, delimiter="\t")
            writer.writerow(header)
            writer.writerows(rows)

    def test_full_report_uses_tsv_q_and_full_frequency_table_and_preserves_unknown(self):
        data = reporting.collect_report(self.pack_path)
        self.assertEqual(data["lookup"], "EUR")  # Neither max-Q EAS nor GNN EAS changes lookup.
        self.assertEqual(data["q"]["EAS"], .4)  # The pack contains a rounded, different Q.
        self.assertEqual(data["second"], "SAS")
        self.assertEqual(data["ratio"], 2)
        self.assertEqual(data["frequency"]["total"], 30)
        self.assertEqual(data["frequency"]["valid"], 28)
        self.assertEqual(data["frequency"]["bins"], [1, 1, 0, 0, 0, 0, 26])
        html = reporting.generate_report(self.pack_path).read_text()
        self.assertIn("BA1/BS1：不允许", html)
        self.assertIn('<dt>精确匹配</dt><dd>29</dd>', html)  # Exact matches may have blank AF.
        self.assertNotIn('频率预览 · 前 25 行', html)
        self.assertIn('<a href="allele_freq.tsv" download>全量逐位点频率表', html)
        with (self.delivery / "allele_freq.tsv").open() as f:
            rows = list(csv.DictReader(f, delimiter="\t"))
        self.assertEqual(len(rows), 30)
        self.assertEqual([row["matched_pop_AF"] for row in rows[:2]], ["", "0"])
        self.assertNotIn('<script>unsafe', html)
        self.assertIn('Sample &lt;script&gt;', html)
        self.assertEqual(html.count('<li>'), 6)
        self.assertIn('<details id="rules"><summary>六条使用规则</summary>', html)
        self.assertLess(html.index('<section id="downloads">'), html.index('<details id="rules">'))
        self.assertNotIn('<nav', html)
        self.assertIn('它与欧洲（EUR）参考人群的中心最近', html)
        for chart in ("admixture-chart", "pca-chart", "gnn-chart", "frequency-chart"):
            self.assertIn(f'id="{chart}"', html)
        self.assertIn('class="patient-point"', html)
        self.assertEqual(len(Links(html).links), 5)
        self.assertTrue(all((self.delivery / link).is_file() for link in Links(html).links))

    def test_carried_alleles_quality_counts_and_download(self):
        html = reporting.generate_report(self.pack_path).read_text()
        for key in ("quality-dp", "quality-gq", "quality-ab", "review-plot"):
            self.assertIn(f'id="{key}"', html)
        self.assertIn('id="review-baseline" data-total="4"', html)
        self.assertIn('aria-live="polite" hidden><table>', html)
        self.assertNotIn('id="review-next"', html)
        self.assertIn('<option value="">全部染色体</option>', html)
        self.assertIn("有效 2 / 适用 3", html)
        self.assertIn("有效 1 / 适用 1", html)
        with gzip.open(self.delivery / "variant_review.tsv.gz", "rt") as f:
            rows = list(csv.DictReader(f, delimiter="\t"))
        self.assertEqual([r["GT"] for r in rows], ["0/1", "1/2", "1/2", "1"])
        self.assertEqual(rows[0]["heterozygous_AB"], "0.4")
        self.assertEqual(rows[0]["matched_pop_AF"], "0")
        self.assertEqual(rows[-1]["matched_pop_AF"], "")
        self.assertEqual(rows[1]["DP"], "0")
        self.assertEqual(rows[1]["heterozygous_AB"], "")
        self.assertEqual(rows[-1]["DP"], ".")

    def test_invalid_matched_frequency_keeps_raw_value_without_a_frequency_class(self):
        self.write_tsv(self.delivery / "allele_freq.tsv",
                       ["CHROM", "POS", "REF", "ALT", "matched_pop", "matched_pop_AF", "global_AF"],
                       [["chr1", 2, "A", "G", "EUR", 1.2, .1]])
        reporting.generate_report(self.pack_path)
        with gzip.open(self.delivery / "variant_review.tsv.gz", "rt") as f:
            row = next(csv.DictReader(f, delimiter="\t"))
        self.assertEqual(row["matched_pop_AF"], "1.2")
        self.assertIn("频率未知", row["frequency_context"])

    def test_quality_unavailable_and_wrong_sample(self):
        path = self.results / "patient.vcf.gz"
        head = "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\t"
        for sample in ("SYNTHETIC", "OTHER"):
            with gzip.open(path, "wt") as f:
                f.write(head + sample + "\nchr1\t2\t.\tA\tG\t.\t.\t.\tGT\t0/1\n")
            if sample == "OTHER":
                with self.assertRaisesRegex(ValueError, "样本"):
                    reporting.generate_report(self.pack_path)
            else:
                html = reporting.generate_report(self.pack_path).read_text()
                self.assertNotIn('id="quality-dp"', html)
                self.assertIn("有效 0 / 适用 1", html)

    def test_only_recorded_neighbors_are_shown_with_observed_coverage(self):
        html = reporting.generate_report(self.pack_path).read_text()
        self.assertIn("200 / 30,000（0.67%）", html)
        self.assertNotIn('id="gnn-neighbors"', html)
        self.write_json(self.results / "gnn_decision.json", {
            "status": "OK", "patient_neighbors": [{"iid": "ref<1>", "superpop": "EAS"}]})
        html = reporting.generate_report(self.pack_path).read_text()
        self.assertIn('id="gnn-neighbors"', html)
        self.assertIn("ref&lt;1&gt;", html)

    def test_insufficient_overlap_has_no_conclusion_or_gnn_chart(self):
        for count in (0, 199):
            with self.subTest(observed=count):
                self.pack["ancestry"]["gnn_based"]["n_snps_observed"] = count
                self.write_json(self.pack_path, self.pack)
                html = reporting.generate_report(self.pack_path).read_text()
                self.assertIn("本次没有 GNN 结论", html)
                self.assertNotIn('id="gnn-chart"', html)
                self.assertIn("少于 200", html)
                self.assertIn(f"<dd>{count}</dd>", html)

    def test_skipped_or_insufficient_decision_with_null_result_keeps_observed_count(self):
        self.pack["ancestry"]["gnn_based"] = None
        self.pack["ancestry"]["confidence"] = None
        self.write_json(self.results / "gnn_decision.json", {"status": "INSUFFICIENT_DATA", "n_snps_observed": 75})
        self.write_json(self.pack_path, self.pack)
        data = reporting.collect_report(self.pack_path)
        self.assertEqual(data["gnn"]["observed"], 75)
        self.assertIsNone(data["gnn"]["q"])
        self.pack["files"]["gnn_decision"] = None  # Ignore an existing stale decision file.
        self.write_json(self.pack_path, self.pack)
        data = reporting.collect_report(self.pack_path)
        self.assertIsNone(data["gnn"]["observed"])
        self.assertIn("未运行", data["gnn"]["reason"])

    def test_checkpoint_feature_count_is_not_observed_overlap(self):
        self.pack["ancestry"]["gnn_based"].pop("n_snps_observed")
        self.pack["files"]["gnn_decision"] = None
        self.write_json(self.pack_path, self.pack)
        data = reporting.collect_report(self.pack_path)
        self.assertIsNone(data["gnn"]["observed"])
        self.assertIsNone(data["gnn"]["q"])

    def test_missing_af_coverage_does_not_turn_unknown_exact_matches_into_zero(self):
        (self.results / "af_coverage.json").unlink()
        data = reporting.collect_report(self.pack_path)
        html = reporting.render_html(data)
        self.assertIn('<dt>精确匹配</dt><dd>未查到</dd>', html)
        self.assertIn('<dt>未查到</dt><dd>未查到</dd>', html)

    def test_all_blank_frequencies_have_no_fake_distribution(self):
        self.write_tsv(self.delivery / "allele_freq.tsv", ["CHROM", "POS", "REF", "ALT", "matched_pop", "matched_pop_AF", "global_AF"],
                       [["chr1", 1, "A", "G", "EUR", "", ""]])
        html = reporting.generate_report(self.pack_path).read_text()
        self.assertNotIn('id="frequency-chart"', html)
        self.assertIn("未查到可绘图", html)

    def test_literal_sample_names_and_alleles_are_not_treated_as_missing_frequencies(self):
        self.pack["metadata"]["sample_alias"] = "NA"
        self.write_json(self.pack_path, self.pack)
        self.write_tsv(self.delivery / "allele_freq.tsv", ["CHROM", "POS", "REF", "ALT", "matched_pop", "matched_pop_AF", "global_AF"],
                       [["chr1", 1, "NA", "N", "EUR", "NaN", "."]])
        html = reporting.generate_report(self.pack_path).read_text()
        self.assertIn('<dt>样本名</dt><dd>NA</dd>', html)
        self.assertNotIn('id="frequency-preview"', html)
        self.assertNotIn('id="frequency-chart"', html)
        with (self.delivery / "allele_freq.tsv").open() as f:
            row = next(csv.DictReader(f, delimiter="\t"))
        self.assertEqual([row[k] for k in ("REF", "ALT", "matched_pop_AF", "global_AF")], ["NA", "N", "NaN", "."])

    def test_mismatched_lookup_population_is_rejected(self):
        self.pack["ancestry"]["analysis_based"]["af_population"] = "EAS"
        self.write_json(self.pack_path, self.pack)
        with self.assertRaisesRegex(ValueError, "查表人群必须"):
            reporting.collect_report(self.pack_path)

    def test_run_shortlist_obeys_af_quality_and_missing_policy(self):
        review = reporting.review
        rows = [
            ("rare", ".009", "15", "30"), ("equal", ".01", "15", "30"),
            ("unknown", "", "20", "60"), ("zero", "0", "10", "20"),
            ("low_dp", ".001", "9", "60"), ("low_gq", ".001", "12", "19"),
            ("missing", ".001", ".", "."), ("common", ".03", "15", "20")]
        with gzip.open(self.delivery / review.TABLE, "wt", newline="") as f:
            writer = csv.writer(f, delimiter="\t")
            writer.writerow(["record_id", "matched_pop_AF", "DP", "GQ"])
            writer.writerows(rows)
        for pct, keep, expected in [
                (1, False, ["rare", "zero"]), (1, True, ["rare", "zero", "missing"]),
                (5, False, ["rare", "equal", "zero", "common"]), (0, True, [])]:
            policy = dict(af_percent=pct, min_dp=10, min_gq=20, keep_missing_quality=keep)
            self.assertEqual(review.write_shortlist(self.delivery, policy), len(expected))
            with gzip.open(self.delivery / review.SHORTLIST, "rt") as f:
                self.assertEqual([r["record_id"] for r in csv.DictReader(f, delimiter="\t")], expected)

    def test_integrated_delivery_remains_portable_and_preserves_pack_references(self):
        original = self.pack_path.read_bytes()
        output = self.root / "unified"
        output.mkdir()
        self.assertEqual(deliver_popgen(output, {"popgen": {"artifact": file_spec(self.pack_path)}}, {}, "SYNTHETIC"), "complete")
        self.assertEqual(self.pack_path.read_bytes(), original)
        moved = self.root / "moved"
        output.rename(moved)
        html = (moved / "popgen/report.html").read_text()
        for link in Links(html).links:
            self.assertTrue((moved / "popgen" / link).is_file(), link)
        pack = json.loads((moved / "popgen/evidence_pack.json").read_text())
        for relative in pack["files"].values():
            self.assertTrue((moved / "popgen" / relative).is_file(), relative)
        self.assertIn('id="gnn-chart"', html)

    def test_downstream_reuse_finds_verified_original_pack(self):
        provenance = self.root / "prepared_manifest.source.json"
        self.write_json(provenance, {"inputs": {"evidence_pack": file_spec(self.pack_path)}})
        output = self.root / "reused"
        output.mkdir()
        self.assertEqual(deliver_popgen(output, {}, {"provenance/prepared_manifest.source.json": provenance}, "SYNTHETIC"), "complete")
        self.assertTrue((output / "popgen/report.html").is_file())

    def test_pack_builder_automatically_generates_the_report(self):
        partial = self.results / "partial_evidence.json"
        self.pack["ancestry"]["analysis_based"].update(af_source="AF_EUR", admixture_dominant="EAS", superpop="EUR", concordant=False)
        shutil.copyfile(self.delivery / "allele_freq.tsv", self.results / "allele_freq.tsv")
        self.write_json(partial, {"metadata": self.pack["metadata"], "ancestry": self.pack["ancestry"],
            "structure": self.pack["structure"], "findings": {"pca": {"pc_distance": {"EUR": .01, "SAS": .02}}}})
        pack = import_module("1_popgen.pack")
        output = pack.build_evidence_pack(partial, None, self.delivery, self.results)
        pack.validate_pack(output)
        self.assertEqual(output, self.pack_path)
        self.assertTrue((self.delivery / "popgen_report.html").is_file())
        self.assertEqual(json.loads(output.read_text())["files"]["report"], "popgen_report.html")
        self.assertIn("本次没有 GNN 结论", (self.delivery / "popgen_report.html").read_text())

    def test_other_sample_is_rejected(self):
        output = self.root / "wrong"
        output.mkdir()
        with self.assertRaisesRegex(ValueError, "样本或基因组"):
            deliver_popgen(output, {"popgen": {"artifact": file_spec(self.pack_path)}}, {}, "OTHER")


if __name__ == "__main__":
    unittest.main()
