"""Derive a small INFO-only atlas from the documented IGSR public byte range."""
import csv
import hashlib
import json
import sys
import zlib
from pathlib import Path

URL = 'https://ftp.1000genomes.ebi.ac.uk/vol1/ftp/data_collections/1000G_2504_high_coverage/working/20220422_3202_phased_SNV_INDEL_SV/1kGP_high_coverage_Illumina.chr1.filtered.SNV_INDEL_SV_phased_panel.vcf.gz'


def extract(path):
    data=path.read_bytes();digest=hashlib.sha256(data).hexdigest();size=len(data);blocks=[]
    while data:
        reader=zlib.decompressobj(31);block=reader.decompress(data)
        if not reader.eof: break
        blocks.append(block);data=reader.unused_data
    folder=Path(__file__).with_name('references');folder.mkdir(exist_ok=True)
    tags=['AF','AF_EAS','AF_AMR','AF_EUR','AF_AFR','AF_SAS'];count=0
    with (folder/'igsr_frequency.tsv').open('w',newline='') as handle:
        writer=csv.writer(handle,delimiter='\t',lineterminator='\n');writer.writerow(['CHROM','POS','REF','ALT',*tags])
        for line in b''.join(blocks).decode().split('\n')[:-1]:
            if line.startswith('#'):continue
            fields=line.split('\t',8);info=dict(item.split('=',1) for item in fields[7].split(';') if '=' in item)
            for idx,alt in enumerate(fields[4].split(',')):
                if max(len(alt),len(fields[3]))>100 or set(alt+fields[3])-set('ACGTN'): continue
                values=[info.get(tag,'').split(',') for tag in tags];writer.writerow([fields[0],fields[1],fields[3],alt,*[val[idx] if len(val)>idx else '' for val in values]]);count+=1
    manifest={'url':URL,'assembly':'GRCh38','range':f'bytes=0-{size-1}','range_sha256':digest,'allele_rows':count,'info_fields':tags,'scope':'Complete records from complete BGZF blocks in the byte range. No individual genotypes. Not a chromosome-wide panel.'}
    (folder/'igsr_frequency.source.json').write_text(json.dumps(manifest,indent=2)+'\n');print(count)


if __name__=='__main__':extract(Path(sys.argv[1]))
