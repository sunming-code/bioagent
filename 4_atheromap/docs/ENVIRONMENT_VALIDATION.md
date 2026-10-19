# 2026-10-16 · 换行与依赖环境验收

本次在当前服务器完成了换行修复、三个独立环境的实际安装及合成数据运行验证。平台为 Ubuntu 20.04 / Linux x86_64，Python 3.10.22，R 4.4.3。

## 换行修复

- 修复 4 个原始 Shell 脚本和 `config/paths.example.env` 中的 CRLF；新建的本地配置也使用 LF。
- 原始 4 个 Shell 脚本全部通过 `bash -n`，加上两个新环境工具共 6/6 通过。
- 配置文件经过实际 `source` 检查，所有 `ATHEROMAP_*` 变量均不含回车字符。
- `.gitattributes` 固定 Shell 和 env 文件使用 LF。4 个原始 Shell 的修复后 SHA256 与 `source_manifest.tsv` 中的 LF 基线一致；没有修改其分析参数。

## 已安装环境

默认根目录为 `$HOME/.conda/envs/`：

| 环境 | 核心组件 | 状态 |
| --- | --- | --- |
| `atheromap_scdrs` | scDRS 1.0.2、Harmony 0.0.10、Scanpy 1.9.8、AnnData 0.10.8 | 安装并验证通过 |
| `atheromap_gsmap` | gsMap 1.73.8、SpaGCN 1.2.7、Torch 2.2.2 CPU、Torch Geometric 2.5.3 | 安装并验证通过 |
| `atheromap_r` | R 4.4.3、scDblFinder 1.20.2、scran 1.34.0、zellkonverter 1.16.0 | 安装并验证通过 |

补齐了 zellkonverter 原生 R 读取模式需要的 rhdf5 / HDF5Array，以及 MatrixGenerics 稀疏矩阵计算需要的 sparseMatrixStats / DelayedMatrixStats。gsMap 环境使用 setuptools 69.5.1，满足旧版 louvain 对 pkg_resources 的调用。

两个 Python 环境设置 `PYTHONNOUSERSITE=1`，避免用户级包覆盖固定版本；启动工具还设置无图形界面的 Matplotlib 后端。安装过程中曾被 pip 替换的用户级 Pandas 已恢复为原版本 2.3.3，项目环境使用各自的 Pandas 1.5.3。

完整 Conda 包 URL、全部已安装 Python 发行包版本及 R sessionInfo 保存于 [`environments/locks/`](../environments/locks/)。Python 锁定文件没有包含 Conda 构建机器的本地安装路径。

## 实际运行验证

合成矩阵为 240 个细胞 / spots × 1200 个基因，不使用真实研究数据。验证输出保存在临时目录并自动清理。

| 验证内容 | 结果 |
| --- | --- |
| 两个 Python 环境的 `pip check`、主要依赖导入 | 通过 |
| 14 个 R 包的实际加载 | 通过 |
| scDRS `compute-score` / `perform-downstream`、gsMap `quick_mode` 命令帮助 | 通过 |
| gsMap 完整流程模块 `gsMap.run_all_mode` 导入 | 通过 |
| Scanpy PCA、邻居图、Leiden、UMAP | 两个 Python 环境均通过 |
| Harmony 计算及有限值检查 | 通过 |
| 原 `run_GSE159677_prepare_scdrs.py` 生成 H5AD 与协变量 | 通过 |
| 原 `run_GSE159677_scdrs_cli.sh` 评分，保留 `n_ctrl=1000` | 通过，生成 240 个细胞的分数 |
| 原 Shell 中的四类分组分析 | 通过，确认四个输出文件存在 |
| 原预处理函数 `run_scDblFinder` 的 Python → R → Python 调用 | 通过，细胞对应及双细胞输出列检查通过 |
| 原预处理函数 `run_acosh_norm` 调用 scran | 通过，size factor 有限且为正，生成 acosh 层 |
| Torch Geometric 图卷积、SpaGCN 邻接矩阵 / 训练 / 预测 | 通过 |
| OpenCV PNG 编解码、Plotly / Kaleido 报告图像导出 | 通过 |
| 当前 31 个 Python 文件 AST | 31/31 通过 |

对应日志：

- [scDRS 与 Python/R 联动](validation/scdrs-smoke.log)
- [gsMap / SpaGCN 及图像导出](validation/gsmap-smoke.log)
- [R 包加载](validation/r-packages.log)

可用以下命令重新验证，运行方式见 [ENVIRONMENTS.md](ENVIRONMENTS.md)：

```bash
python tools/check_environments.py --smoke
```

这次完成的是当前机器上的依赖兼容性与合成数据验收。没有运行完整 GSE159677 / GSE241346 真实数据、真实 GWAS / LD 参考资源的 gsMap quick mode，也没有核对历史结果一致性、实际数据的内存与耗时。人工注释和附属输入缺口仍按 [KNOWN_GAPS.md](KNOWN_GAPS.md) 处理。
