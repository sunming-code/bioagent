# 本次上传清单

上传目录：团队仓库中的 `agents/popgen/`（内容即本目录 `popgen_agent/`）。

`.gitignore` 会排除 `data/`、`results/`、`work/` 和 `.nextflow`。下面「要额外加入」的文件必须 `git add -f`，否则会被忽略。不在本清单里的大文件见 `LOCAL_DATA.md`。

`envs/*.yml` 末尾的 `prefix: /home/wangy/miniconda3/...` 是本机路径，提交前删掉这三行。

## 代码与契约

| 路径 | 上传原因 |
|---|---|
| `orchestrator.py` | 平台调用入口。按顺序跑预处理、群体分析、GNN，并汇总证据包 |
| `pack.py` | 把步骤 2/3 的 JSON 收成 e-Gene 交付包，并做 schema 校验 |
| `contracts/evidence_pack.schema.json` | 与 e-Gene 对齐的交付字段。平台和下游用同一份文件互检 |
| `contracts/partial_evidence.schema.json` | 步骤 2 中间结果的字段约束。`pack.py` 之前的分析输出靠它保持稳定 |
| `steps/01_preprocess/main.nf` | FASTQ 到 VCF 的 Nextflow 流程 |
| `steps/01_preprocess/nextflow.config` | 该流程的 Nextflow 配置 |
| `steps/02_analysis/popgen_agent.py` | 祖先比例、PCA、ADMIXTURE 和匹配人群频率 |
| `steps/03_gnn/gnn_core.py` | GNN 的特征、图、模型和冻结推理实现 |
| `steps/03_gnn/decide.py` | 病人 VCF 的 GNN 推理入口 |
| `steps/03_gnn/train.py` | 训练与交叉验证。换底库或重训时要靠它再生 `model.pt` |
| `steps/03_gnn/model.pt` | 已训练权重、训练位点、PCA 参数和温度。没有它就不能做冻结推理 |
| `ui/app.py` | 只读结果看板的 API |
| `ui/static/index.html` | 看板页面 |
| `scripts/run_preprocess.sh` | 启动步骤 1 的命令 |
| `scripts/run_gnn_train.sh` | 启动 GNN 训练的命令 |
| `scripts/run_ui.sh` | 启动看板 |
| `scripts/build_1000g_panel.sh` | 从公共 1000G VCF 生成 plink 底库。底库本身不入库，脚本必须在 |
| `scripts/fetch_data.sh` | 说明并拉取参考基因组等本地输入 |
| `scripts/leave_one_out.sh` | 四个大陆个体的步骤 2 留一自测 |
| `scripts/fill_refhom.py` | 用 BAM 补参考纯合位点的试验脚本。当前交付频率表不含这些位点，脚本保留以便复核 |
| `envs/preprocess.yml` | 步骤 1 的 conda 环境（`popgen`） |
| `envs/analysis.yml` | 步骤 2 的 conda 环境（`popgen_analysis`） |
| `envs/gnn.yml` | 步骤 3 的 conda 环境（`popgen_gnn`） |
| `.gitignore` | 防止 FASTQ、BAM、VCF 和 Nextflow 缓存被提交 |
| `data/.gitkeep` | 保留空的 `data/`，让别人知道输入该放这里 |
| `data/fastq/.gitkeep` | 保留 FASTQ 目录 |
| `data/reference/.gitkeep` | 保留参考基因组与底库目录 |
| `data/truth/.gitkeep` | 保留 GIAB 金标准目录 |
| `results/.gitkeep` | 保留结果目录 |

## 说明文档

| 路径 | 上传原因 |
|---|---|
| `README.md` | 模块是什么、怎么跑、和 e-Gene 的关系 |
| `OPERATION.md` | 已完成的步骤和后续平台接入计划 |
| `LOCAL_DATA.md` | 不上传的数据：绝对路径、内容、在流水线中的作用 |
| `UPLOAD.md` | 本清单。提交时逐项核对 |

## 要额外加入的小结果

这些文件被 `results/*` 忽略，但体积小，是合并平台时对接口和核对结论用的。`results/evidence_pack.json` 与交付目录里的是同一份文件，只提交交付目录那份。

| 路径 | 上传原因 |
|---|---|
| `results/delivery/evidence_pack.json` | HG002 的正式交付样例。e-Gene 按这些字段接 popgen |
| `results/delivery/INTERFACE.md` | 同一次交付的读法：查表人群、BA1 开关、GNN 不得改查表人群 |
| `results/partial_evidence.json` | 步骤 2 的原始结论。证据包里的 `analysis_based` 从这里来 |
| `results/gnn_decision.json` | 冻结推理的 HG002 结果：AMR、置信度 0.382、`usable_for_lookup=false` |
| `results/gnn/cv_metrics.json` | 五折交叉验证相对 PCA / ADMIXTURE 的准确率和 ECE |
| `results/gnn/cv_slices.tsv` | 上述指标按大陆、混血、AMR 等切片的表 |
| `results/gnn/cv_predictions.tsv` | 3202 人逐个体的交叉验证预测，用来核对 `cv_metrics.json` |
| `results/gnn/inductive_loo.tsv` | 四个大陆个体走冻结推理后与标签一致 |
| `results/loo/summary.tsv` | 同四个个体的步骤 2 留一是否通过 |
| `results/concordance/summary.md` | HG002 调用相对 GIAB 金标准的精确率。比对中间文件不上传 |
| `results/ancestry_pca.tsv` | 看板画 PCA 散点。约 394KB |
| `results/admixture_results_K5.tsv` | HG002 的监督 K=5 祖先比例 |
| `results/admixture_cv.tsv` | 无监督 ADMIXTURE 的交叉验证误差 |
| `results/admixture_unsupervised_K9.tsv` | 无监督最佳 K=9 时病人的成分。只描述底库细结构，不是查表人群 |

## 不要和本次代码一起提交

Nextflow 缓存和日志：`steps/01_preprocess/.nextflow/`、`steps/01_preprocess/.nextflow.log*`。

Python 缓存：所有 `__pycache__/`。

大文件和旧目录：见 `LOCAL_DATA.md`。其中包括 FASTQ、GRCh38、1000G 底库、`work/`、`patient.vcf`、`allele_freq.tsv`、`results/loo/` 里除 `summary.tsv` 以外的内容、`results/concordance/` 里除 `summary.md` 以外的内容、`prototype/`。
