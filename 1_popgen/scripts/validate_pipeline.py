"""Export a known sample, exclude it from reference nodes, and run the real pipeline.

This verifies file/feature consistency and execution; it is not independent model validation.
"""
from __future__ import annotations
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from runtime import run_in_environment


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--outdir',type=Path,required=True)
    p.add_argument('--skip-cv',action='store_true')
    args=p.parse_args()
    work=ROOT/'.runtime/validation'
    work.mkdir(parents=True,exist_ok=True)
    panel=ROOT/'data/reference/panel_1000g/ref_1000g_pruned'
    rows=panel.with_suffix('.bim').read_text().splitlines()
    indexes=[i*(len(rows)-1)//9999 for i in range(10000)]
    (work/'snps.txt').write_text(''.join(rows[i].split()[1]+'\n' for i in indexes))
    sample=next(row.split() for row in panel.with_suffix('.fam').read_text().splitlines() if row.split()[1]=='NA18526')
    (work/'keep.txt').write_text(f'{sample[0]}\t{sample[1]}\n')
    run_in_environment('popgen_analysis',['plink2','--bfile',str(panel),'--keep',str(work/'keep.txt'),
        '--extract',str(work/'snps.txt'),'--export','vcf','id-paste=iid','--output-chr','chrM','--out',str(work/'CHB_holdout')])
    command=[sys.executable,str(ROOT/'orchestrator.py'),'--vcf',str(work/'CHB_holdout.vcf'),'--outdir',str(args.outdir.resolve())]
    if args.skip_cv:command.append('--skip-cv')
    subprocess.run(command,check=True)
    pack=json.loads((args.outdir/'delivery/evidence_pack.json').read_text())
    assert pack['metadata']['sample_id']=='NA18526'
    assert pack['ancestry']['analysis_based']['pca_nearest']=='EAS'
    assert pack['ancestry']['gnn_based']['predicted']=='EAS'
    print('Execution and known-sample ancestry checks passed:', args.outdir)


if __name__=='__main__':main()
