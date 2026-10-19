# 2026-10-18 · GDgpt → scDRS 真实数据接入验收

本记录验证第三阶段接口与现有 scDRS 数据续接。没有重新运行前三阶段或请求大模型，也没有重新聚类、改写人工注释或补造 GWAS 来源。

## 输入

- 上游：`runs/NA18526_RNF34_pipeline/delivery/gdgpt/gdgpt_manifest.json`，已完成的 NA18526 / RNF34 指定基因探索任务。
- 参考数据：`4_atheromap_data/GSE159677_scDRS`，25 个文件及 SHA-256 登记于 [参考清单](../config/GSE159677_scdrs.reference.json)。
- 已生成接口：`runs/NA18526_RNF34_atheromap_input_20261018/input_manifest.json`。
- 范围：`reference_context_only`，保留 RNF34 原始 VUS / background 证据。`z_score` 的疾病与 GWAS 来源未知；患者 ID 不对应参考 donor。

## 内容验收

| 对象 | 结果 |
| --- | --- |
| 总体注释 | 40,563 细胞，23 cluster；复核 CSV = 映射 CSV，应用后标签与最终注释/scDRS 输入一致 |
| Unknown | cluster 17 的 710 个细胞保留明确 Unknown 标签 |
| 巨噬细胞 | 7,498 → 7,055；移除 cluster 7 的 443 个细胞；最终 4 亚型 |
| VSMC | 5,112 → 4,935；移除 cluster 7 的 177 个细胞；最终 3 亚型；cluster 5/6/9 人工映射落实 |
| 协变量 | barcode、顺序、log_n_counts、mt_frac 与矩阵观测一致 |
| 分数 | 总体完整/简版 norm_score 一致；亚型分数与总体对应细胞一致 |
| 原细胞级 CSV | 行数、顺序、亚型、condition、分数与最终 H5AD 一致 |
| 基因集 | 标签 z_score；1,000 个唯一带权重基因，权重有效；本次重算实际匹配表达矩阵的基因为 962 个 |
| 格式兼容 | 三份工作副本省略 uns/pca/params/mask_var 的 null；路径及原值记录于 input_compatibility.json；源文件保留 |

## 分数复用与全部绘图

命令：

```bash
bash 4_atheromap/tools/run_scdrs.sh \
  --input-manifest runs/NA18526_RNF34_atheromap_input_20261018/input_manifest.json \
  --mode reuse --plots all \
  --outdir runs/NA18526_RNF34_atheromap_scdrs_validated_20261018
```

[结果报告](../../runs/NA18526_RNF34_atheromap_scdrs_validated_20261018/delivery/report.html) 和 [运行清单](../../runs/NA18526_RNF34_atheromap_scdrs_validated_20261018/atheromap_manifest.json) 的状态为 `complete`。13 个计算/绘图步骤均完成，包括 merge、10 个 Python 面板与两个 R 脚本；生成 24 个 PNG 和 3 个 PDF。全部 135 个登记文件通过大小与 SHA-256 复查，HTML 本地链接均存在。抽查总体注释面板和 VSMC R 条件小提琴图，图像可读取、内容完整。

RNF34 唯一对应 `ENSG00000170633`，已输出其总体细胞类、巨噬细胞亚型和 VSMC 亚型参考表达。亚型交付 TSV 含 reference cell ID；R 输入 CSV 由本次入口重新导出。原始分类不变，未建立诊断或个体患病概率。

## 完整重新评分

```bash
bash 4_atheromap/tools/run_scdrs.sh \
  --input-manifest runs/NA18526_RNF34_atheromap_input_20261018/input_manifest.json \
  --mode recompute --plots none \
  --outdir runs/NA18526_RNF34_atheromap_recompute_validated_20261018
```

[重算报告](../../runs/NA18526_RNF34_atheromap_recompute_validated_20261018/delivery/report.html) 和 [运行清单](../../runs/NA18526_RNF34_atheromap_recompute_validated_20261018/atheromap_manifest.json) 状态均为 `complete`。原 CLI 保留 `n_ctrl=1000`，评分与四类分组统计共耗时 1,815.628 秒，merge 耗时 50.778 秒；完整重算明显慢于默认分数复用。此模式未执行额外 Python/R 面板，保留 merge 的 7 张基础 PNG。

独立核验重算目录的 68 个登记文件全部通过大小和 SHA-256 检查。40,563 个细胞的重算 norm_score 与原交付完全一致，最大绝对差为 0，Pearson 相关为 1。巨噬细胞和 VSMC 的工作 H5AD、含 barcode 的 TSV、R 格式 CSV 与本次全局分数逐细胞一致；所有报告链接有效。

两个成功目录验收后再次检查输入接口及 25 个原始参考文件哈希，均未变化。可读机器记录与代码摘要见 [SCDRS_VALIDATION_20261018.json](SCDRS_VALIDATION_20261018.json)。

## 自动测试与环境

```bash
2_egene/.runtime/venv/bin/python -m unittest discover -s tests -v

PYTHONPATH=tests PYTHONNOUSERSITE=1 \
  "$HOME/.conda/envs/atheromap_scdrs/bin/python" -m unittest test_atheromap -v
```

根目录 22 项测试中，21 项通过，HDF5 科学环境测试在 e-Gene 环境跳过；在 scDRS 环境的 11 项接口测试全部通过，包括该项真实 HDF5 格式兼容测试。覆盖证据与频率权限保留、空任务、精确疾病匹配、排除记录、患者混用、任务/证据/范围篡改拒绝、原始数据和已有输出保护。该兼容测试确认源文件哈希不变，转换后 X、raw_counts 和 obs 与原内容一致。其余原三阶段回归检查继续通过。

测试日志：[接口与三阶段回归](validation_20261018/interface_and_regression.log)、[scDRS 环境接口及 HDF5](validation_20261018/scdrs_interface_and_hdf5.log)。

Python AST、JSON、Bash 语法及文档链接检查通过；scDRS 环境 `pip check` 无破损依赖。数值环境仍为 Python 3.10 / NumPy 1.26.4 / Pandas 1.5.3 / Scanpy 1.9.8 / AnnData 0.10.8 / scDRS 1.0.2，接口新增 jsonschema 4.23.0，R 绘图使用独立 R 环境。

## 验证边界

已验证从真实已完成 GDgpt 交付读取、生成可校验接口，再消费真实 scDRS 数据进行统计与绘图。原始单细胞预处理、重新聚类后人工注释、GWAS 来源核实、根统一调度器的第四阶段，以及 gsMap 空间数据均不在本次验收范围。

最早一次完整绘图尝试在新版 H5AD null 编码处失败，失败目录保留为 `runs/NA18526_RNF34_atheromap_scdrs_20261018`，状态为 failed；修复后在上述新的 validated 目录完整运行成功。应使用 validated 目录的交付。
