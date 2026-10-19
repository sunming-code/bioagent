# GDgpt 本机部署

版本：1.1 · 更新日期：2026-10-16

## 启动与访问

```bash
cd /hpc2hdd/home/msun663/e-gene/3_GDgpt
scripts/run_local.sh start
scripts/run_local.sh status
scripts/run_local.sh check
```

页面地址为 `http://127.0.0.1:8501`。服务绑定服务器的回环地址。
在自己电脑上建立 SSH 隧道后，打开自己电脑的同一地址：

```bash
ssh -N -L 8501:127.0.0.1:8501 msun663@服务器SSH地址
```

如果使用 VS Code Remote SSH，也可以在 Ports 面板转发服务器的 8501 端口。
使用能运行上述启动命令的同一个 SSH 主机；当前安装所在主机为 `mgmt-3`。

停止本项目的页面和数据库：

```bash
scripts/run_local.sh stop
```

这些命令不安装系统服务；服务器重启后重新执行 `start`。
`start` 会复用已经导入的图谱，重复执行不会重复导入。

## 安装内容

| 项目 | 本地位置 / 配置 |
| --- | --- |
| Python | `.venv/`，Python 3.11；完整依赖版本见 `requirements.lock.txt` |
| Neo4j | `.runtime/neo4j/`，Community 5.26.12 |
| Java | `.runtime/java` 指向服务器已有 Temurin 21.0.11 |
| 数据 | `.runtime/neo4j/data/`，10,133 节点、87,838 条边 |
| 数据库端口 | `127.0.0.1:7474` / `127.0.0.1:7687` |
| LLM | `kimi-k3`，`https://api.moonshot.cn/v1` |
| 向量模型 | 本地 FastEmbed / `BAAI/bge-small-zh-v1.5`，缓存 `.runtime/models/` |
| 配置 | `config.json`，权限 0600，已被 `.gitignore` 排除 |
| 页面日志 | `.runtime/logs/streamlit.log` |
| 数据库日志 | `.runtime/neo4j/logs/` |

Neo4j 5.26 可使用 Java 21，依据 [Neo4j 官方系统要求](https://neo4j.com/docs/operations-manual/current/installation/requirements/)。
本次无需 Docker 守护进程，未改动服务器系统 Java。

Kimi K3 实测只接受 `temperature=1`，因此生成模型与审核模型均使用 1；其他模型
保留原来的 0.7 / 0.0。K3 的推理参数依据 [Kimi 官方 API 文档](https://platform.kimi.com/docs/api/chat)，
此部署未关闭推理、未缩减系统角色、未修改查询或论文中的历史结果。
本次运行的模型与温度不同于历史实验，运行检查结果不能当成历史实验复现。

API Key 可在页面左侧“系统配置”修改。配置保存会保留本地向量模型设置。
也可用 `GDGPT_API_KEY`、`GDGPT_BASE_URL`、`GDGPT_TEXT_MODEL` 覆盖当前进程配置；
环境变量覆盖优先于配置文件。应用不会自动复用编码助手自己的凭据。

两个经验库初始为空；在有标准答案的评测模式下才保存经验。
本次向量验证使用临时 FAISS 索引，未将测试文本或历史答案灌入实际经验库。
启动脚本默认使用已缓存的向量模型，避免每次启动访问模型下载网站。
需要重新下载模型时可设置 `GDGPT_HF_OFFLINE=0` 后执行检查。

## 并行执行

同轮专家默认最多 7 位同时分析；每位专家内部仍依次规划查询、检索图谱、生成分析。
每份计划中互不依赖的 Neo4j 只读查询最多并发 3 条。分诊和经验检索同时执行；
启用自适应路由时，复杂度判断也与分诊同时执行。
专家全部完成后按原角色顺序汇总，再执行审核，跨轮仍按顺序推进。

`config.json` 支持 `max_parallel_experts`（1–7，默认 7）和
`max_parallel_queries`（1–8，默认 3）。API 请求量保持原策略，并发会提高瞬时请求速率；
遇到账户限流可减小专家并发数，原有 SDK 重试仍保留。
应用与评测统一使用这些设置；无需在页面另外开启。

每位专家拥有独立页面缓冲，后台事件通过队列回到调用线程更新页面。
Neo4j 共用受锁保护的驱动，每条查询独立创建 session；错误状态按线程隔离。
FAISS 经验库的初始化、读取和保存使用同一锁，避免并发读写。
Neo4j 多线程与独立 session 的依据见 [官方并发说明](https://neo4j.com/docs/python-manual/current/concurrency/)。

运行产物增加 `execution_timings`，记录模型请求、专家整体和工作流阶段的起点、耗时和成功状态。
批量工具证据仍按“轮次 → 原角色顺序 → 计划查询顺序”保存。
页面会显示各阶段用时。并行部署检查保存到
`evaluation/results/local_runtime_parallel_smoke.jsonl`，原串行产物保留。

修改模块后可仅重启页面，使其重新加载 Python 模块：

```bash
scripts/run_local.sh restart-web
```

## 验证命令

```bash
# 图谱连接、数据量、单跳、Bridge 查询、页面健康检查
scripts/run_local.sh check

# 使用真实 Kimi API 运行完整工作流，会消耗账户额度
# 此命令使用 max_rounds=1 检查四阶段功能；正式实验仍用 max_rounds=6
scripts/run_local.sh smoke

# 原有回归检查
.venv/bin/python evaluation/scripts/check_placeholder_guard.py
.venv/bin/python evaluation/scripts/check_disease_to_gene_ranking.py
.venv/bin/python evaluation/tests/check_metrics_ext.py \
  --pred evaluation/results/adapt15_guardrank_raw.jsonl \
  --kg-nodes kg_build/task_kg_output/task_kg_nodes.csv
```

原串行检查产物位于 `evaluation/results/local_runtime_smoke.jsonl`；当前检查产物位于 `evaluation/results/local_runtime_parallel_smoke.jsonl`。
该文件为部署检查，未合并进论文评测结果。
该检查运行单轮，验证分诊、图谱预取、多专家分析与审核能生成最终输出。
此前使用六轮上限的宽泛问题在第一轮审核后继续讨论，已人工中断，
未计为验证通过；日志保留于 `.runtime/logs/workflow_six_round_interrupted.log`。
应用默认六轮和正式实验配置均未更改。

并发回归检查（包含实际页面按钮和本机 Neo4j，只读查询）：

```bash
.venv/bin/python evaluation/tests/check_parallel_execution.py
```

## 已完成的验证

- 并发回归检查 12/12 通过，包含线程交叠、并发上限、异常回调恢复、两轮互盲、两轮页面输出、批量证据顺序、共享实例问题隔离、自适应判断并行、向量初始化单次执行及本机 Neo4j 并发查询。

- `pip check` 无依赖冲突；51 个项目 Python 文件语法通过。
- Streamlit 页面可渲染，配置保存后保留本地向量模型设置。
- 图谱数据量与 CSV 一致；11 个查询意图均无执行错误。
- 对本次 `breast carcinoma` 示例，`DiseaseToPathway` 和 `DiseaseToPhenotype`
  返回空结果；前者是已记录的图谱直接边缺失，通路证据由 Bridge 查询提供。
- 原有占位符检查 28 个正例 + 102 个反例通过；指标检查 7/7 通过；
  3 个疾病的实时基因排序检查通过。
- 本地向量模型、FAISS 持久化和中英文语义检索通过。
- 实际 CorrectKB / ChainKB 的保存、重载及联合检索在临时目录中通过。
- Kimi K3 真实单轮四阶段检查通过：4 个专家、4 次专家工具回调、KG 覆盖率 1.0，
  最终输出 6,523 字符，耗时 381.82 秒。此结果证明链路可执行，未评估临床结论正确性。
- 已停止并重新启动 Neo4j 和页面，图谱数据保持完整，重启后的本地健康检查通过。

## 真实并行对照（2026-10-16）

同一个 TP53 问题、Kimi K3、相同四位专家、单轮部署功能检查：

| 指标 | 实测 |
| --- | ---: |
| 原串行总耗时 | 381.82 秒 |
| 并行总耗时 | 327.69 秒 |
| 减少 | 54.13 秒（14.18%） |
| 本次四位专家个体耗时之和 | 142.03 秒 |
| 本次专家并行执行跨度 | 45.64 秒 |
| 四位专家同时在执行的交叠区间 | 28.05 秒 |
| 汇总请求 | 160.89 秒 |
| 审核请求 | 56.29 秒 |

四位专家的启动时间差小于 0.03 秒；实际模型请求 12 次，未减少角色或请求步骤。
未记录到失败的模型请求、专家任务或 KG 查询，KG 覆盖率为 1.0。
这是一组单次端到端观测，输出长度和接口调度存在波动，不能推断所有问题的平均提速。
142.03 秒是本次并行运行中各专家时长之和，未测得上一版本的独立专家阶段耗时。
本次汇总与审核有先后依赖，合计约占当前总耗时的 66%，仍需顺序执行。

原始起止时间见 `local_runtime_parallel_smoke.jsonl` 的 `execution_timings`；
对照摘要保存于 `evaluation/results/parallel_runtime_comparison.json`。

## 变更记录

| 版本 | 日期 | 变更 |
| --- | --- | --- |
| 1.1 | 2026-10-16 | 接入专家、独立图谱查询、分诊/经验检索并行；隔离工具与页面状态；记录模型/专家/阶段耗时并增加并发回归检查。 |
| 1.0 | 2026-10-16 | 安装独立环境和本地图谱；增加启动/停止/检查命令、批量幂等导入、Kimi K3 温度兼容和本地向量检索；修正配置路径并限制配置权限。 |
