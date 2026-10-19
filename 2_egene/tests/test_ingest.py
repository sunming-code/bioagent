"""Focused correctness checks for the input adapter, not a clinical benchmark."""
from __future__ import annotations

import contextlib
import csv
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import pysam

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from egene import ingest
from egene.common import checksum, find_bcftools


def rows(path: Path) -> list[dict]:
    with path.open(newline="") as source:
        return list(csv.DictReader(source, delimiter="\t"))


class InputAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bcftools = find_bcftools()
        cls.converter = ROOT / "vendor/annovar/convert2annovar.pl"
        if not cls.converter.is_file():
            raise unittest.SkipTest("The authorized ANNOVAR converter is needed for integration checks")

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name) / "case with spaces"
        self.directory.mkdir()
        self.reference = self.directory / "reference.fa"
        self.sequence = "C" + "A" * 8 + "G" + "ACGT" * 120
        self.reference.write_text(">chr1\n" + self.sequence + "\n>chrX\n" + "A" * 100 + "\n")
        pysam.faidx(str(self.reference))
        # Only test fixtures override chromosome lengths; the CLI has no bypass.
        self.lengths = patch.object(ingest, "GRCH38_LENGTHS", {"chr1": len(self.sequence), "chrX": 100})
        self.lengths.start()
        self.addCleanup(self.lengths.stop)
        self.addCleanup(self.temporary.cleanup)

    def fixture(self, records=None, *, permission=True, omit_frequency=()):
        if records is None:
            records = [
                ("1", 10, "G", "T", "1/1:30:60:0,30:.", "PASS", "GT:DP:GQ:AD:PS", "70"),
                ("1", 6, "AA", "A", "0/1:30:60:15,15:.", "PASS", "GT:DP:GQ:AD:PS", "70"),
                ("1", 7, "A", "AA", "0/1:30:60:15,15:.", "PASS", "GT:DP:GQ:AD:PS", "70"),
                ("1", 11, "A", "C,G,T", "1|2:18:60:3,7,8,0:11", "PASS", "GT:DP:GQ:AD:PS", "70"),
                ("1", 19, "A", "T", "0/0", "PASS", "GT", "70"),
                ("1", 23, "A", "C", "./.", "PASS", "GT", "70"),
                ("1", 27, "A", "G", "./1", "PASS", "GT", "70"),
                ("1", 31, "A", "C", "0/1", "LowQual", "GT", "5"),
                ("1", 35, "A", "T", "0/1", ".", "GT", "."),
                ("1", 39, "A", "<DEL>", "0/1", "PASS", "GT", "70"),
                ("1", 15, "A", "G,C", "0/2:30:60:15,0,15:.", "PASS", "GT:DP:GQ:AD:PS", "70"),
                ("X", 5, "A", "G", "1", "PASS", "GT", "70"),
                ("Un", 5, "A", "G", "0/1", "PASS", "GT", "70"),
            ]
        header = (
            '##fileformat=VCFv4.2\n##reference=GRCh38\n'
            f'##contig=<ID=1,length={len(self.sequence)}>\n##contig=<ID=X,length=100>\n'
            '##contig=<ID=Un,length=100>\n'
            '##FILTER=<ID=LowQual,Description="Low quality">\n'
            '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
            '##FORMAT=<ID=DP,Number=1,Type=Integer,Description="Depth">\n'
            '##FORMAT=<ID=GQ,Number=1,Type=Integer,Description="Genotype quality">\n'
            '##FORMAT=<ID=AD,Number=R,Type=Integer,Description="Allelic depths">\n'
            '##FORMAT=<ID=PS,Number=1,Type=Integer,Description="Phase set">\n'
            '#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tTEST\n'
        )
        source = self.directory / "patient.vcf"
        source.write_text(header + "".join(
            "\t".join(map(str, (chrom, pos, ".", ref, alt, qual, filt, ".", fmt, genotype))) + "\n"
            for chrom, pos, ref, alt, genotype, filt, fmt, qual in records
        ))
        delivery = self.directory / "delivery"
        delivery.mkdir()
        af_rows = []
        for chrom, pos, ref, alts, *_ in records:
            for alt in alts.split(","):
                if (chrom, pos, ref, alt) in omit_frequency:
                    continue
                # Distinguish unknown from genuine AF=0 at the same multiallelic site.
                matched = "" if pos == 11 and alt == "C" else ("0" if pos == 11 and alt == "G" else "0.1")
                af_rows.append([chrom, pos, ref, alt, "EAS", matched, matched])
        with (delivery / "allele_freq.tsv").open("w", newline="") as target:
            writer = csv.writer(target, delimiter="\t", lineterminator="\n")
            writer.writerow(ingest.AF_COLUMNS)
            writer.writerows(af_rows)
        self.pack = {
            "schema_version": "1.0",
            "metadata": {"sample_id": "TEST", "genome_build": "GRCh38", "mode": "Real_Pipeline",
                         "variant_count": len(records)},
            "ancestry": {"analysis_based": {
                "superpop": "EAS", "pca_nearest": "EAS", "admixture_dominant": "EAS",
                "assignment": "in_reference" if permission else "admixed",
                "af_population": "EAS", "af_source": "AF_EAS", "use_for_acmg_ba1_bs1": permission,
                "reason": "fixture",
            }, "gnn_based": {"predicted": "AFR", "q": {"AFR": 0.99, "EAS": 0.01},
                            "qmax": 0.99, "usable_for_lookup": False}},
            "structure": {"catalog_k": 5, "catalog_k_meaning": "1000G_superpopulation_directory"},
            "allele_frequency": {"path": "allele_freq.tsv", "format": "tsv", "n_rows": len(af_rows),
                                 "join_key": ["CHROM", "POS", "REF", "ALT"],
                                 "columns": ingest.AF_COLUMNS, "matched_pop": "EAS"},
            "usage": {"must": ["preserve lookup population"], "must_not": ["do not replace unknown with zero"]},
            "files": {"patient_vcf": "../patient.vcf", "allele_frequency": "allele_freq.tsv"},
        }
        self.pack_path = delivery / "evidence_pack.json"
        self.save_pack()
        return self.pack_path

    def save_pack(self):
        self.pack_path.write_text(json.dumps(self.pack))

    def run_adapter(self, *extra, name="prepared with spaces"):
        args = ingest.argument_parser().parse_args([
            "--popgen-pack", str(self.pack_path), "--reference", str(self.reference),
            "--bcftools", str(self.bcftools), "--convert2annovar", str(self.converter),
            "--outdir", str(self.directory / name), *extra,
        ])
        with contextlib.redirect_stdout(io.StringIO()):
            manifest = ingest.prepare(args)
        return self.directory / name, manifest

    def test_end_to_end_indel_multiallelic_quality_and_unknown_frequency(self):
        self.fixture(omit_frequency=[("X", 5, "A", "G")])
        before = checksum(self.directory / "patient.vcf")
        out, manifest = self.run_adapter()
        self.assertEqual(checksum(self.directory / "patient.vcf"), before)
        self.assertEqual(manifest["counts"]["retained_variants"], 8)
        mappings = rows(out / "variant_mapping.tsv")
        retained = rows(out / "patient_variants.tsv")
        deletion = next(row for row in retained if row["source_POS"] == "6")
        self.assertEqual((deletion["POS"], deletion["REF"], deletion["ALT"]), ("1", "CA", "C"))
        self.assertEqual((deletion["ANNOVAR_START"], deletion["ANNOVAR_END"], deletion["ANNOVAR_REF"], deletion["ANNOVAR_ALT"]),
                         ("2", "2", "A", "-"))
        self.assertEqual(deletion["matched_pop_AF"], "0.1")
        insertion = next(row for row in retained if row["source_POS"] == "7")
        self.assertEqual((insertion["ANNOVAR_START"], insertion["ANNOVAR_REF"], insertion["ANNOVAR_ALT"]), ("1", "-", "A"))
        multi = [row for row in retained if row["source_POS"] == "11"]
        self.assertEqual({row["source_ALT"] for row in multi}, {"C", "G"})
        self.assertTrue(all(row["source_GT"] == "1|2" and row["original_AD"] == "3,7,8,0" for row in multi))
        self.assertTrue(all(row["original_PS"] == "11" and row["original_phased"] == "true" for row in multi))
        unknown = next(row for row in multi if row["ALT"] == "C")
        zero = next(row for row in multi if row["ALT"] == "G")
        self.assertEqual((unknown["matched_pop_AF"], unknown["af_status"]), ("", "missing"))
        self.assertEqual((zero["matched_pop_AF"], zero["af_status"]), ("0.0", "available"))
        haploid = next(row for row in retained if row["CHROM"] == "chrX")
        self.assertEqual((haploid["original_ploidy"], haploid["source_GT"], haploid["af_status"]), ("1", "1", "no_row"))
        self.assertEqual(next(row for row in mappings if row["source_POS"] == "27")["decision"], "partial_genotype")
        self.assertEqual(next(row for row in mappings if row["source_POS"] == "39")["decision"], "unsupported_variant")
        self.assertEqual(len(rows(out / "source_records.tsv")), 13)
        with pysam.VariantFile(str(out / "normalized.vcf.gz")) as vcf:
            self.assertEqual(len(list(vcf)), 8)
            self.assertEqual(len(list(vcf.fetch("chr1", 0, 2))), 2)
        self.assertEqual(len((out / "patient.avinput").read_text().splitlines()), 8)
        for spec in manifest["files"].values():
            self.assertEqual(checksum(out / spec["path"]), spec["sha256"])
        self.assertFalse((out / "work").exists())

    def test_ancestry_permission_and_gnn_are_preserved(self):
        self.fixture(permission=False)
        out, manifest = self.run_adapter()
        self.assertEqual(manifest["frequency_policy"]["lookup_population"], "EAS")
        self.assertFalse(manifest["frequency_policy"]["use_for_acmg_ba1_bs1"])
        self.assertTrue(all(row["matched_pop"] == "EAS" and row["use_for_acmg_ba1_bs1"] == "false"
                            for row in rows(out / "allele_freq.tsv")))

    def test_explicit_quality_threshold_excludes_missing_and_failed_filter(self):
        self.fixture()
        out, manifest = self.run_adapter("--min-dp", "20")
        self.assertEqual(manifest["counts"]["retained_variants"], 4)
        mappings = rows(out / "variant_mapping.tsv")
        self.assertEqual(next(row for row in mappings if row["source_POS"] == "35")["decision"], "quality_excluded")
        self.assertEqual(next(row for row in mappings if row["source_POS"] == "31")["decision"], "filtered")

    def test_wrong_reference_allele_fails_without_completed_manifest(self):
        self.fixture([("1", 10, "C", "T", "0/1", "PASS", "GT", "70")])
        with self.assertRaisesRegex(ValueError, "Reference allele mismatch"):
            self.run_adapter()
        out = self.directory / "prepared with spaces"
        self.assertEqual(json.loads((out / "status.json").read_text())["status"], "failed")
        self.assertFalse((out / "input_manifest.json").exists())

    def test_sample_mismatch_is_rejected(self):
        self.fixture()
        self.pack["metadata"]["sample_id"] = "ANOTHER_SAMPLE"
        self.save_pack()
        with self.assertRaisesRegex(ValueError, "VCF 必须仅包含"):
            self.run_adapter()

    def test_explicit_ref_mismatch_exclusion_is_audited_without_rewriting_genotypes(self):
        self.fixture([
            ("1", 10, "C", "T", "1/1", "PASS", "GT", "70"),
            ("1", 11, "A", "C", "0/1", "PASS", "GT", "70"),
        ])
        out, manifest = self.run_adapter("--ref-mismatch", "exclude")
        self.assertEqual(manifest["counts"]["retained_variants"], 1)
        bad = rows(out / "reference_mismatches.tsv")
        self.assertEqual((bad[0]["VCF_REF"], bad[0]["FASTA_REF"]), ("C", "G"))
        mapping = rows(out / "variant_mapping.tsv")[0]
        self.assertEqual((mapping["decision"], mapping["source_GT"], mapping["normalized_id"]),
                         ("reference_mismatch", "1/1", ""))
        self.assertEqual(json.loads((out / "input_qc.json").read_text())["reference_mismatch_records"], 1)

    def test_frequency_population_mismatch_is_rejected(self):
        self.fixture()
        path = self.directory / "delivery/allele_freq.tsv"
        path.write_text(path.read_text().replace("\tEAS\t", "\tAFR\t", 1))
        with self.assertRaisesRegex(ValueError, "查表人群不一致"):
            self.run_adapter()

    def test_orphan_frequency_variant_is_rejected(self):
        self.fixture()
        path = self.directory / "delivery/allele_freq.tsv"
        path.write_text(path.read_text().replace("1\t10\tG\tT", "1\t10\tG\tC", 1))
        with self.assertRaisesRegex(ValueError, "不属于输入 VCF"):
            self.run_adapter()

    def test_duplicate_normalization_is_not_silently_merged(self):
        self.fixture([
            ("1", 6, "AA", "A", "0/1", "PASS", "GT", "70"),
            ("1", 7, "AA", "A", "1/1", "PASS", "GT", "70"),
        ])
        with self.assertRaisesRegex(ValueError, "同一变异"):
            self.run_adapter()

    def test_empty_carried_set_is_explicit_and_indexed(self):
        self.fixture([("1", 10, "G", "T", "0/0", "PASS", "GT", "70")])
        out, manifest = self.run_adapter()
        self.assertEqual(manifest["counts"]["retained_variants"], 0)
        self.assertFalse(json.loads((out / "input_qc.json").read_text())["ready_for_annotation"])
        self.assertEqual((out / "patient.avinput").read_text(), "")
        with pysam.VariantFile(str(out / "normalized.vcf.gz")) as vcf:
            self.assertEqual(list(vcf), [])

    def test_existing_outputs_are_never_overwritten(self):
        self.fixture()
        out = self.directory / "prepared with spaces"
        out.mkdir()
        (out / "sentinel").write_text("preserve")
        with self.assertRaisesRegex(ValueError, "拒绝覆盖"):
            self.run_adapter()
        self.assertEqual((out / "sentinel").read_text(), "preserve")


if __name__ == "__main__":
    unittest.main()
