# e-Gene Pipeline UI

在仓库根目录启动本地页面：

```bash
1_popgen/.runtime/envs/popgen_gnn/bin/python -m uvicorn pipeline_ui.app:app --host 127.0.0.1 --port 8000
```

页面允许选择起止阶段，并根据开始阶段切换输入契约：PopGen 接 FASTQ 目录或 VCF，e-Gene 接
PopGen `evidence_pack.json`，GDgpt 接 e-Gene `report_manifest.json`，AtheroMap 接 GDgpt
`gdgpt_manifest.json`。后端把选择转换为根目录已有的 `run_pipeline.py` 参数，并用
`--end-stage` 在指定阶段发布成功的阶段清单。

当输入含有 VCF REF 与 GRCh38 不一致的记录时，页面会要求选择“报错并停止”或“排除并记录”；排除清单
会随 e-Gene 中间产物保存，页面不会静默改变策略。

`/api/runs/<id>/events` 使用 Server-Sent Events 读取统一流水线的原子清单、阶段日志和阶段目录中的
当前文件。阶段完成后立即显示其报告、manifest 和结构化 JSON；GDgpt 的逐任务文件也会在运行期间出现，
不需要等待整条链路或最终 ZIP。
