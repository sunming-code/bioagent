#!/usr/bin/env python
"""Exclude rsIDs incompatible with LD panel, preserving official formatter output."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd

root=Path(__file__).resolve().parent.parent
original=root/'data/gwas/GCST007435_gsmap.official.sumstats.gz'
final=root/'data/gwas/GCST007435_gsmap.sumstats.gz'
audit=json.loads((root/'preparation/reference_alignment_audit.json').read_text())
excluded=set(audit['incompatible_rsids'])
assert len(excluded)==303
if not original.exists():
    final.rename(original)
data=pd.read_csv(original,sep='\t')
assert len(data)==6137571 and data.SNP.is_unique
removed=data.loc[data.SNP.isin(excluded)].copy()
assert set(removed.SNP)==excluded
result=data.loc[~data.SNP.isin(excluded)]
assert len(result)==6137268
removed.to_csv(root/'preparation/GCST007435_excluded_from_final_sumstats.tsv',sep='\t',index=False)
temporary=final.with_name(final.name+'.tmp')
result.to_csv(temporary,sep='\t',index=False,float_format='%.3f',compression='gzip')
temporary.replace(final)
report={'status':'complete','completed_at':datetime.now(timezone.utc).isoformat(),'reason':'rsID has no LD-panel record matching both GRCh37 coordinates and alleles (including swaps and strand complements)','official_formatter_output':str(original.relative_to(root)),'official_formatter_rows':len(data),'final_output':str(final.relative_to(root)),'final_rows':len(result),'removed_rsids':sorted(excluded),'removed_count':len(removed),'removed_from_regression_intersection':len(audit['incompatible_rsids_in_regression']),'excluded_rows':'preparation/GCST007435_excluded_from_final_sumstats.tsv','reference_comparison_table':audit['table'],'audit':'preparation/reference_alignment_audit.json','coordinate_or_allele_values_rewritten':False}
(root/'preparation/reference_exclusions.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k!='removed_rsids'},indent=2),flush=True)
