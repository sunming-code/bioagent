# 本次验证记录

整理日期：2026-10-11。源文件：用户上传的 `atheromap_source_review_0_aw2l8n.tar.gz`。

## 已完成

- Python AST 语法解析：**29/29** 通过，其中 28 个原分析脚本、1 个新增只读输入检查工具。没有导入或执行科学计算脚本。
- Bash `-n` 语法检查：**4/4** 通过。
- 新旧 Python 顶层函数 / 类的 AST 对比：**28/28** 脚本一致；未改变其中的分析函数。配置层改动见 `source_manifest.tsv`。
- 输入检查工具：缺失文件返回非零状态，且不创建工作目录；完整的路径占位文件通过存在性检查；同一样本有多个匹配原始文件时拒绝通过。
- scDRS Shell 启动接口：使用临时 stub 记录参数，确认传入配置路径、保留 `n_ctrl=1000`，并用具名路径参数调用 downstream。stub 未计算任何疾病分数。
- 对交付脚本作常见凭据模式扫描，未检出相应模式；这不是完整安全审计。

## 未完成

- 本环境没有 Rscript，两个 R 绘图脚本未进行 R 解析或执行。
- 未安装并验证完整 scDRS / gsMap / SpaGCN / R 环境。
- 未读取真实 H5AD、GWAS、marker、基因集或 cell2location 数据。
- 未核对旧编号文件与脚本预期文件的内容等价性。
- 未运行单细胞、空间流程，未确认结果图、P 值、内存需求、运行时间或生物学结论。
- 未创建 GitHub 远程分支、Pull Request 或上传文件。

因此本版状态是：**可供团队审阅的源码整理包，附配置及交接文档；不等于已完整复现的软件发布版。**

## 路径整理说明

1. scDRS Python / Shell / R 工作目录统一读取 `ATHEROMAP_SCDRS_WORK_DIR`；预处理输入和 Rscript 独立配置。
2. gsMap 工作目录统一读取 `ATHEROMAP_GSMAP_WORK_DIR`；不依赖启动命令时的当前目录或原用户名。
3. gsMap review 脚本将输出写到工作目录中新的 `*_atheromap` 文件夹。
4. scDRS Shell 不再自动激活某个固定名字的 Conda 环境，并增加输入文件存在检查。
5. scDRS downstream 路径采用官方 CLI 的具名参数；gsMap Shell 将 H5AD 路径作为 Python argv 传递。

这些改动不解决缺失的数据、环境锁定文件或人工判断步骤，也不自动移动原服务器中的任何文件。
