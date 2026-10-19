# 2026-10-18 · gsMap 真实数据验收

GSE241346_sample1 / sample2 的完整 gsMap quick mode 已通过验收。保留原脚本与科学参数，用固定 atheromap_gsmap 环境运行；并行运行两个样本，每样本 10 个空间 LDSC 工作线程，数值库线程设为 2。

| 样本 | 点位 | 分区 | 点位 BH q<0.05 | 分区 BH q<0.05 | 运行时间 |
| --- | ---: | ---: | ---: | ---: | ---: |
| GSE241346_sample1 | 1,804 | 6 | 439 | 6/6 | 220.4 秒 |
| GSE241346_sample2 | 1,039 | 7 | 235 | 6/7 | 186.3 秒 |

两次执行均使用 6,137,268 个质控 GWAS 位点，与 baseline / weights 共有 1,045,692 个 SNP；没有位点因默认 chi-square 阈值 80 被过滤。步骤包括潜在表示、基因映射、quick-mode 参考复用、空间 LDSC、Cauchy 组合和完整 HTML 报告。

## 结果核对

- 两个样本无点位丢失；count、空间坐标、分区与源 H5AD 一致，潜在表示和 marker score 无非有限值。
- 每个点位的 Z 和单侧 P 根据 beta / SE 复核；各分区 Cauchy 和中位数按原异常值策略独立复算。
- 基因诊断 PCC / 分区 GSS 中位数全部重算吻合，误差为浮点舍入量级。
- 每份 HTML 的统计表与源 CSV 一致，50 个基因、100 张表达/GSS PNG 齐全。
- Chromium 130 打开本地报告，空间图点数分别为 1,804 / 1,039，曼哈顿图各 100,000 点；基因切换和运行信息展开正常，没有 JavaScript 或资源加载错误。截图已目视核对。

BH q 值为验收额外补充的样本内校正，空间点和分区分别计算。区域编号未赋予人工病理命名，跨样本同号分区不代表相同组织类型。此次验证不等于根调度器已接入第四阶段，也不包含依赖 cell2location 的额外 review 汇总。

## 报告与验收记录

- [GSE241346_sample1 报告](../../4_atheromap_data/GSE241346_gsMap/results/gsmap_quick_mode/GSE241346/GSE241346_sample1/report/GCST007435/GSE241346_sample1_GCST007435_gsMap_Report.html)
- [GSE241346_sample2 报告](../../4_atheromap_data/GSE241346_gsMap/results/gsmap_quick_mode/GSE241346/GSE241346_sample2/report/GCST007435/GSE241346_sample2_GCST007435_gsMap_Report.html)

- [完整验收说明、打包报告和统计表](../../4_atheromap_data/GSE241346_gsMap/validation/gsmap_real_samples/README.md)
- [机器可读验收清单](../../4_atheromap_data/GSE241346_gsMap/validation/gsmap_real_samples/validation_manifest.json)
- [输入准备说明](GSMAP_INPUTS.md)

查看或传递报告时保留完整 report/GCST007435 目录，或使用完整 ZIP。模板中的 Bootstrap CSS / JS 需网络访问 jsDelivr。原始数据、预处理输入和科学输出未因校验而改写。

## 重复验收

从项目根目录运行：

```bash
bash 4_atheromap/tools/run_in_env.sh gsmap python 4_atheromap/tools/validate_gsmap_results.py --root /hpc2hdd/home/msun663/e-gene/4_atheromap_data/GSE241346_gsMap
/hpc2hdd/home/msun663/.cache/atheromap/report_browser/bin/python 4_atheromap/tools/check_gsmap_reports_browser.py --root /hpc2hdd/home/msun663/e-gene/4_atheromap_data/GSE241346_gsMap
```

浏览器工具使用单独的 Playwright 1.48.0 环境，未修改科学计算环境。gsMap 原入口会按文件是否存在跳过已完成阶段；更换输入或参数时应创建新的结果目录，不能用当前输出存在来替代输入指纹核对。
