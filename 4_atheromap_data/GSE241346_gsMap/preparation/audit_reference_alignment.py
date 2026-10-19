#!/usr/bin/env python
"""Resolve LD reference differences by rsID and check actual regression SNPs."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow.feather as feather

root = Path(__file__).resolve().parent.parent
resources = root / 'resources/gsMap_resource'
out = pd.read_csv(root / 'data/gwas/GCST007435_gsmap.sumstats.gz', sep='\t', usecols=['SNP','Chr','Pos','A1','A2']).set_index('SNP')
hit = np.zeros(len(out), dtype=bool)
good = np.zeros(len(out), dtype=bool)
bad_rows = []
baseline = []
weights = []
complement = str.maketrans('ACGT','TGCA')
for chrom in range(1, 23):
    baseline.extend(feather.read_table(resources / f'quick_mode/baseline/baseline.{chrom}.l2.ldscore.feather', columns=['SNP']).column('SNP').to_pylist())
    weights.extend(pd.read_csv(resources / f'LDSC_resource/weights_hm3_no_hla/weights.{chrom}.l2.ldscore.gz', sep=r'\s+', usecols=['SNP']).SNP)
    bim = pd.read_csv(resources / f'LD_Reference_Panel/1000G_EUR_Phase3_plink/1000G.EUR.QC.{chrom}.bim', sep=r'\s+', header=None, names=['Chr','SNP','CM','Pos','A1','A2'])
    idx = out.index.get_indexer(bim.SNP)
    keep = idx >= 0
    idx = idx[keep]
    b = bim.loc[keep].reset_index(drop=True)
    t = out.iloc[idx].reset_index()
    same_pos = b.Chr.eq(t.Chr) & b.Pos.eq(t.Pos)
    observed, expected = t.A1+t.A2, b.A1+b.A2
    same_alleles = observed.eq(expected) | observed.eq(expected.str[::-1]) | observed.eq(expected.str.translate(complement)) | observed.eq(expected.str.translate(complement).str[::-1])
    hit[idx] = True
    np.logical_or.at(good, idx, (same_pos & same_alleles).to_numpy())
    bad = ~(same_pos & same_alleles)
    if bad.any():
        frame = t.loc[bad].copy()
        for col in ['Chr','Pos','A1','A2']: frame['LD_'+col] = b.loc[bad,col].to_numpy()
        frame['coordinate_match'] = same_pos.loc[bad].to_numpy()
        frame['allele_match_including_strand_and_swap'] = same_alleles.loc[bad].to_numpy()
        bad_rows.append(frame)
    print(f'Reference chromosome {chrom} audited', flush=True)
common = out.index.intersection(pd.Index(baseline)).intersection(pd.Index(weights))
strict_bad = out.index[hit & ~good]
rows = pd.concat(bad_rows, ignore_index=True) if bad_rows else pd.DataFrame(columns=['SNP'])
rows['has_any_matching_LD_record'] = rows.SNP.isin(out.index[good])
rows['in_regression_intersection'] = rows.SNP.isin(common)
rows.to_csv(root/'preparation/GCST007435_ld_reference_mismatches.tsv', sep='\t', index=False)
result = dict(status='reviewed', unique_rsids_without_any_matching_LD_record=len(strict_bad), mismatched_reference_rows=len(rows), regression_intersection_snps=len(common), mismatched_rows_in_regression=int(rows.in_regression_intersection.sum()), incompatible_rsids_in_regression=strict_bad.intersection(common).tolist(), incompatible_rsids=strict_bad.tolist(), table='preparation/GCST007435_ld_reference_mismatches.tsv')
(root/'preparation/reference_alignment_audit.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k!='incompatible_rsids'},indent=2), flush=True)
