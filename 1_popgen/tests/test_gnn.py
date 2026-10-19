import os
import sys
import tempfile
import unittest
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'steps/03_gnn'))
from gnn_core import dosages_from_vcf, read_bed_indices


class GNNRegressionTests(unittest.TestCase):
    def test_vcf_dosages_match_checkpoint_bed_encoding(self):
        fixture=ROOT/'.runtime/validation/CHB_holdout.vcf'
        if not fixture.exists():
            self.skipTest('Run scripts/validate_pipeline.py to prepare the real reference sample')
        panel=ROOT/'data/reference/panel_1000g/ref_1000g_pruned'
        n=len(panel.with_suffix('.bim').read_text().splitlines())
        geno,iids,ids=read_bed_indices(panel,np.linspace(0,n-1,10000,dtype=int))
        with tempfile.TemporaryDirectory() as tmp:
            vec,observed=dosages_from_vcf(fixture,ids,Path(tmp))
        self.assertEqual(observed,10000)
        np.testing.assert_allclose(vec[0],geno[np.where(iids=='NA18526')[0][0]],equal_nan=True)

    def test_reversed_alleles_and_missing_genotypes(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp)
            p=tmp/'input with spaces.vcf'
            p.write_text('##fileformat=VCFv4.2\n##contig=<ID=chr1>\n##FORMAT=<ID=GT,Number=1,Type=String,Description="GT">\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS\nchr1\t100\t.\tA\tG\t.\tPASS\t.\tGT\t0|0\nchr1\t200\t.\tG\tA\t.\tPASS\t.\tGT\t0/0\nchr1\t300\t.\tA\tG\t.\tPASS\t.\tGT\t./.\n')
            vec,n=dosages_from_vcf(p,np.array(['chr1:100:A:G','chr1:200:A:G','chr1:300:A:G']),tmp)
            np.testing.assert_allclose(vec,[[2,0,np.nan]],equal_nan=True)
            self.assertEqual(n,2)


if __name__=='__main__':
    unittest.main()
