# 数据来源记录

完整获取和上传说明见 [DATASETS.md](../DATASETS.md)。

- `provenance.json`：从本地数据目录保存的小型来源快照、URL、版本、历史校验值、本次重算的面板/模型/图谱 SHA-256、HTTP 访问检查和已确认的复现缺口。
- `local_inventory.tsv`：2026-10-19 审计时三个数据目录的 732 个文件，包含大小及可用校验值。未提供哈希的文件标为 `not_rehashed`。
- `popgen_panel/`：当前剪枝面板的标签、`.fam` 个体顺序和 `.pop` 超群标签；没有包含基因型 `.bed`。
- `git_upload_preview.json`、`git_upload_files.tsv`：按当前忽略规则模拟 Git 收录的结果和文件清单。文件总量与目录磁盘占用采用不同口径。

这些记录不包含原始大数据，不是可直接消费的运行期数据库清单。`source_records` 中保留的本机路径用于审计，迁移后需按模块安装器重新生成运行配置。本次没有修改上游来源锁，也没有解决 `mim2gene.txt` 历史快照或 GSE159677 加工数据的公共发布问题。
