# 2026-10-18 · 四阶段统一入口验收

已从已有的真实三阶段任务 `NA18526_RNF34_pipeline` 续接第四阶段，命令为：

```bash
python run_pipeline.py \
  --resume-from runs/NA18526_RNF34_pipeline/pipeline_manifest.json \
  --with-atheromap \
  --outdir runs/NA18526_RNF34_pipeline_atheromap_final
```

本次续接复用了已有 PopGen、e-Gene 和 GDgpt 清单，只执行新增的 `05_atheromap`，没有改写原三阶段结果。最终清单显示四个阶段均为 `complete`，统一样本为 `NA18526`，统一交付 ZIP 约 2.15 GB，包含 600 个经过 SHA-256 记录的交付文件。

第四阶段包括：

- GDgpt → AtheroMap 接口重新校验，患者 ID、GRCh38、任务、变异证据和来源清单一致。
- scDRS `reuse` 模式，复用已验收 GSE159677 参考分数，处理 40,563 个外部参考细胞，完整 Python/R 图和统计交付完成。
- 已验收 GSE241346 gsMap 空间结果挂接；两个真实样本的空间 LDSC、Cauchy 分组统计和 HTML 浏览器验收状态均为 `passed`。
- 根统一报告新增 `delivery/atheromap/report.html`，并可从 `delivery/index.html` 进入；完整第四阶段内容位于 `delivery/atheromap/`。

结果入口：

- [统一报告](runs/NA18526_RNF34_pipeline_atheromap_final/delivery/index.html)
- [AtheroMap 第四阶段报告](runs/NA18526_RNF34_pipeline_atheromap_final/delivery/atheromap/report.html)
- [统一结构化清单](runs/NA18526_RNF34_pipeline_atheromap_final/pipeline_manifest.json)
- [完整离线交付包](runs/NA18526_RNF34_pipeline_atheromap_final/delivery.zip)

四阶段统一入口需要显式指定 `--with-atheromap`；不指定时保持原三阶段行为，便于只复用前三阶段或在没有第四阶段外部数据的机器上检查上游流程。AtheroMap 结果仍按外部 GSE159677 / GSE241346 队列解释，不修改患者 ACMG 分类，不建立患者诊断或个体患病概率。
