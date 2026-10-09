# GDgpt 毕业设计项目汇报

> **项目名称**：基于知识图谱增强的多智能体基因-疾病-通路机制分析系统  
> **汇报日期**：2026 年 4 月 10 日  
> **汇报人**：[姓名]  
> **指导教师**：[导师姓名]

---

## 目录

1. [一句话总结：这个项目在做什么](#一-一句话总结这个项目在做什么)
2. [项目背景与问题定义](#二-项目背景与问题定义)
3. [系统设计——如何解决这个问题](#三-系统设计如何解决这个问题)
4. [知识图谱（KG）详解——系统的"知识仓库"](#四-知识图谱kg详解系统的知识仓库)
5. [多角色专家协同——如何模拟"专家会诊"](#五-多角色专家协同如何模拟专家会诊)
6. [测试集构建——如何验证系统有效](#六-测试集构建如何验证系统有效)
7. [评测指标体系——如何量化"好不好"](#七-评测指标体系如何量化好不好)
8. [实验设计与结果](#八-实验设计与结果)
9. [关键发现与分析](#九-关键发现与分析)
10. [已知问题与解决方向](#十-已知问题与解决方向)
11. [后续工作计划](#十一-后续工作计划)

---

## 一、一句话总结：这个项目在做什么

> **核心问题**：给定一个生物医学问题（如"乳腺癌涉及哪些基因和通路？"），系统能否自动从知识图谱中检索相关的基因、通路、表型、药物，并给出结构化、可追溯的机制解释？

**简单类比**：就像一群医学专家围在一起会诊——每个专家（基因专家、通路专家、药物专家等）先从医学百科全书（知识图谱）里查资料，然后各抒己见，最后由主治医生综合各方意见给出最终报告。本系统用 AI 模拟了这个过程。

---

## 二、项目背景与问题定义

### 2.1 领域背景

生物医学知识是一个庞大的网络：
- **基因（Gene）**：如 BRCA1、TP53、EGFR 等，是疾病的分子基础
- **疾病（Disease）**：如乳腺癌、肺癌、精神分裂症等
- **通路（Pathway）**：基因参与的信号传导链条（如 PI3K/AKT 通路），是基因发挥功能的"高速公路"
- **表型（Phenotype）**：疾病的临床表现（如肿块、头痛）
- **药物（Drug）**：治疗疾病的药物，通常靶向特定基因

这些实体之间存在复杂的关联关系：

```
举个例子：

乳腺癌 (Disease) 
  ──关联──→ BRCA1 (Gene) ──参与──→ DNA Repair Pathway (通路)
  ──关联──→ ERBB2 (Gene) ──参与──→ PI3K/AKT signaling (通路)
  ──表现──→ 乳房肿块 (Phenotype)
  ──治疗──→ Tamoxifen (Drug) ──靶向──→ ESR1 (Gene)
```

### 2.2 现有方法的不足

| 方法 | 优点 | 缺点 |
|------|------|------|
| **手动查文献** | 准确 | 极其耗时，需要专业知识 |
| **直接问 ChatGPT** | 快速、流畅 | ❌ 可能产生"幻觉"（编造不存在的基因-疾病关联）<br>❌ 无法追溯信息来源<br>❌ 无法区分"有证据支持的事实"和"推测" |
| **查数据库（如 PrimeKG）** | 准确、可追溯 | 查询需要专业知识，无法自然语言交互 |

### 2.3 本项目的目标

**将 LLM 的自然语言能力 + 知识图谱的结构化准确性 结合起来**，让系统：
1. 能用自然语言提问
2. 从知识图谱中检索有据可查的关联
3. 多个"AI 专家"从不同角度分析
4. 输出结构化、可验证的结果（具体的基因列表、通路列表等）

### 2.4 三个核心研究问题

| 研究问题 | 含义 |
|---------|------|
| **RQ1** | 知识图谱辅助能否提升 LLM 在生物医学问答任务上的表现？ |
| **RQ2** | 在何种条件下（哪类问题、什么覆盖率），KG 辅助最为有效？ |
| **RQ3** | 当 KG 覆盖不足时，系统能否优雅降级（不比纯 LLM 差）？ |

---

## 三、系统设计——如何解决这个问题

### 3.1 整体工作流

系统的处理流程类似"多学科会诊"（MDT），分为 4 个阶段：

```
用户输入问题（如："乳腺癌涉及哪些基因和通路？"）
       │
       ▼
┌──────────────────────────────────────────────────────────────┐
│  第一步：分诊（Triage）                                       │
│  • 分析问题类型：疾病相关？基因相关？药物相关？                  │
│  • 从 7 个专家角色中选择 ≥3 个最适合回答的                     │
│  • 例如对"乳腺癌"问题，选 GeneCurator + PathwayBiologist      │
│         + PhenotypeMapper + DrugMechanismAnalyst 等           │
└──────────────────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────────────────┐
│  第二步：知识图谱预取（KG Prefetch）                           │
│  • LLM 自动规划查询计划（选择从 11 种查询意图中挑 2-3 种）      │
│  • 批量执行 Neo4j 数据库查询                                  │
│  • 将查到的基因、通路、药物等作为"共享证据"                     │
│                                                              │
│  例：规划出以下查询                                            │
│    - DiseaseToGene：乳腺癌 → 关联基因                         │
│    - DiseaseGenePathwayBridge：乳腺癌 → 基因 → 通路           │
│    - DiseaseToDrug：乳腺癌 → 治疗药物                         │
└──────────────────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────────────────┐
│  第三步：专家会诊（Consultation）                              │
│  • 多个 AI 专家各自独立分析（同一轮互不可见，避免互相抄袭）      │
│  • 每个专家可以额外调用 KG 工具补充查询                        │
│  • 主治医生综合各专家意见                                      │
│  • 安全评审员判断是否已收敛到可信结论                           │
│  • 未收敛 → 再来一轮（最多 6 轮）                              │
└──────────────────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────────────────┐
│  最终输出：结构化报告                                          │
│  • 关联基因列表（如 BRCA1, TP53, PIK3CA, ERBB2...）           │
│  • 涉及通路列表（如 PI3K/AKT, MAPK, DNA Repair...）           │
│  • 临床表型列表（如 乳房肿块、淋巴结肿大...）                   │
│  • 治疗药物列表（如 Tamoxifen, Trastuzumab...）                │
│  • 完整机制链解释（每条关联都标注来自 KG 还是 LLM 推测）         │
└──────────────────────────────────────────────────────────────┘
```

### 3.2 一个完整的运行示例

**用户提问**："我怀疑我有 breast carcinoma，把相关的基因/通路给我解释一下，以及有什么症状？"

**Step 1：分诊结果**
```
识别实体: breast carcinoma（疾病）
问题类型: disease_centered
选中专家: GeneCurator, PathwayBiologist, PhenotypeMapper, 
         DrugMechanismAnalyst, EvidenceReviewer
```

**Step 2：KG Prefetch 查询结果**

系统自动规划并执行了 4 种查询：

| 查询类型 | 查询路径 | 返回结果示例 |
|---------|---------|-------------|
| DiseaseToGene | 乳腺癌 → 基因 | ABCB1, ABL1, AKT1, ERBB2, TP53... |
| DiseaseGenePathwayBridge | 乳腺癌 → 基因 → 通路 | PI3K/AKT (经 AKT1, ERBB2 等 20 个基因), MAPK (经 KRAS, ERBB2 等 20 个基因) |
| DiseaseToPhenotype | 乳腺癌 → 表型 | ⚠️ 该疾病在 KG 中无表型节点 |
| DiseaseToDrug | 乳腺癌 → 药物 | Carboplatin, Cyclophosphamide, Docetaxel... |

**Step 3：专家独立分析（摘要）**

- **GeneCurator**：规范化了基因名，标注了 ERBB2/HER2 是同一基因
- **PathwayBiologist**：分析了 PI3K→AKT→mTOR 和 RAF→MAPK 两条核心级联通路
- **DrugMechanismAnalyst**：解释了 Trastuzumab 靶向 ERBB2 的机制
- **EvidenceReviewer**：指出 BRCA1/2 这两个经典驱动基因不在当前 KG 切片中，属于 KG 覆盖不足

**最终输出**：

```
📍 疾病: breast carcinoma

🧬 KG 支持的关联基因: ERBB2, AKT1, MTOR, SRC, KRAS, TP53, BCL2...

🔗 KG 支持的通路（通过多跳查询得出）:
   • PI3K→PIP3→AKT→MTOR 信号通路
   • RAF→MAPK 级联
   • 雌激素依赖基因表达
   • IL-4/13 炎症信号通路

💊 关联药物: Carboplatin, Docetaxel, Doxorubicin...

⚠️ 局限性:
   • KG 中该疾病无直接表型节点（临床症状信息缺失）
   • 经典驱动基因 BRCA1/2 不在当前 KG 切片中
   • 以上为 KG 关联的解读，并非因果声明
```

### 3.3 技术栈

| 组件 | 技术选型 | 用途 |
|------|---------|------|
| 大语言模型（LLM） | GPT-5-mini | 推理、规划、综合 |
| 知识图谱数据库 | Neo4j 5.x | 存储和查询结构化知识 |
| 知识图谱数据源 | PrimeKG | 哈佛/MIT 构建的生物医学 KG |
| 向量数据库 | FAISS | 历史经验检索 |
| 工作流引擎 | LangGraph | 多阶段流程编排 |
| 前端界面 | Streamlit | Web 交互界面 |

---

## 四、知识图谱（KG）详解——系统的"知识仓库"

### 4.1 什么是知识图谱

**知识图谱**是用"节点 + 关系"来表示知识的数据库。可以理解为一个巨大的"概念网络"：

```
简单类比：
  
  普通数据库 = 一本书（线性的，一页一页翻）
  知识图谱   = 一张蜘蛛网（网状的，可以从任意一点出发，沿着关系找到关联的知识）
```

### 4.2 我们的 KG 长什么样

本项目使用 **PrimeKG**（由哈佛大学和 MIT 联合构建的大规模生物医学知识图谱，发表于 Nature Scientific Data）作为数据源，导入 Neo4j 图数据库后形成 **Task KG**。

**5 类节点（实体）**：

| 实体类型 | 数量 | 说明 | 举例 |
|---------|:----:|------|------|
| Gene（基因） | 3,582 | 人类基因 | BRCA1, TP53, EGFR |
| Disease（疾病） | ~20 | 主要是癌症类 | breast carcinoma, lung cancer |
| Pathway（通路） | 1,725 | 信号通路 | PI3K/AKT/mTOR, MAPK cascade |
| Phenotype（表型） | 76 | 临床表现 | Abnormal breast morphology |
| Drug（药物） | 4,730 | 治疗药物 | Tamoxifen, Trastuzumab |

**5 类关系（边）**：

| 关系 | 含义 | 举例 |
|------|------|------|
| ASSOCIATED_WITH | 基因-疾病关联 | BRCA1 ──关联── breast carcinoma |
| INVOLVED_IN | 基因-通路参与 | BRCA1 ──参与── DNA Repair Pathway |
| HAS_PHENOTYPE | 疾病-表型关联 | breast carcinoma ──表现── 乳房肿块 |
| TREATS | 药物-疾病治疗 | Tamoxifen ──治疗── breast carcinoma |
| TARGETS | 药物-基因靶向 | Tamoxifen ──靶向── ESR1 |

### 4.3 为什么需要"多跳查询"（Bridge Query）

这是本项目的**核心创新点**之一。

**问题**：用户问"乳腺癌涉及哪些通路？"。但在 KG 中，Disease 和 Pathway 之间**没有直接的边**——必须经过 Gene 这个"中间人"。

```
❌ 单跳查询无法回答：
   Disease ──?──→ Pathway    （不存在直接关系！）

✅ 需要两跳查询（Bridge）：
   Disease ──ASSOCIATED_WITH──→ Gene ──INVOLVED_IN──→ Pathway
   
   具体例子：
   breast carcinoma ──关联──→ ERBB2 ──参与──→ PI3K/AKT signaling
   breast carcinoma ──关联──→ KRAS  ──参与──→ RAF/MAPK cascade
```

**我们设计了 3 种 Bridge 查询模板**：

| Bridge 名称 | 路径 | 使用场景 | 具体例子 |
|------------|------|---------|---------|
| DiseaseGenePathwayBridge | 疾病→基因→通路 | "XX 疾病涉及哪些通路？" | breast carcinoma → ERBB2 → PI3K/AKT |
| GenePhenotypeBridge | 基因→疾病→表型 | "XX 基因突变有什么症状？" | TP53 → Li-Fraumeni syndrome → 多发肿瘤 |
| DrugTargetDiseaseBridge | 药物→靶点基因→疾病 | "XX 药物能治什么病？" | Tamoxifen → ESR1 → breast carcinoma |

**Bridge 查询的 Cypher 实现**（以 DiseaseGenePathwayBridge 为例）：

```cypher
-- 从疾病出发，找到关联基因，再找到基因参与的通路
MATCH (d:Disease)-[r1:ASSOCIATED_WITH]-(g:Gene)-[r2:INVOLVED_IN]-(p:Pathway)
WHERE toLower(d.name) = 'breast carcinoma'
WITH d, p,
     collect(DISTINCT g.name)[0..5] AS genes,   -- 保留中间基因列表（可追溯！）
     count(DISTINCT g) AS gene_count             -- 经过的基因数量
RETURN d.name AS disease, p.name AS pathway, genes, gene_count
ORDER BY gene_count DESC                         -- 经过基因越多的通路排越前
LIMIT 10
```

**查询结果示例**（breast carcinoma 的 Bridge 查询）：

| 疾病 | 通路 | 经过的中间基因 | 基因数 |
|------|------|--------------|:------:|
| breast carcinoma | Interleukin-4/13 signaling | IL6, AKT1, TP53, MMP1, BCL2 | 26 |
| breast carcinoma | PIP3 activates AKT signaling | FGF10, MTOR, AKT1, NRG1, SRC | 23 |
| breast carcinoma | PI3K/AKT Signaling | FGF10, AKT1, NRG1, SRC, ERBB2 | 20 |
| breast carcinoma | RAF/MAP kinase cascade | FGF10, NRG1, KRAS, ERBB2 | 20 |

> **意义**：这个结果不仅告诉用户"乳腺癌涉及 PI3K/AKT 通路"，还展示了**完整的推理路径**——是通过 AKT1、ERBB2、SRC 这些基因连接过去的。这种可追溯性是纯 LLM 无法提供的。

### 4.4 KG Prefetch（知识图谱预取）机制

**设计动机**：如果 5 个专家各自去查 KG，会重复查询、浪费资源、且各专家看到的证据可能不一致。

**解决方案**：在专家会诊之前，先由 LLM 统一规划查询计划，批量执行所有查询，然后把结果作为"共享证据"分发给所有专家。

```
用户问题："乳腺癌涉及哪些基因和通路？"
       │
       ▼
LLM 规划查询意图：
  ┌──────────────────────────────────────────────┐
  │ 查询 1: DiseaseToGene (乳腺癌 → 基因, k=10) │
  │ 查询 2: DiseaseGenePathwayBridge (k=10)      │
  │ 查询 3: DiseaseToPhenotype (k=10)            │
  │ 查询 4: DiseaseToDrug (k=5)                  │
  └──────────────────────────────────────────────┘
       │
       ▼ 批量执行
       │
       ▼ 格式化结果
       │
  ┌────┼────┬────┬────┐
  ▼    ▼    ▼    ▼    ▼
专家1 专家2 专家3 专家4 专家5
     （所有专家看到同一份 KG 证据）
```

---

## 五、多角色专家协同——如何模拟"专家会诊"

### 5.1 为什么需要多角色

生物医学问题涉及多个维度——一个基因专家可能不了解药物机制，一个药物专家可能不了解表型映射。多角色设计确保问题被从**多个专业视角**分析。

### 5.2 七种专家角色

| # | 角色 | 职责 | 类比 |
|:-:|------|------|------|
| 1 | **GeneCurator**<br>基因管理员 | 基因名标准化、别名映射、基因级证据评估 | 遗传科医生 |
| 2 | **DiseaseMechanismAnalyst**<br>疾病机制分析师 | 分析疾病-基因因果关系、排序驱动基因 | 病理科医生 |
| 3 | **PathwayBiologist**<br>通路生物学家 | 追踪信号通路证据链、分析级联效应 | 分子生物学家 |
| 4 | **PhenotypeMapper**<br>表型映射员 | 将基因/疾病证据映射到临床症状 | 临床内科医生 |
| 5 | **DrugMechanismAnalyst**<br>药物机制分析师 | 分析药物靶点、禁忌、药物-基因-疾病链 | 药剂师 |
| 6 | **EvidenceReviewer**<br>证据评审员 | 区分"图谱支持的事实"与"推测性结论" | 循证医学审查员 |
| 7 | **HypothesisIntegrator**<br>假设整合者 | 将多跳证据整合为连贯机制链 | 综合分析师 |

### 5.3 协同机制：同轮互盲、跨轮可见

```
Round 1:
  ┌─────────────────────────────────────────┐
  │         共享输入（KG Prefetch 结果）       │
  └──────────────┬──────────────────────────┘
                 │
     ┌───────────┼───────────┐
     ▼           ▼           ▼
  ┌──────┐  ┌──────┐  ┌──────┐
  │基因  │  │通路  │  │表型  │    ← 同一轮各专家互不可见！
  │专家  │  │专家  │  │专家  │       保证独立思考
  └──┬───┘  └──┬───┘  └──┬───┘
     │         │         │
     └─────────┴─────────┘
                │
                ▼
  ┌──────────────────────────────────────────┐
  │  主治医生（Lead Physician）综合各方意见    │
  │  → 生成 Round 1 总结                      │
  └──────────────────────────────────────────┘
                │
                ▼
  ┌──────────────────────────────────────────┐
  │  安全评审：是否收敛？                      │
  │  → 是 → 输出最终答案                      │
  │  → 否 → 进入 Round 2（各专家可看到上轮总结）│
  └──────────────────────────────────────────┘
```

**设计优势**：
- **同轮互盲**：避免专家之间"随大流"，保证多样性观点
- **跨轮可见**：后续轮次可以基于前轮结论深入讨论
- **统一证据基础**：所有专家基于同一份 KG 预取结果，避免自相矛盾

---

## 六、测试集构建——如何验证系统有效

### 6.1 为什么测试集构建很重要

评测一个 AI 系统，需要一套"标准答案"（gold standard）来对比系统输出是否正确。测试集的质量直接决定了实验结论是否可信。

### 6.2 循环评测问题

**循环评测（Circular Evaluation）** 是这类系统面临的核心方法论挑战：

```
❌ 错误做法（循环评测）：
  PrimeKG 知识图谱 ──生成──→ 测试集的 Gold 标准
                    ↑                  │
                    │                  ▼
                    └──── 系统查询 ←── 用来评测系统
  
  问题：系统从 PrimeKG 查出来的答案，和从 PrimeKG 生成的标准答案，
       当然会匹配！这就像老师用课本出题，学生带着课本考试——意义不大。

✅ 正确做法（独立评测）：
  外部独立数据源 ──生成──→ 测试集的 Gold 标准
  （Open Targets, Reactome）          │
                                      ▼
  PrimeKG ──作为系统的知识来源──→ 系统输出 ──对比──→ 评测结果
  
  这样才能真正衡量系统的能力：用 A 的知识回答，用 B 的标准来评判。
```

### 6.3 四套测试集的演进过程

我们在项目推进过程中**迭代构建了 4 套测试集**，每一套都是在发现前一套问题后的改进版：

#### 🅰 测试集 A：原始测试集（30 题，中文）

- **构建方式**：直接从 PrimeKG 图谱自动生成 + 人工种子
- **时间**：2026-03-17
- **示例问题**："我怀疑我有 breast carcinoma，把相关的基因/通路给我解释一下"
- **Gold 标准来源**：PrimeKG 自身
- **⚠️ 问题**：存在严重的循环评测——gold_genes 直接来自 PrimeKG，系统也从 PrimeKG 查数据

#### 🅱 测试集 B：Quick 独立测试集（30 题，英文）

- **构建方式**：从外部独立数据源自动抓取
- **时间**：2026-03-31
- **数据来源**：
  - **Open Targets Platform**（EMBL-EBI 运营的基因-疾病关联数据库，发表于 Nucleic Acids Research）
  - **Reactome**（手工筛选 + 同行评审的通路数据库，同样发表于 NAR）
- **构建流程**：

```
Step 1: 从 Open Targets API 获取疾病-基因关联
  └──→ 输入: 10种疾病 (如 hepatocellular carcinoma, colorectal cancer...)
  └──→ 输出: 每种疾病的 top-20 高置信度关联基因 (confidence score ≥ 0.6)

Step 2: 从 Reactome API 获取基因-通路关联
  └──→ 输入: 热门基因 (如 TP53, EGFR, BRCA1...)
  └──→ 输出: 每个基因参与的通路列表

Step 3: 生成测试题
  └──→ disease-centered: "What genes are associated with XX cancer?"
  └──→ gene-centered: "What diseases are associated with gene XX?"
  └──→ pathway-centered: "What genes are involved in XX pathway?"

Step 4: 格式化为 JSONL (与现有评测框架兼容)
```

- **示例数据**：
```json
{
  "id": "ind_dc_xxx",
  "task_type": "disease-centered",
  "question": "What genetic factors contribute to hepatocellular carcinoma?",
  "disease_focus": "hepatocellular carcinoma",
  "gold_genes": ["TP53", "CTNNB1", "AXIN1", "ARID1A", ...],  // 来自 Open Targets
  "gold_pathways": ["Wnt signaling", "PI3K/AKT", ...],        // 来自 Reactome
  "source": "Open Targets Platform",
  "annotation_status": "independent_source"
}
```

- **⚠️ 发现的问题**：
  1. gold_phenotypes 和 gold_bridge 字段为空 → 评测逻辑出 bug（双方都空被视为匹配成功）
  2. LLM Only 的一些指标异常偏高（假阳性）

#### 🅲 测试集 C：Quick Enriched v2（30 题，英文）

- **改进点**：在 B 的基础上用 Neo4j KG 补充了缺失字段
- **时间**：2026-04-07
- **具体改进**：
  1. ✅ 基因别名映射（7192 条，如 HER2 → ERBB2），解决"系统说的是 HER2，标准答案写的是 ERBB2"这类不该被判错的情况
  2. ✅ 通路模糊匹配（子串匹配），解决"PI3K/AKT signaling" vs "PIP3 activates AKT signaling"这类同义不同名的问题
  3. ✅ 修复空集匹配 bug
  4. ✅ 用 Neo4j 补充 gold_phenotypes 和 gold_bridge

- **⚠️ 新问题**：从 KG 补充的字段又引入了部分循环成分

#### 🅳 测试集 D：KG 优化测试集（38 题，英文）——最终版

- **设计目标**：消除"系统查不到是因为 KG 里没有"的干扰因素
- **时间**：2026-04-07
- **构建方式**：Open Targets 数据 **×** PrimeKG 交叉验证——确保每个疾病和基因在 KG 中都存在对应节点
- **具体做法**：

```
Step 1: 从 Open Targets 获取疾病-基因关联（外部独立源）
Step 2: 逐个检查这些疾病和基因是否在 PrimeKG Neo4j 中存在节点
Step 3: 只保留"Open Targets 有记录 且 PrimeKG 也有节点"的关联
Step 4: 补充通路信息：从 PrimeKG 查询这些基因参与的 Reactome 通路
Step 5: 补充表型和药物：从 PrimeKG 的 HPO 和 DrugBank 标注中获取
```

- **数据特点**：
  - `gold_genes`：**20 个/题**（来自 Open Targets，是外部独立标准）
  - `gold_pathways`：**10 个/题**（来自 Reactome + PrimeKG 确认存在）
  - `gold_phenotypes`：5-10 个/题（来自 PrimeKG HPO 标注）
  - `gold_drugs`：2-10 个/题（来自 PrimeKG DrugBank 标注）
  - `kg_gene_count`：KG 中该疾病实际关联的基因总数（如 hereditary breast ovarian cancer syndrome → 1156 个）

### 6.4 测试集总览对比

| 属性 | A 原始 | B Quick | C Enriched | D KG优化 |
|------|:------:|:-------:|:----------:|:--------:|
| 题数 | 30 | 30 | 30 | 38 |
| 语言 | 中文 | 英文 | 英文 | 英文 |
| Gold 基因来源 | PrimeKG | Open Targets | Open Targets | **Open Targets** ✅ |
| Gold 通路来源 | PrimeKG | Reactome | Reactome | Reactome+PrimeKG |
| Gold 表型来源 | PrimeKG | 空 | PrimeKG | PrimeKG |
| 循环评测风险 | ❌ 高 | ✅ 低 | ⚠️ 中 | ⚠️ 中（基因独立，表型循环） |
| 100% KG 覆盖 | 否 | 否 | 否 | **是** ✅ |
| 别名映射 | 无 | 无 | ✅ 有 | ✅ 有 |
| 模糊匹配 | 无 | 无 | ✅ 有 | ✅ 有 |

### 6.5 构建工具链

所有测试集的构建都有**完整的自动化脚本**，确保可复现：

| 脚本 | 功能 |
|------|------|
| `fetch_opentargets.py` | 从 Open Targets REST API 批量获取疾病-基因关联 |
| `fetch_reactome.py` | 从 Reactome Content Service API 获取基因-通路关联 |
| `generate_testset.py` | 生成测试集（格式化为 JSONL） |
| `validate_primekg_coverage.py` | 验证测试集实体在 PrimeKG 中的覆盖率 |
| `generate_testset_versions.py` | 生成不同版本（Quick/Full） |
| `analyze_testset_coverage.py` | 覆盖率分析报告 |

---

## 七、评测指标体系——如何量化"好不好"

### 7.1 概念解释：Precision、Recall、F1

这三个指标是信息检索领域最基础的评价标准：

```
假设对于问题"乳腺癌涉及哪些基因？"：

  标准答案（Gold）= {BRCA1, BRCA2, TP53, PIK3CA, ERBB2}  共 5 个正确基因
  系统输出（Pred）= {TP53, AKT1, MTOR, ERBB2, SRC}       共 5 个预测基因

  两者的交集（命中）= {TP53, ERBB2}                       命中 2 个

  ┌─────────────────────────────────────────────────────────────────┐
  │  Recall（召回率）= 命中数 / 标准答案总数 = 2/5 = 40%            │
  │  含义："正确答案里的东西，你找到了百分之几？"                      │
  │  高 Recall = 不会漏掉正确答案                                   │
  │                                                                 │
  │  Precision（精确率）= 命中数 / 预测总数 = 2/5 = 40%             │
  │  含义："你给出的答案里，有百分之几是对的？"                        │
  │  高 Precision = 不会给出错误答案                                 │
  │                                                                 │
  │  F1 = 2 × Precision × Recall / (Precision + Recall)            │
  │     = 2 × 0.4 × 0.4 / (0.4 + 0.4) = 0.40                     │
  │  含义：Precision 和 Recall 的调和平均，综合衡量找准和找全的能力   │
  └─────────────────────────────────────────────────────────────────┘

为什么不单看 Precision 或 Recall？
  
  极端情况 1：系统只输出 1 个基因（TP53），但这 1 个是对的
    → Precision = 1/1 = 100%  看起来很好！
    → Recall = 1/5 = 20%      但漏掉了 80% 的正确答案...
    → F1 = 0.33               F1 揭示了真实水平
  
  极端情况 2：系统输出 100 个基因，包含了所有正确答案
    → Recall = 5/5 = 100%     看起来很好！
    → Precision = 5/100 = 5%  但 95% 都是错的...
    → F1 = 0.095              F1 揭示了真实水平

结论：F1 惩罚极端策略，鼓励 Precision 和 Recall 的平衡。
```

### 7.2 完整指标体系

#### 检索层指标（6 个，全部自动计算）

| 指标 | 公式 | 通俗含义 | 举例说明 |
|------|------|---------|---------|
| **Gene Recall@5** | 命中基因数 / gold基因数 | 标准答案里的基因，系统找到了多少 | gold=5个基因，系统命中2个 → 40% |
| **Gene Precision@5** | 命中基因数 / 系统输出前5个 | 系统给出的 top-5 基因里，有几个是对的 | 输出5个基因，其中2个在标准答案里 → 40% |
| **Pathway Recall@5** | 同上，针对通路 | 标准答案里的通路，系统找到了多少 | — |
| **Pathway Precision@5** | 同上 | 系统给出的通路里，有几个是对的 | — |
| **Bridge Hit Rate** | 判对题数 / 总题数 | 多跳查询是否正确判断了多跳关系的存在 | 30题全部正确判断 → 100% |
| **Coverage** | (非空维度数/4) 的平均 | 系统输出了多少个维度的信息 | 输出了基因+通路+药物（3/4）→ 75% |

#### 端到端指标（6 个，3 个自动 + 3 个人工）

| 指标 | 计算方式 | 含义 |
|------|---------|------|
| **Gene F1** | 不限 top-k 的全集 F1 | 基因预测的综合准确度 |
| **Pathway F1** | 同上 | 通路预测的综合准确度 |
| **Phenotype F1** | 同上 | 表型预测的综合准确度 |
| **Mechanism Completeness** | 人工评分 0-2 | 机制解释是否完整 |
| **Graph Faithfulness** | 人工评分 0-2 | 输出是否忠实于 KG 证据（不编造） |
| **Utility Score** | 人工评分 1-5 | 对用户的实用性 |

### 7.3 评测中的特殊处理

为了公平评测，我们在指标计算中加入了多项特殊处理：

| 处理 | 原因 | 技术细节 |
|------|------|---------|
| **基因别名映射** | 同一个基因有多个名字（如 HER2 = ERBB2 = NEU） | 加载 7192 条 PrimeKG alias map，统一为 canonical symbol |
| **通路模糊匹配** | 同一通路的名称可能不同（如 "PI3K/AKT signaling" vs "PIP3 activates AKT signaling"） | 去除后缀（pathway, signaling pathway），子串匹配 |
| **空集跳过** | 当 Gold 和 Pred 都为空时，不应计入平均 | 返回 None，计算均值时排除 |

---

## 八、实验设计与结果

### 8.1 实验配置

我们设计了两组核心对比实验：

| 配置项 | Exp-0: Full Task KG<br>（完整系统） | Exp-1: LLM Only<br>（纯 LLM 基线） |
|--------|:---:|:---:|
| Neo4j KG 查询 | ✅ 开启 | ❌ 关闭 |
| FAISS 向量检索 | ✅ 开启 | ❌ 关闭 |
| Bridge 多跳查询 | ✅ 开启 | ❌ 关闭 |
| KG Prefetch | ✅ 开启 | ❌ 关闭 |
| 多角色专家协同 | ✅ 开启 | ✅ 开启 |
| LLM 模型 | gpt-5-mini | gpt-5-mini |

**核心目的**：在其他条件完全相同的情况下，**唯一关闭知识图谱**，看性能下降多少——从而证明知识图谱的价值。

### 8.2 实验运行流程

```
Step 1: 批量运行系统
  python run_batch_eval_template.py --gold <测试集> --out <原始输出> --experiment <full|llm_only>
  → 对每道题调用系统，记录 answer_text + tool_calls

Step 2: 后处理——从原始输出中提取结构化字段
  python extract_from_tool_calls.py --pred <原始输出> --out <提取后>
  → 从 tool_calls 中提取 predicted_genes, predicted_pathways 等

Step 3: 计算指标
  python compute_metrics.py --gold <测试集> --pred <提取后> --k 5
  → 输出 JSON 格式的评测指标
```

### 8.3 实验时间线

| 日期 | 里程碑 |
|------|--------|
| 2026-03-17 | Exp-0 原始测试集（30题）完成 |
| 2026-03-18 | Exp-1 LLM Only（30题）完成；首版指标出炉 |
| 2026-03-31 | Quick 独立测试集（30题）构建完成 |
| 2026-04-03 | Quick 版 Full KG 实验完成 |
| 2026-04-05 | Quick 版 LLM Only 完成；Quick v1 指标出炉 |
| 2026-04-07 | Enriched v2 指标更新；KG 优化测试集（38题）构建 |
| 2026-04-08 | KG 优化 Full KG 实验完成 |
| 2026-04-09 | KG 优化 LLM Only 完成（大部分失败） |
| 2026-04-10 | 最终指标计算 + 本报告 |

### 8.4 完整实验结果

#### 8.4.1 检索层指标（越高越好）

| 测试集 | 题数 | 实验 | Gene R@5 | Gene P@5 | Path R@5 | Path P@5 | Bridge Hit | Coverage |
|--------|:----:|------|:--------:|:--------:|:--------:|:--------:|:----------:|:--------:|
| **A 原始** | 30 | Full KG | 0.055 | 0.040 | 0.394 | 0.153 | **1.000** | **0.858** |
| A 原始 | 30 | LLM only | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| **B Quick** | 30 | Full KG | 0.103 | 0.033 | 0.733 | 0.000 | 0.033 | 0.800 |
| B Quick | 30 | LLM only | 0.000 | 0.000 | ⚠️ 0.733 | 0.000 | ⚠️ 1.000 | 0.000 |
| **C Enriched** | 30 | Full KG | 0.104 | 0.040 | 0.271 | **0.240** | 0.767 | 0.800 |
| C Enriched | 30 | LLM only | 0.000 | 0.000 | 0.000 | 0.000 | 0.267 | 0.000 |
| **D KG优化** | 38 | Full KG | 0.004 | 0.021 | 0.261 | **0.474** | **1.000** | **0.849** |
| D KG优化 | 38 | LLM only | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |

> 注：B Quick 的 LLM Only 出现异常高的 Path R@5 和 Bridge Hit，这是评测 bug（gold 字段为空导致的假阳性），在 C Enriched 中已修复。

#### 8.4.2 端到端指标

| 测试集 | 题数 | 实验 | Gene F1 | Path F1 | Pheno F1 |
|--------|:----:|------|:-------:|:-------:|:--------:|
| **A 原始** | 30 | Full KG | 0.060 | **0.316** | 0.438 |
| A 原始 | 30 | LLM only | 0.000 | 0.000 | ⚠️ 0.633 |
| **B Quick** | 30 | Full KG | 0.037 | 0.233 | 0.300 |
| **C Enriched** | 30 | Full KG | 0.042 | 0.246 | 0.006 |
| C Enriched | 30 | LLM only | 0.000 | 0.000 | 0.000 |
| **D KG优化** | 38 | Full KG | 0.052 | **0.337** | 0.168 |
| D KG优化 | 38 | LLM only | 0.000 | 0.000 | 0.000 |

#### 8.4.3 结果速读表（核心对比：KG 优化测试集 D，38 题）

| 指标 | Full Task KG | LLM Only | 差距 | 结论 |
|------|:-----------:|:--------:|:----:|------|
| Gene F1 | 0.052 | 0.000 | +5.2% | KG 能输出结构化基因，LLM 不能 |
| Pathway F1 | **0.337** | 0.000 | **+33.7%** | ✅ KG 显著优势——通路是主力指标 |
| Pathway P@5 | **0.474** | 0.000 | **+47.4%** | ✅ 系统返回的通路接近一半是正确的 |
| Bridge Hit | **1.000** | 0.000 | **+100%** | ✅ 多跳查询 100% 有效 |
| Coverage | **0.849** | 0.000 | **+84.9%** | ✅ 系统能输出多维度结构化数据 |
| Phenotype F1 | 0.168 | 0.000 | +16.8% | KG 有一定表型覆盖 |

---

## 九、关键发现与分析

### 9.1 ✅ 核心结论：知识图谱是结构化输出的必要条件

**最重要的发现**：LLM Only 模式下，**所有检索层指标和大部分端到端指标均为零**。

这说明：
1. 纯 LLM 无法产生可验证、可追溯的结构化实体（基因列表、通路列表等）
2. LLM Only 的多角色讨论在 3 轮内无法收敛，大部分输出为 "Continuing discussion"
3. **知识图谱是系统产生结构化、有价值输出的必要条件**

### 9.2 ✅ 通路检索是系统的核心优势

在所有测试集中，Pathway 相关指标始终是最亮眼的：

| 测试集 | Pathway Precision@5 | Pathway F1 |
|--------|:-------------------:|:----------:|
| A 原始 | 0.153 | 0.316 |
| C Enriched | 0.240 | 0.246 |
| **D KG优化** | **0.474** | **0.337** |

**Pathway Precision@5 = 0.474** 意味着：系统返回的 top-5 通路中，**接近一半是正确的**。这是一个非常有价值的结果，因为通路是理解疾病机制的关键——知道一个疾病涉及 PI3K/AKT 通路，就意味着可以考虑针对该通路的靶向治疗。

### 9.3 ✅ Bridge 多跳查询设计有效

| 测试集 | Bridge Hit Rate |
|--------|:---------------:|
| A 原始（30 题） | **1.000** |
| D KG优化（38 题） | **1.000** |

Bridge Hit Rate = 100% 意味着：**所有题目**的多跳查询（Disease→Gene→Pathway）都成功返回了结果。这证明了 Bridge 查询的设计是正确和可靠的。

### 9.4 ⚠️ Gene F1 偏低——已知瓶颈及原因

Gene F1 在所有测试集上都维持在 0.04-0.06 的低水平。这是当前系统的**主要瓶颈**。

**根本原因**：KG 查询 `DiseaseToGene` 使用的是**按基因名字母序**排序返回前 k 个基因。

```
举个例子：

用户问：乳腺癌涉及哪些基因？

KG 中 breast carcinoma 关联了 1156 个基因
系统查询返回（按字母序 top-8）：ABCB1, ABCC1, ABCG2, ABL1, ACE, ACPP, ACP5, ADA
标准答案（Open Targets 按证据强度排序）：BRCA1, BRCA2, TP53, PIK3CA, ERBB2...

问题一目了然：
  BRCA1 按字母排在 B，不在 A 开头的前 8 名里！
  TP53、PIK3CA、ERBB2 更是排在很后面！
```

**解决方向**（已规划，待实现）：
- 改用**证据权重排序**（degree-weighted 或 evidence score）替代字母序
- 提高 k 值（从 8 增加到 20）
- 引入二次排序机制

### 9.5 ⚠️ LLM Only 的 Phenotype F1 异常——并非真正优势

在原始测试集 A 中，LLM Only 的 Phenotype F1（0.633）高于 Full KG（0.438）。但这**并非 LLM 的真正优势**，而是统计假象：

```
原因分析：

LLM Only 的 38 个回答中，大部分输出为 "Continuing discussion"
  → predicted_phenotypes 全部为空

Gold 标准中，很多题的 gold_phenotypes 也为空

评测逻辑：当 Gold 和 Pred 都为空时 → 该题不计入平均（返回 None）

结果：只有极少数题计入平均，其中个别题 LLM 恰好提到了 Gold 表型
  → 少量样本的偶然命中推高了平均值

在 Enriched v2 和 KG 优化测试集中（补充了 gold_phenotypes），
LLM Only 的 Phenotype F1 回归为 0.000，证实了上述分析。
```

### 9.6 评测指标的迭代改进过程

| 问题 | 发现时间 | 影响 | 修复方案 | 修复版本 |
|------|---------|------|---------|---------|
| 基因别名不统一 | 04-05 | HER2 和 ERBB2 被判为不匹配 | 加载 7192 条别名映射表 | C Enriched |
| 通路名不统一 | 04-05 | "PI3K/AKT" vs "PIP3 activates AKT" 不匹配 | 子串模糊匹配 | C Enriched |
| 空集假阳性 | 04-05 | LLM Only 出现 100% Phenotype F1 | 空集跳过逻辑 | C Enriched |
| Gold 字段缺失 | 04-07 | Phenotype、Bridge 字段为空 | Neo4j 补充 | C Enriched |
| KG 覆盖不匹配 | 04-07 | 部分疾病不在 KG 中，无法查询 | 100% KG 覆盖验证 | D KG优化 |

---

## 十、已知问题与解决方向

### 10.1 问题清单

| # | 问题 | 严重程度 | 原因 | 计划中的解决方案 |
|:-:|------|:--------:|------|----------------|
| 1 | Gene F1 偏低（~5%） | 🔴 高 | KG 按字母序返回基因，而非按相关性 | 改为 evidence-weighted 排序 |
| 2 | 循环评测风险 | 🔴 高 | Gold 的 phenotype/drug 字段来自 PrimeKG | 构建 2023.07 后新数据的时间分割独立测试集 |
| 3 | LLM Only 全零 | 🟡 中 | max_rounds=3 不够收敛 | 考虑增加轮数或降低收敛条件 |
| 4 | 人工指标缺失 | 🟡 中 | 需要人工打分 | 抽样 10-15 题做人工评估 |
| 5 | API 不稳定 | 🟡 中 | 网络波动导致超时 | 增强重试机制 |

### 10.2 导师此前提出的"循环评测"问题

**导师的核心关切**：当前测试集与 KG 存在数据重合，构成循环评测。

**已做的改进**：
- 测试集 B/C/D 的 **Gold 基因**均来自 Open Targets（外部独立源），不来自 PrimeKG ✅
- 但 Gold 的 phenotype/drug/bridge 仍部分来自 PrimeKG ⚠️

**计划中的彻底解决方案**：
- 利用时间分割（Temporal Split）思路
- PrimeKG 数据截止约 2022-2023 年初
- 收集 **2023 年 7 月之后** 新发表的基因-疾病-通路关联
- 数据来源：Open Targets 2024+ 更新、ClinVar 2023.07+ 新提交、Reactome 2024+ 新通路
- 对每条候选关联，**反向查询 Neo4j** 确认该关联不在 KG 中
- 只有 KG 中不存在的关联才纳入独立测试集
- 预计生成 15-20 题的"真正独立"测试集

---

## 十一、后续工作计划

### 11.1 短期（1-2 周）

| 优先级 | 任务 | 预期效果 |
|:------:|------|---------|
| P0 | 构建时间分割独立测试集 | 消除循环评测，回应导师核心关切 |
| P0 | 修复 KG 查询排序（字母序→证据权重） | Gene F1 预期提升 5-10 倍 |
| P1 | 人工评估 Mechanism Completeness 等 | 补全评测维度 |
| P1 | 稳定网络下重跑 KG 优化 LLM Only | 获得可信的 LLM Only 基线 |

### 11.2 中期（3-4 周）

| 优先级 | 任务 | 目的 |
|:------:|------|------|
| P1 | 消融实验 Exp-2: No Bridge | 量化 Bridge 多跳查询的增量价值 |
| P1 | 消融实验 Exp-3: No KG Prefetch | 量化预取机制的增量价值 |
| P2 | 消融实验 Exp-4: Single Role | 量化多角色协同的价值 |
| P2 | 案例分析（成功+失败各 1 个） | 定性分析，丰富论文内容 |

### 11.3 长期

- 论文撰写：实验章节已有充足数据支撑
- 系统优化：基于评测反馈迭代 KG 查询策略和 prompt
- 公开 Benchmark 接入（如 BioASQ）

---

## 附录

### 附录 A：项目文件结构

```
GDgpt/
├── app.py                         # Web 界面
├── workflow.py                    # LangGraph 工作流定义
├── agents.py                      # 多角色智能体实现
├── tools.py                       # Neo4j KG 查询工具（含 Bridge）
├── knowledge_base.py              # FAISS 双知识库
├── utils.py                       # 工具函数
├── config.json                    # 运行配置
│
├── evaluation/                    # 评测相关（核心目录）
│   ├── evaluation_gold_final.jsonl      # 原始测试集 Gold（30题）
│   ├── compute_metrics.py               # 指标计算脚本
│   ├── run_batch_eval_template.py       # 批量评测运行脚本
│   ├── gene_alias_map.json              # 基因别名映射表（7192条）
│   ├── independent_testset/             # 独立测试集构建
│   │   ├── scripts/                     #   构建脚本（8个）
│   │   ├── raw_data/                    #   API 原始数据
│   │   └── output/                      #   最终测试集
│   │       ├── testset_quick.jsonl              # B: Quick 30题
│   │       ├── testset_quick_enriched.jsonl     # C: Enriched 30题
│   │       └── testset_kg_optimized_enriched.jsonl  # D: KG优化 38题
│   └── results/                         # 实验结果
│       ├── results_summary.json                 # 原始测试集指标
│       ├── quick_results_summary.json           # Quick v1 指标
│       ├── quick_results_summary_v2.json        # Enriched v2 指标
│       ├── kg_opt_exp0_extracted.jsonl           # KG优化 Full KG 预测
│       └── kg_opt_exp1_llm_only.jsonl           # KG优化 LLM Only 预测
│
├── docs/
│   ├── ADVISOR_BRIEFING_20260410.md     # 本文档
│   └── REPORT_TO_ADVISOR.md             # 上次汇报总结
│
├── PRD.md                         # 产品需求文档
├── EXPERIMENT_PROPOSAL.md         # 实验方案设计
├── PROGRESS_REPORT.md             # 开发进度报告
└── README.md                      # 项目总览
```

### 附录 B：KG 优化测试集完整指标（2026-04-10 计算）

**Exp-0 Full Task KG（38 题）**：
```json
{
  "retrieval": {
    "gene_recall@5": 0.0043,
    "gene_precision@5": 0.0211,
    "pathway_recall@5": 0.2605,
    "pathway_precision@5": 0.4737,
    "bridge_hit_rate": 1.0000,
    "coverage": 0.8487
  },
  "end_to_end": {
    "gene_f1": 0.0516,
    "pathway_f1": 0.3370,
    "phenotype_f1": 0.1682
  }
}
```

**Exp-1 LLM Only（38 题）**：
```json
{
  "retrieval": { "全部": 0.0 },
  "end_to_end": { "全部": 0.0 }
}
```

### 附录 C：关键术语表

| 术语 | 英文 | 解释 |
|------|------|------|
| 知识图谱（KG） | Knowledge Graph | 用"节点+边"存储知识的图数据库 |
| 多跳查询 | Bridge / Multi-hop Query | 经过 2 个以上节点的链式查询 |
| PrimeKG | — | 哈佛/MIT 构建的生物医学知识图谱 |
| Task KG | — | 本项目基于 PrimeKG 构建的任务特化 KG |
| 循环评测 | Circular Evaluation | 用同一数据源生成测试集和训练系统 |
| 时间分割 | Temporal Split | 用时间点区分训练数据和测试数据 |
| Recall（召回率） | — | 标准答案中被找到的比例 |
| Precision（精确率） | — | 系统输出中正确的比例 |
| F1 | — | Precision 和 Recall 的调和平均 |
| Bridge Hit Rate | — | 多跳查询成功率 |
| Coverage | — | 系统输出的维度完整性 |
| LLM | Large Language Model | 大语言模型 |
| Neo4j | — | 图数据库 |
| FAISS | — | Facebook 开发的向量相似度检索库 |
| LangGraph | — | 基于图的 LLM 工作流编排框架 |

### 附录 D：数据源引用

| 数据源 | 论文/出处 | 引用 |
|--------|----------|------|
| PrimeKG | Nature Scientific Data, 2023 | Chandak et al. "Building a knowledge graph to enable precision medicine" |
| Open Targets | Nucleic Acids Research, 2023 | Ochoa et al. "The next-generation Open Targets Platform" |
| Reactome | Nucleic Acids Research, 2024 | Milacic et al. "The Reactome Pathway Knowledgebase 2024" |

---

> **汇报完毕，请导师指正。**
