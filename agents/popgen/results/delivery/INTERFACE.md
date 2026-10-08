# PopGen → e-Gene 接口说明（schema 1.0）

平台接入：读取本目录的 `evidence_pack.json`，再用同目录 `allele_freq.tsv` 按变异连接。不要解析步骤 2 的 `findings` 杂项。

## 必读文件

| 文件 | 作用 |
|---|---|
| `evidence_pack.json` | 祖先结论、查表人群、BA1 权限、用法硬规则 |
| `allele_freq.tsv` | 每个病人 VCF 变异的匹配人群 AF + 全球 AF |

连接键：`CHROM`, `POS`, `REF`, `ALT`（GRCh38，`chr1` 形式）。不要只按位置连接。

## 本样本（HG002）必须执行的行为

- 查表人群：`EUR`（`AF_EUR`）
- `use_for_acmg_ba1_bs1` = **false**
- `assignment` = `admixed`；`reason` = `pca_EUR_admixture_AFR_discordant`
- PCA 最近档 = `EUR`；监督最大档 = `AFR`。**最大 Q 不是祖先结论。**
- 因此：**禁止**用 `matched_pop_AF` 打 BA1/BS1。表仍可给人看，也可作罕见程度参考，但不能一票良性。
- 禁止改去查 AFR、GNN predicted，或任何最大 Q 档的频率。
- `structure.unsupervised_best_k` = 9 只描述 1000G 底库细结构，没有 `AF_K9`。

## GNN（步骤 3）

- `gnn_based.predicted` = `AMR`；`confidence` = 0.381819
- 同图 PCA3 最近档 = `EUR`；`concordant_with_pca3` = **false**
- `usable_for_lookup` = **false**
- `pca3_EUR_gnn_AMR_discordant`
- `sparse_overlap_with_genomewide_aims;exome_capture_can_shift_the_patient_node;report confidence but do not lock lookup;analysis_based.af_population stays authoritative`
- **禁止**用 GNN predicted 改查表人群。查表仍是 `analysis_based.af_population`。

## `usage.must` / `usage.must_not`

以 JSON 里的英文条款为准（机器可读）。上文是同一规则的中文说明。

## 本轮没有的字段

- 无 snpEff 基因后果、无 VQSR、无捕获 BED
- 频率表不含 BAM 补上的 0/0 位点

e-Gene 按本包调整即可；字段以 schema `contracts/evidence_pack.schema.json` 锁定。
