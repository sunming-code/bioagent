import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd
import pysam

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('analysis', ROOT / 'steps/02_analysis/popgen_agent.py')
analysis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis)
import sys
sys.path.insert(0, str(ROOT))
from input_vcf import prepare


class AnalysisRegressionTests(unittest.TestCase):
    def test_frequency_uses_exact_alleles_and_preserves_unknowns(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            panel = tmp / 'panel'
            panel.mkdir()
            header = pysam.VariantHeader()
            for c in ('chr1', 'chrX'):
                header.contigs.add(c)
            for tag in ['AF', *['AF_' + s for s in analysis.SUPERPOPS]]:
                header.info.add(tag, 'A', 'Float', tag)
            p = panel / '1kGP_high_coverage_Illumina.chr1.filtered.SNV_INDEL_SV_phased_panel.vcf.gz'
            with pysam.VariantFile(str(p), 'wz', header=header) as f:
                r = f.new_record(contig='chr1', start=99, alleles=('A', 'C', 'G'))
                for tag in header.info:
                    r.info[tag] = (0.1, 0.4)
                f.write(r)
            pysam.tabix_index(str(p), preset='vcf')
            source = tmp / 'input.vcf'
            with pysam.VariantFile(str(source), 'w', header=header) as f:
                for chrom, pos, ref, alt in [('chr1',100,'A','G'), ('chr1',100,'A','T'), ('chr1',100,'C','G'), ('chrX',100,'A','G')]:
                    f.write(f.new_record(contig=chrom,start=pos-1,alleles=(ref,alt)))
            original = analysis.PANEL_VCF_DIR
            try:
                analysis.PANEL_VCF_DIR = panel
                out = analysis.calc_matched_af(source, 'EAS', {}, tmp, tmp)
            finally:
                analysis.PANEL_VCF_DIR = original
            rows = pd.read_csv(out, sep='\t')
            self.assertEqual(len(rows), 4)
            self.assertAlmostEqual(rows.iloc[0].matched_pop_AF, 0.4, places=6)
            self.assertTrue(rows.iloc[1:].matched_pop_AF.isna().all())
            coverage = json.loads((tmp/'af_coverage.json').read_text())
            self.assertEqual(coverage['matched_reference_alleles'], 1)
            self.assertEqual(coverage['unsupported_contigs'], ['chrX'])

    def test_rejects_build_and_multiple_samples(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp)
            p=tmp/'bad.vcf'
            for extra, samples in [('##reference=GRCh37\n', 'S'), ('', 'S\tT')]:
                gt = '0/1\t0/1' if '\t' in samples else '0/1'
                p.write_text('##fileformat=VCFv4.2\n'+extra+'##contig=<ID=chr1,length=248956422>\n##FORMAT=<ID=GT,Number=1,Type=String,Description="GT">\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\t'+samples+'\nchr1\t100\t.\tA\tG\t.\tPASS\t.\tGT\t'+gt+'\n')
                with self.assertRaises(ValueError):
                    prepare(p, tmp/'output')

    def test_normalizes_contigs_sorts_and_splits_multiallelics(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp)
            source=tmp/'input.vcf'
            header='##fileformat=VCFv4.2\n##contig=<ID=1,length=248956422>\n##FORMAT=<ID=GT,Number=1,Type=String,Description="GT">\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tREAL_SAMPLE\n'
            source.write_text(header+''.join(f'1\t{pos}\t.\tA\tG\t.\tPASS\t.\tGT\t0/1\n' for pos in range(11000,1000,-1))+'1\t500\t.\tA\tC,G\t.\tPASS\t.\tGT\t1/2\n')
            meta=prepare(source,tmp/'output with spaces')
            self.assertEqual(meta['sample_id'],'REAL_SAMPLE')
            self.assertEqual(meta['variant_count'],10002)
            with pysam.VariantFile(str(tmp/'output with spaces/patient.vcf.gz')) as f:
                r=next(f.fetch('chr1',499,500))
                self.assertEqual(r.alts,('C',))


if __name__ == '__main__':
    unittest.main()
