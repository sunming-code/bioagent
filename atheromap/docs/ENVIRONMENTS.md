# 环境记录与依赖

本文件是依据源码得到的依赖清单，不是经过测试的锁定环境。不要把当前最新版全部安装后声称与历史结果一致。

建议优先保留原服务器可用环境，分别导出后再重建。scDRS、SpaGCN / gsMap、R 可以分环境运行，不需要强行装进一个环境。

| 组别 | 源码显示的主要依赖 |
| --- | --- |
| scDRS Python | scdrs CLI、scanpy、anndata、harmonypy、numpy、pandas、scipy、matplotlib、seaborn；Scanpy 聚类及 IO 还需对应后端依赖 |
| scDRS 预处理调用的 R | scDblFinder、SingleCellExperiment、BiocParallel、zellkonverter、scran、MatrixGenerics，以及这些包的传递依赖 |
| 可选 R 图 | ggplot2、dplyr、ggsignif、patchwork（巨噬细胞图） |
| gsMap / SpaGCN | gsmap CLI、SpaGCN、torch、cv2（OpenCV）、scanpy、anndata、numpy、pandas、scipy、matplotlib |
| gsMap review | h5py、numpy、pandas、matplotlib 等，详见 import_inventory.tsv |
| 输入检查工具 | Python 标准库；无第三方依赖 |

`docs/import_inventory.tsv` 是静态解析得到的导入清单，包含标准库；它不是可直接 `pip install -r` 的依赖文件，也不涵盖全部传递依赖、CLI 和嵌入式 R 包。

在实际用于分析的每个 Conda 环境中分别执行，输出放在自己的本地环境记录目录：

```bash
conda env export --no-builds > environment.yml
conda list --explicit > conda-explicit.txt
python -m pip freeze > requirements-freeze.txt
```

在原 R 环境执行：

```bash
Rscript -e 'sessionInfo()' > R-sessionInfo.txt
```

把不同环境保存到不同子目录，避免互相覆盖。上传前检查导出文件中的 `prefix:`、本地路径、私有仓库 URL 或 token，仅保留必要且可分享的环境信息。必要时记录 scDRS / gsMap 仓库的 commit，而不是只记录包名。

此前 scDRS Shell 自动切换到名为 `magma` 的环境；新版不再假设其他人有同名环境。由使用者先激活正确环境再运行。预处理用哪个 R 由 `ATHEROMAP_RSCRIPT` 指定。
