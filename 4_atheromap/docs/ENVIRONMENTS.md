# 分析环境与运行方式

环境分为三个独立的 Conda 前缀，不修改系统 Python、系统 R 或其他项目的环境。默认位置为 `$HOME/.conda/envs/`，可以通过 `ATHEROMAP_ENV_ROOT` 调整。

| 环境目录名 | 主要用途 | 固定的核心版本 |
| --- | --- | --- |
| `atheromap_scdrs` | 预处理、Harmony、scDRS 与 Python 绘图 | Python 3.10、scDRS 1.0.2、Harmony 0.0.10 |
| `atheromap_gsmap` | SpaGCN 分区、gsMap、空间结果检查 | Python 3.10、gsMap 1.73.8、SpaGCN 1.2.7、Torch 2.2.2 CPU |
| `atheromap_r` | scDblFinder、scran、H5AD 读取及 R 绘图 | R 4.4、scDblFinder 1.20.2、scran 1.34.0、zellkonverter 1.16.0 |

两个 Python 环境共用相同版本的数值计算栈：NumPy 1.26.4、Pandas 1.5.3、SciPy 1.11.4、Scanpy 1.9.8、AnnData 0.10.8。聚类后端、OpenCV、scikit-misc、Torch Geometric、R 绘图依赖，以及 H5AD 读取需要的 rhdf5 / HDF5Array 和稀疏矩阵运算需要的 sparseMatrixStats / DelayedMatrixStats 均列入安装文件。gsMap 环境固定 setuptools 69.5.1，以提供 louvain 0.8.2 仍使用的 pkg_resources。这些版本用于现有脚本的兼容性验证；原服务器历史环境仍未知，不能据此声称与历史分析结果完全一致。

GDgpt → scDRS 接口另使用 `jsonschema==4.23.0`，已列入 scDRS 依赖和完整 pip 快照。本机数据的新版 H5AD 空值元数据由运行入口在独立副本中兼容处理，记录见 [SCDRS_INTEGRATION.md](SCDRS_INTEGRATION.md)。

## 安装

在模块目录执行：

```bash
bash tools/setup_environments.sh
```

安装脚本先检查目标环境不存在，再创建环境；不会覆盖已有环境。也可单独安装 `scdrs`、`gsmap` 或 `r`：

```bash
bash tools/setup_environments.sh gsmap
```

`environments/*.yml` 和 `environments/*.txt` 记录环境定义及主要依赖版本。`environments/locks/` 保存本机验收环境的 Conda 明细及完整 pip 版本；Linux x86_64 重建时安装脚本优先使用这些锁定文件。Torch CPU 轮子从 PyTorch 官方索引安装。环境缓存默认位于 `$HOME/.cache/atheromap/conda-pkgs`。

## 配置及使用

首次使用时复制配置；已有本地配置时直接编辑：

```bash
cp config/paths.example.env config/paths.local.env
```

填写输入目录，核对分析工作目录。`ATHEROMAP_RSCRIPT` 默认指向独立 R 环境中的 `Rscript`，预处理会通过这个绝对路径调用 R。

推荐通过启动脚本选择环境，无需手动激活：

```bash
bash tools/run_in_env.sh scdrs python scdrs/scripts/overall_analysis/run_GSE159677_pre_scdrs_harmony.py
bash tools/run_in_env.sh scdrs bash scdrs/scripts/overall_analysis/run_GSE159677_scdrs_cli.sh
bash tools/run_in_env.sh gsmap python gsmap/scripts/02_prepare_GSE241346_h5ad_spagcn.py
bash tools/run_in_env.sh gsmap bash gsmap/scripts/03_gsmap_quick_mode_sample2.sh
bash tools/run_in_env.sh r Rscript scdrs/scripts/vsmc_subtype_analysis/plot_GSE159677_vsmc_violin_ggplot2.R
```

启动脚本读取 `config/paths.local.env`，不存在时读取示例配置；也可通过 `ATHEROMAP_PATHS_FILE` 选择配置文件。配置中的默认值保留调用者已设置的环境变量。运行参数和输入顺序仍按 [WORKFLOWS.md](WORKFLOWS.md) 执行。

启动脚本先激活指定 Conda 前缀，再直接执行命令，确保 `gsmap format_sumstats --n n` 等参数完整传给目标程序。

启动脚本启用无图形界面的 Matplotlib 后端、禁用用户级 Python 包，并将计算线程默认限制为 4；需要调整时设置 `ATHEROMAP_NUM_THREADS`。gsMap Shell 中原有 `MAX_PROCESSES=10` 不受该变量控制。

## 验证

依赖导入、`pip check`、R 包加载及命令帮助检查：

```bash
python tools/check_environments.py
```

进一步使用临时合成数据验证计算和 Python/R 交换：

```bash
python tools/check_environments.py --smoke
```

数值检查涵盖 Scanpy PCA / 邻居图 / Leiden / UMAP、Harmony、scDRS 评分与分组分析、通过项目原函数调用 scDblFinder 和 scran、Torch Geometric 运算、SpaGCN 训练预测、OpenCV 图像编解码及 Plotly / Kaleido 报告图像导出。测试数据和输出保存在临时目录并自动清理。依赖环境验收不等于真实 GSE159677 / GSE241346、GWAS 和 LD 参考数据的完整端到端复现。

原文件中的 CRLF 换行已对 Shell 和环境配置修正为 LF；`.gitattributes` 固定这两类文件的 Git 换行方式。

## 上游来源

- [scDRS](https://github.com/martinjzhang/scDRS)、[scDRS 1.0.2](https://pypi.org/project/scdrs/1.0.2/)
- [gsMap](https://github.com/JianYang-Lab/gsMap)、[gsMap 1.73.8](https://pypi.org/project/gsMap/1.73.8/)
- [SpaGCN 安装说明](https://github.com/jianhuupenn/SpaGCN/blob/master/tutorial/tutorial.md)
- [Scanpy 安装说明](https://scanpy.readthedocs.io/en/stable/installation.html)

没有使用这些新环境替代或猜测人工注释、trait 基因集、GWAS 转换及 cell2location 输入；相关边界见 [KNOWN_GAPS.md](KNOWN_GAPS.md)。
