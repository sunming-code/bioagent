# HG002 外显子 FASTQ → VCF · GIAB v4.2.1 concordance

比较范围：chr1–22 ∩ GIAB 高置信 BED  
Query：`results/patient.vcf.gz`  
Truth：`data/truth/HG002_GRCh38_v4.2.1_benchmark.vcf.gz`  
方法：`bcftools view -T BED` 后 `bcftools isec`

| 集合 | 条数 |
|---|---|
| Query ∩ 高置信 | 792,937 |
| Truth ∩ 高置信（全基因组金标准） | 3,890,499 |

| 类型 | TP | FP | FN | Precision | Recall |
|---|---|---|---|---|---|
| 全部 | 705,791 | 87,146 | 3,184,708 | **0.890** | 0.181 |
| SNP | 644,198 | 73,838 | 2,722,176 | **0.897** | 0.191 |
| INDEL | 61,625 | 13,321 | 463,747 | **0.822** | 0.117 |

**怎么读这些数：**

- **Precision ~89%（SNP ~90%）是这次该看的主指标。** 我们在高置信区报出来的变异，约 9 成与 GIAB 一致。对第一轮、无捕获 BED、未做 VQSR/hard-filter 的 HaplotypeCaller 原输出，这个水平合理。
- **Recall ~18% 不能当失败。** Truth 是全基因组，输入是外显子。金标准里大部分位点我们根本没测到，FN 会被 WGS 真值撑大。没有捕获试剂盒 BED 之前，不宜用 recall 卡关。
- 第一轮通过标准（手册）：`patient.vcf` 存在、变异 ≫ 1 万、contig 为 `chr`、能和 truth 做 isec —— **已满足。**

产物目录：`/home/wangy/RBM_popgen/popgen_agent/results/concordance/`
