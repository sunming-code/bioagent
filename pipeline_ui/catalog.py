"""Read-only module indexes over BioAgent references and stage deliveries."""
import csv
import json
import os
import re
import shutil
import subprocess
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PANEL = 'data_sources/popgen_panel/sample_superpop.tsv'
ALIASES = '2_egene/config/phenotype_aliases.json'
DISEASES = '2_egene/data/disease/genes_to_disease.txt'
KG = '3_GDgpt/kg_build/task_kg_output/'
NODES, EDGES = KG+'task_kg_nodes.csv', KG+'task_kg_edges.csv'
REVISION = '2844be81dfe297f24287902b1433c095a5499043'
DELIVERIES = {'frequencies': ('popgen', '01_popgen/delivery/allele_freq.tsv', 'delivery/popgen/allele_freq.tsv'),
              'classifications': ('egene', '02_egene/delivery/acmg_results.tsv', 'delivery/egene/acmg_results.tsv'),
              'candidates': ('egene', '02_egene/delivery/disease_candidates.tsv', 'delivery/egene/disease_candidates.tsv')}
EN_TERMS = {'HP:0001250':'Seizure','HP:0001263':'Global developmental delay','HP:0001249':'Intellectual disability','HP:0001252':'Hypotonia','HP:0000252':'Microcephaly','HP:0000256':'Macrocephaly','HP:0004322':'Short stature','HP:0000957':'Café-au-lait spot','HP:0000365':'Hearing impairment','HP:0000407':'Sensorineural hearing impairment','HP:0000510':'Retinitis pigmentosa','HP:0001251':'Ataxia','HP:0001324':'Muscle weakness','HP:0001638':'Cardiomyopathy','HP:0001639':'Hypertrophic cardiomyopathy','HP:0001382':'Joint hypermobility','HP:0002650':'Scoliosis'}


class Problem(ValueError):
    def __init__(self, code, status=400):
        self.code = code
        self.status = status
        super().__init__(code)


def read_rows(path, delimiter):
    with path.open(encoding='utf-8-sig', newline='') as handle:
        yield from csv.DictReader(handle, delimiter=delimiter)


@lru_cache(maxsize=4)
def dataset(kind):
    if kind == 'panel':
        return list(read_rows(ROOT/PANEL, '\t'))
    if kind == 'hpo':
        groups = defaultdict(list)
        for alias, code in json.loads((ROOT/ALIASES).read_text())['aliases'].items():
            groups[code].append(alias)
        return [{'HPO':code,'English':EN_TERMS.get(code,''),'aliases':' / '.join(terms)} for code, terms in groups.items()]
    if kind == 'nodes':
        return list(read_rows(ROOT/NODES, ','))
    if not (ROOT/DISEASES).is_file():
        raise Problem('no_disease_reference', 409)
    with (ROOT/DISEASES).open(encoding='utf-8-sig') as handle:
        header = handle.readline().lstrip('#').strip().split('\t')
        return list(csv.DictReader(handle, fieldnames=header, delimiter='\t'))


@lru_cache(maxsize=1)
def graph_index():
    grouped = defaultdict(list)
    for row in read_rows(ROOT/EDGES, ','):
        edge = (row['source_id'],row['source_name'],row['display_relation'],row['target_name'],row['target_id'],row['source'])
        grouped[edge[0]].append(edge)
        if edge[4] != edge[0]: grouped[edge[4]].append(edge)
    return grouped


def result(columns, rows, source, offset=0, limit=30, predicate=None):
    page, total = [], 0
    for row in rows:
        if predicate and not predicate(row): continue
        if offset <= total < offset+limit: page.append(row)
        total += 1
    return dict(columns=columns, rows=page, total=total, offset=offset, limit=limit, source=source)


def allele(query, population):
    match = re.fullmatch(r'(?:chr)?([1-9]|1[0-9]|2[0-2]):([1-9]\d{0,8}):([ACGTN]{1,100}):([ACGTN]{1,100})', query, re.I)
    if not match or population not in ('EUR','EAS','SAS','AFR','AMR'): raise Problem('allele_format')
    chrom, pos, ref, alt = match.groups(); chrom = 'chr'+chrom; ref, alt = ref.upper(),alt.upper()
    folder = Path(os.getenv('POPGEN_1000G_VCF_DIR', ROOT/'1_popgen/data/1000GP/20220422_3202_phased_SNV_INDEL_SV')).expanduser()
    file = folder/f'1kGP_high_coverage_Illumina.{chrom}.filtered.SNV_INDEL_SV_phased_panel.vcf.gz'
    cols = ['GRCh38','REF','ALT','population','matched_pop_AF','global_AF']
    if not file.is_file() or not any(Path(str(file)+ext).is_file() for ext in ('.tbi','.csi')):
        excerpt=ROOT/'pipeline_ui/references/igsr_frequency.tsv'
        for row in read_rows(excerpt,'\t'):
            if (row['CHROM'],row['POS'],row['REF'],row['ALT'])==(chrom,pos,ref,alt):
                values=[None if row[tag] in ('','.') else row[tag] for tag in ('AF_'+population,'AF')]
                return result(cols,[[f'{chrom}:{pos}',ref,alt,population,*values]],'IGSR · 20220422_3202 · GRCh38 / igsr_frequency.tsv')
        raise Problem('no_panel_vcf',409)
    binary = shutil.which('tabix')
    if not binary: raise Problem('no_tabix',409)
    try: proc = subprocess.run([binary,str(file),f'{chrom}:{pos}-{pos}'],capture_output=True,timeout=12,text=True,check=True)
    except (subprocess.SubprocessError,OSError): raise Problem('panel_read_error',409) from None
    rows=[]
    for record in proc.stdout.splitlines():
        fields=record.split('\t',8)
        if len(fields)<8 or fields[:2]!=[chrom,pos] or fields[3]!=ref or alt not in fields[4].split(','): continue
        index=fields[4].split(',').index(alt); info=dict(item.split('=',1) for item in fields[7].split(';') if '=' in item)
        def frequency(key):
            values=info.get(key,'').split(',');return values[index] if index<len(values) and values[index] not in ('','.') else None
        rows.append([f'{chrom}:{pos}',ref,alt,population,frequency('AF_'+population),frequency('AF')]);break
    return result(cols,rows,file.name)


def lookup(module, mode, query='', offset=0, run='', population='EUR', runs=None):
    if len(query)>160 or offset<0: raise Problem('invalid_query')
    term=query.strip().casefold(); limit=30
    if (module,mode)==('popgen','allele'): return allele(query.strip(),population)
    if (module,mode)==('gdgpt','edges'):
        if not term: raise Problem('node_required')
        node=next((row for row in dataset('nodes') if row['id'].casefold()==term),None)
        if not node: raise Problem('unknown_node',404)
        return result(['source_id','source_name','relation','target_name','target_id','source'],graph_index().get(node['id'],()),EDGES,offset)
    specs={('popgen','panel'):(PANEL,['IID','SUBPOP','SUPERPOP']),('egene','hpo'):(ALIASES,['HPO','English','aliases']),('egene','disease'):(DISEASES,['gene_symbol','ncbi_gene_id','disease_id','association_type','source']),('gdgpt','nodes'):(NODES,['name','type','id','source'])}
    if (module,mode) in specs:
        source,cols=specs[(module,mode)];rows=dataset(mode)
        keep=lambda row: all(word in ' '.join(str(item or '') for item in row.values()).casefold() for word in term.split())
        if mode=='nodes' and term:
            rows=sorted((row for row in rows if keep(row)),key=lambda row:(term not in (row['name'].casefold(),row['id'].casefold()),not row['name'].casefold().startswith(term),row['name']))
            keep=None
        return result(cols,([row.get(col) for col in cols] for row in rows if not keep or keep(row)),source,offset)
    if mode not in DELIVERIES or DELIVERIES[mode][0]!=module: raise Problem('invalid_query')
    if not re.fullmatch(r'ui_[0-9A-Za-z_-]{8,80}',run): raise Problem('select_run',409)
    base=((runs or ROOT/'runs')/run).resolve()
    if not base.is_relative_to((runs or ROOT/'runs').resolve()): raise Problem('select_run',409)
    for folder in (base/'output',base):
        for relative in DELIVERIES[mode][1:]:
            path=(folder/relative).resolve()
            if not path.is_relative_to(base) or not path.is_file():continue
            with path.open(newline='',encoding='utf-8-sig') as handle:
                reader=csv.DictReader(handle,delimiter='\t'); fields=reader.fieldnames or []
                priority=['gene','gene_symbol','disease_id','disease_name','normalized_id','classification','integrated_classification','priority_band'];cols=list(dict.fromkeys([key for key in priority if key in fields]+fields))[:14]
                out=result(cols,([row.get(col) for col in cols] for row in reader if all(word in ' '.join(str(val or '') for val in row.values()).casefold() for word in term.split())),relative,offset)
                out['file_url']=f'/api/runs/{run}/files/{relative}';return out
    raise Problem('no_artifact',409)


def calculate(module, value):
    if module=='popgen':
        selector=value.strip().upper();rows=dataset('panel');counts=Counter((row['SUPERPOP'],row['SUBPOP']) for row in rows if selector in ('',row['SUPERPOP'],row['SUBPOP']))
        if not counts: raise Problem('no_match')
        total=sum(counts.values());return result(['SUPERPOP','SUBPOP','samples','percent'],([sup,sub,num,round(num*100/total,2)] for (sup,sub),num in sorted(counts.items())),PANEL,limit=len(counts))
    if module=='egene':
        terms=list(dict.fromkeys(part.strip() for part in re.split(r'[,，;；\n]+',value) if part.strip()))
        if not 1<=len(terms)<=100: raise Problem('terms_required')
        index={key.casefold():row for row in dataset('hpo') for key in [row['HPO'],row['English'],*row['aliases'].split(' / ')]}
        return result(['input','HPO','English'],([term,index.get(term.casefold(),{}).get('HPO'),index.get(term.casefold(),{}).get('English')] for term in terms),ALIASES,limit=len(terms))
    if module=='gdgpt':
        matches=[row for row in dataset('nodes') if value.strip().casefold() in (row['id'].casefold(),row['name'].casefold())]
        if len(matches)!=1:raise Problem('unique_node')
        node=matches[0]['id'];edges=graph_index().get(node,()); groups=defaultdict(list)
        for src,_,rel,__,target,___ in edges:
            groups[(rel,'out' if src==node else 'in')].append(target if src==node else src)
        out=result(['relation','direction','edges','neighbors'],([rel,direction,len(items),len(set(items))] for (rel,direction),items in sorted(groups.items(),key=lambda pair:-len(pair[1]))),EDGES,limit=max(1,len(groups)));out['node']=node;return out
    raise Problem('invalid_query')
