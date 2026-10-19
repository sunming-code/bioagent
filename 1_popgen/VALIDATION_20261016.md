# 2026-10-16 运行与验证记录

必要环境、VCF 输入处理、GNN 推理、频率查询、交付打包和网页任务入口已完成本机验证。

## 环境

- 分析环境：`/hpc2hdd/home/msun663/project/popgen_analysis`
- 推理与网页环境：`/hpc2hdd/home/msun663/project/popgen_gnn`
- `scripts/check_runtime.py` 检查通过；两套环境的精确 conda 包清单重建 dry run 通过。
- GNN：PyTorch 2.1.0 CPU + PyG 2.4.0，无需 GPU。

## 实际 VCF 执行

输入为参考样本 NA18526 的 10,000 个 SNP，执行时从分析底库和 GNN 参考节点中移除该样本。运行命令使用 `scripts/validate_pipeline.py --outdir results/validation_current --skip-cv`。

- PCA 最近超群：EAS。
- 监督 ADMIXTURE：EAS，Q=0.99996。
- GNN：EAS，置信分 0.999724；与 PCA3 一致。
- GNN 有效交集：1,003 / 30,000 个训练位点。
- 频率表：10,000 行；7,716 行与原始参考 VCF 精确匹配，2,284 行 AF 留空，未将未知频率写成零。
- `delivery/evidence_pack.json` 通过 schema 校验，包内所有非空文件引用均存在。
- 结果：`results/validation_current/`；可解压交付包：`results/validation_current/popgen_delivery.zip`。

PLINK 导出的测试 VCF 中存在与原始 VCF REF/ALT 表达不一致的位点，因此此样例不要求全部 AF 可匹配。测试用于执行和编码一致性验证，不能作为独立临床性能评价；模型训练时使用过参考样本。

## 无监督 CV 与动态 K

另外使用同一真实底库的 150 个参考样本（五个人群各 30 人）、600 个 SNP 验证完整 CV 分支与最佳 K 投影。执行 K=2–6 后满足连续三档无改善的停止条件，最佳 K=3，成功生成 `admixture_unsupervised_K3.tsv`，患者成分和为 1。

记录：`.runtime/validation/cv_branch/validation.json`。较大的重复 CV 检查在完成 K=2–5 后终止；它没有生成完整交付物，状态记录在 `results/validation_20261016/VALIDATION_STATUS.json`。生产默认流程保留完整 CV，用户也可显式使用 `--skip-cv`。

## 回归与网页检查

- 分析：3 项通过，覆盖多等位频率精确匹配、未知 AF 保留、错误参考版本/多样本拒绝、染色体命名与排序/索引。
- GNN：2 项通过；同一样本 10,000 个 VCF 位点与 checkpoint 的 BED 剂量编码一致，反向等位基因和缺失 GT 处理通过。
- 网页：3 项通过，覆盖成功结果展示和 ZIP 引用、上传失败反馈、同名文件任务隔离。
- ZIP 无重名条目，解压后所有证据包相对引用都有效。
- 本地 HTTP 首页、Chart.js 静态文件、任务接口均返回 200；前端 JavaScript 语法检查通过。

已修复的两个计算问题：患者 VCF 与训练 BED 的剂量方向相反；ADMIXTURE 投影时患者与参考的等位基因方向不一致。模型权重未修改。
