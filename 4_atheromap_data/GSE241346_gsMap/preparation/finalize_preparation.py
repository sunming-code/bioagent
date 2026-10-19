#!/usr/bin/env python3
"""Seal the preparation record after independent input checks have passed."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

root = Path(__file__).resolve().parent.parent
project = root.parent.parent

def read(name):
    return json.loads((root / name).read_text())

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

spatial = read('preparation/validation_spatial.json')
gwas = read('preparation/validation_gwas.json')
assert spatial['status'] == gwas['status'] == 'passed'
g = gwas['gwas']
assert g['retained_snps'] == 6137268 and g['source_membership_exact']
alignment = read('preparation/reference_alignment_audit.json')
exclusions = read('preparation/reference_exclusions.json')
assert exclusions['status'] == 'complete'
assert set(exclusions['removed_rsids']) == set(alignment['incompatible_rsids'])
assert g['ld_coordinate_mismatches'] == g['ld_allele_mismatches_including_strand_and_swap'] == 0
assert 'Missing/invalid items: 0' in (root / 'logs/check_inputs_gsmap_run.log').read_text()
files = read('preparation/prepared_files.json')
assert len(files['files']) == files['file_count'] == 270
status = read('preparation/status.json')
now = datetime.now(timezone.utc).isoformat()
notes = [
    '官方 YAML 的 author_notes 错配了无关研究；已通过官方研究 API 和目录导出确认性状为 Carotid plaque，Franceschini 等，2018，PMID 30510157。原 YAML 保留。',
    'SpaGCN 注释为区域编号。原脚本邻域修正后 sample1 为 6 个区域，sample2 为 7 个区域。'
]
if g['n_max'] != 48434:
    notes.append(f"官方整项研究样本数为 48,434，原始逐位点 N 最高为 {g['n_max']:g}；保留原始逐位点值，不按整项研究样本数改写。")
notes.append('已剔除 303 个无法与 LD panel 坐标和等位基因同时匹配的 rsID，其中 4 个位于回归交集。最终输入与 LD panel 的共有 rsID 没有坐标或等位基因不一致；官方转换备份和剔除明细均保留。')
provenance = read('preparation/GCST007435_provenance_review.json')
provenance['observed_formatted_sample_size'] = {'min':g['n_min'],'median':g['n_median'],'max':g['n_max'],'unique_values':g['n_unique'],'handling':'Source per-variant n is preserved. Study-level metadata is not used to overwrite it.'}
(root / 'preparation/GCST007435_provenance_review.json').write_text(json.dumps(provenance,ensure_ascii=False,indent=2)+'\n')
code = [project / '4_atheromap/tools/run_in_env.sh', project / '4_atheromap/gsmap/scripts/02_prepare_GSE241346_h5ad_spagcn.py', root / 'preparation/validate_inputs.py', root / 'preparation/audit_reference_alignment.py', root / 'preparation/filter_reference_mismatches.py', root / 'preparation/finalize_preparation.py']
formatter = Path(read('preparation/environment.json')['executable']).parent.parent / 'lib/python3.10/site-packages/gsMap/format_sumstats.py'
code.append(formatter)
manifest = {
    'schema_version':'1.0', 'stage':'prepare_gsmap_inputs', 'status':'complete',
    'started_at':status['started_at'], 'completed_at':now, 'workspace':str(root),
    'scope':['unpack_spatial_and_reference_resources','prepare_spatial_h5ad','format_and_qc_gwas','validate_input_contents_and_reference_overlap'],
    'spatial':spatial['spatial'], 'gwas':g,
    'coordinate_systems':{'gwas':'GRCh37, 1-based; unchanged from source','ld_and_gtf':'1000G EUR Phase3 and gencode.v46lift37 resources','spatial':'full-resolution pixel coordinates; column then row'},
    'reference_resources':{'directory':'resources/gsMap_resource','regular_files':238,'chromosomes_checked':22,'prepared_file_index':'preparation/prepared_files.json'},
    'original_sources':read('download_manifest.json')['files'],
    'prepared_files_index':{'path':'preparation/prepared_files.json','sha256':digest(root/'preparation/prepared_files.json'),'files':files['file_count'],'bytes':files['bytes']},
    'environment':'preparation/environment.json','commands':'preparation/commands.json',
    'validation_reports':['preparation/validation_spatial.json','preparation/validation_gwas.json'],
    'reference_alignment_audit_before_exclusions':alignment,
    'reference_exclusions':exclusions,
    'provenance_review':'preparation/GCST007435_provenance_review.json',
    'code':[{'path':str(p),'sha256':digest(p)} for p in code],
    'notes':notes,
    'attempt_notes':[
        'Initial command dispatch failed because conda run interpreted the formatter flag --n. The environment launcher now activates the requested prefix and execs the command; flag forwarding and real preparation commands passed.',
        'Initial GWAS validator used an interval comparison at the 1% allele-frequency boundary. Corrected to the official min(FRQ,1-FRQ) floating point calculation; the full source comparison was rerun.'
    ],
    'next_stage':'Run both samples through gsMap quick_mode; full association analysis and root pipeline integration have not been run in this preparation task.'
}
(root / 'preparation/inputs_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
lines = ['# gsMap 输入准备（已完成）','', '工作目录：`'+str(root)+'`。空间输入准备与 GWAS 质控转换均已完成，独立内容校验通过。','',
'| 样本 | 保留点位 | 保留基因 | SpaGCN 修正后区域数 |', '| --- | ---: | ---: | ---: |']
for row in spatial['spatial']:
    lines.append(f"| {row['sample']} / {row['geo_id']} | {row['retained_spots']:,} | {row['retained_genes']:,} | {len(row['domains'])} |")
lines += ['', '## 已准备的文件','',
'- [sample1 H5AD](data/spatial/GSE241346/h5ad/GSE241346_sample1_gsmap_spagcn.h5ad)',
'- [sample2 H5AD](data/spatial/GSE241346/h5ad/GSE241346_sample2_gsmap_spagcn.h5ad)',
'- [格式化 GWAS](data/gwas/GCST007435_gsmap.sumstats.gz)',
'- [官方转换结果备份（剔除参考不一致位点之前）](data/gwas/GCST007435_gsmap.official.sumstats.gz)',
'- [解包后的 gsMap 参考资源](resources/gsMap_resource/)',
'- [完整输入清单与验收记录](preparation/inputs_manifest.json)、[文件 SHA-256 清单](preparation/prepared_files.json)、[校验和文本](preparation/PREPARED_SHA256SUMS)',
'- [精确运行命令](preparation/commands.json)、[运行环境](preparation/environment.json)',
'- [空间内容校验](preparation/validation_spatial.json)、[GWAS 与参考资源校验](preparation/validation_gwas.json)',
'- [LD 差异是否进入回归的核查](preparation/reference_alignment_audit.json)、[差异明细表](preparation/GCST007435_ld_reference_mismatches.tsv)',
'- [参考不一致位点剔除记录](preparation/reference_exclusions.json)、[被剔除的 GWAS 记录](preparation/GCST007435_excluded_from_final_sumstats.tsv)',
'- [GWAS 来源及元数据冲突说明](preparation/GCST007435_provenance_review.json)',
'', '空间 H5AD 的 `.X` 和 `layers["count"]` 为整数原始计数，`obsm["spatial"]` 为原始像素坐标，`obs["annotation"]` 为 SpaGCN 区域编号。逐项核对了原始 MTX、基因合并、QC 成员、barcode、坐标和计数值。注释/QC 表位于 `data/spatial/GSE241346/metadata/`，图位于 `plots/GSE241346_spagcn/`。原脚本 QC 和模型参数保留。',
'', '## GWAS 转换与参考匹配','',
f"原始 {g['source_rows']:,} 个位点，官方 formatter 保留 {g['official_formatter_retained_snps']:,} 个，再剔除 303 个参考不一致位点，最终保留 {g['retained_snps']:,} 个，输出列为 `SNP A1 A2 Z N Chr Pos`。按 gsMap 1.73.8 官方规则去除非 SNP/方向不明确的组合及 N < 32,290 的位点；没有缺失值、非法 P 值或重复 rsID。保留位点的 GRCh37 / 1-based 坐标、效应等位基因和逐位点 N 均与源文件一致。Z 由 P 和 beta 符号生成，按官方格式保留三位小数，最大核对误差 {g['max_signed_z_rounding_error']:.9f}。官方 gsMap 读取函数往返检查通过。",
'', f"保留位点的 N 范围 {g['n_min']:g}–{g['n_max']:g}，中位数 {g['n_median']:g}，共 {g['n_unique']:,} 种取值。GWAS 与 baseline/weights 共有 {g['regression_snp_intersection']:,} 个 rsID；22 条染色体参考文件均已核对。与 LD panel 共有 {g['ld_reference_overlap']:,} 条记录，其中坐标不一致 {g['ld_coordinate_mismatches']:,} 条，考虑互换/互补后的等位基因不一致 {g['ld_allele_mismatches_including_strand_and_swap']:,} 条。",
'', '## 来源说明','',
f"原始归档和 GWAS 源文件保留，三个原始文件共 848,599,915 字节（约 0.85 GB），下载来源、原始 SHA-256 和完整性结果见 [download_manifest.json](download_manifest.json)。解包和准备后的文件（含官方转换备份）另占约 {files['bytes']/1e9:.2f} GB，合计约 {(files['bytes']+848599915)/1e9:.2f} GB，未计 Conda 环境。",
'', '注意事项：','']
lines += ['- '+n for n in notes]
lines += ['', '官方 API 和研究目录匹配行保存在 `download_metadata/`，确认 GCST007435 为 Carotid plaque，Franceschini 等，2018，PMID 30510157。',
'', '## 后续使用','',
'从项目根目录设置工作目录；当前默认本地配置仍指向原先的空工作目录，因此使用本批输入时必须设置该变量：','',
'```bash','export ATHEROMAP_GSMAP_WORK_DIR='+str(root),'python 4_atheromap/tools/check_inputs.py --stage gsmap-run','```',
'', '本次范围到输入准备与内容校验完成。下一步是对两个样本运行完整 gsMap quick mode 并验收空间关联结果，再处理根调度器接入。']
(root / 'README.md').write_text('\n'.join(lines)+'\n')
status.update(status='complete', completed_at=now, validation_status='passed', manifest='preparation/inputs_manifest.json', notes=notes)
(root / 'preparation/status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'status':'complete','manifest':str(root/'preparation/inputs_manifest.json'),'spatial_samples':2,'gwas_snps':g['retained_snps'],'reference_snp_overlap':g['regression_snp_intersection'],'notes':notes},ensure_ascii=False,indent=2))
