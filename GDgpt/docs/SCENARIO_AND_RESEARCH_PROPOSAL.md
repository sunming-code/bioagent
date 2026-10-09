# GDgpt 应用场景与研究思路汇报

> **汇报日期**：2026-04-20
> **版本**：v1.0
> **对象**：指导教师
> **核心目的**：回应导师关于"应用场景不明显 + 测试系统不是测性能 + 要有 baseline"的反馈，给出**可落地、有参考论文、适合毕业和发表**的场景定位与研究路线

---

## 0. TL;DR（一页速读）

- **你现在的 KG（10,133 节点 / 87,838 边 / 20 种疾病、主要是癌症）不是"太少"，而是"任务型子图"**。这种"领域特定 Task KG"在 AAAI/Nature/Information Fusion 的对标论文里非常常见（KG4Diagnosis、RareAgents、MAGIC），**不需要重建**，只需要**重新给它安上一个明确的故事**。
- 推荐毕业聚焦的**主应用场景**：**"精准肿瘤学中的分子肿瘤委员会（MTB）辅助 —— 基因-疾病-通路-药物机制解释与可追溯推理"**。这条路线 2025-2026 年是期刊热点（Nature Comm 2026 Knowledge Connector、Cancer Cell 2025 context-LLM、JCO-PO 2024），目标用户（肿瘤科医生+遗传咨询师）非常清晰。
- 把**次要场景**定位为：**药物重定位线索生成** 和 **罕见遗传病机制解释**，既可做案例分析又可在论文讨论里做"泛化性演示"。
- **测试"系统"而非"性能"** 的核心是：**从"能不能命中基因"升级为"能不能给医生一份可用、可追溯、不幻觉的机制报告"**。为此增加三个新指标：Traceability、Hallucination Rate、Clinical Utility（专家打分）；并用**人类专家 + GPT-4o 直答 + 单Agent+KG** 作为三档外部 baseline。
- **测试集策略**：保留你现在的 38 题 KG 优化集做"消融和内部对比"；新建 **20 题 MTB 场景导向独立测试集**（2023.07 后 ClinVar/Open Targets/OncoKB 新数据 + 2024-2025 真实 MTB 案例报告），作为论文主实验。

---

## 1. 导师反馈的本质与破题思路

### 1.1 导师两条反馈其实是同一件事

| 导师原话 | 翻译成研究语言 | 破题方向 |
|---------|--------------|---------|
| "应用场景不明显，故事讲不好" | 你没说清**给谁用、解决什么真实痛点** | 明确**用户角色 + 使用时刻 + 可替代方案** |
| "测试集要面向场景" | Gold 标签不能只来自 KG 本身 | **以真实临床任务**为出发点反向设计测试集 |
| "测系统不是测性能" | F1 = 0.05 这种指标不体现"系统能不能用" | 增加**可用性 / 可追溯性 / 幻觉率 / 临床效用** |
| "要有 baseline" | 不能只跟"LLM Only 全零"比，这是无效对比 | 跟**医生真正会用的替代方案**（直接问 GPT-4、查 UpToDate、PubMed 搜索）比 |

### 1.2 一句话总结你现在的问题

> **你现在的系统可以答一些题，但讲不出"谁会用、为什么要用、比什么都好"。论文读者看完只能得出结论："KG 查到一些基因"，而不是"这个系统解决了 X 用户的 Y 痛点"。**

---

## 2. 参考论文与场景借鉴（2024-2026 最新）

我重点挑出 **8 篇**与你项目高度相关的论文，并提炼每篇的**讲故事公式**。

### 2.1 最直接对标的 3 篇

#### ① DeepRare（Nature 2026，清华 + 上交 + 哈佛）⭐⭐⭐⭐⭐

- **链接**：<https://www.nature.com/articles/s41586-025-10097-9>
- **场景定位**：**罕见病鉴别诊断决策支持**（Diagnostic co-pilot），缓解"诊断奥德赛"（患者平均 5 年以上才能确诊）
- **用户画像**：
  - 罕见病专科医生（验证思路、获取最新文献）
  - 非专科医生 / 全科医生（获取专家级建议）
  - 遗传咨询师（整合 VCF + 表型）
- **Baseline（15+ 种）**：通用 LLM（GPT-4o / DeepSeek-V3 / Claude-3.7）/ 推理 LLM（o3-mini / DeepSeek-R1）/ 医疗 LLM（Baichuan-M1）/ 专科工具（PhenoBrain / PubCaseFinder / Exomiser）/ 智能体系统（MDAgents）
- **评测指标**：Recall@1/3/5、**专家一致性**（推理链被专家接受的比例达 95.4%）、**长尾疾病诊断率**（小于 10 个病例的罕见病）
- **测试集**：**6,401 例**多中心数据（论文病例 + 案例报告 + 真实临床中心），**时间分割**（近期做测试，历史做参考库）

→ **你能借鉴的点**：
- **"traceable reasoning"** 这个提法可以原样用——这正是你 Bridge 查询的卖点（推理路径可追溯到 KG 边）
- 评测上引入 **"专家一致性"** 指标——请 1-2 位合作医生对系统输出打分
- 测试集用**时间分割** + **真实案例报告**

#### ② RareAgents（AAAI-26 Oral，清华）⭐⭐⭐⭐⭐

- **链接**：<https://arxiv.org/abs/2412.12475>
- **场景**：**罕见病多学科会诊（MDT）**，用多 Agent 模拟不同专科医生协同诊断
- **架构**：和你的"7 种角色专家会诊"几乎一致
- **讲故事公式**：`具体病人案例 → 单专科看不全 → 需要 MDT → 我们用多 Agent 自动化 MDT`

→ **你能借鉴的点**：你的 `GeneCurator + DiseaseMechanismAnalyst + PathwayBiologist + PhenotypeMapper + DrugMechanismAnalyst + EvidenceReviewer + HypothesisIntegrator` 这 7 角色本身就是一个**自动化 MTB/MDT**，论文里要明确把角色映射到真实委员会里的专家席位。

#### ③ Knowledge Connector（Nature Communications 2026，德国癌症研究中心 DKFZ）⭐⭐⭐⭐⭐

- **链接**：<https://www.nature.com/articles/s41467-026-68333-3>
- **场景**：**分子肿瘤委员会（MTB）决策支持系统**，面向精准肿瘤学
- **用户流程**：
  1. 输入多组学数据（WGS/RNA-seq/基因 panel）
  2. 识别生物标志物（HRD、TMB、SNV、CNV、融合基因）
  3. 自动关联 OncoKB / CIViC 等外部知识库
  4. 生成治疗建议 + 临床试验匹配
  5. 输出给 MTB 会议讨论
- **评测方法**：
  - **结构化用户调查**（21 位用户）：可视化、整合度、工作流改善、效率
  - **实际使用数据**：268 个真实病例，90.7% 至少获得 1 条临床干预建议；56.3% 匹配到合适的临床试验
  - **案例验证**：HRD 阳性甲状腺癌 / AGK::BRAF 融合腮腺癌等具体案例
- **关键数据点（很适合写进你的论文 intro）**：`MTB 是精准肿瘤学的标准工作流但负担很重；AI 辅助是大势所趋`

→ **你能借鉴的点**：**MTB 就是你最适合的主场景**！它是临床已经接受的工作流，痛点明确（专家忙、证据分散、文献更新快），测试集可从公开 MTB 案例报告、OncoKB / CIViC 的新增条目构建。

### 2.2 药物重定位方向的 2 篇

#### ④ Drug Repurposing with Graph-of-Thoughts on PrimeKG（OpenReview 2025）⭐⭐⭐⭐⭐

- **链接**：<https://openreview.net/forum?id=lbnPkTlwyR>
- **卖点**：**直接基于 PrimeKG**，用 GoT（Graph of Thoughts）做药物重定位，与你的 KG 完全同源
- **意义**：证明了 PrimeKG 子图 + LLM 推理是有效且有发表价值的组合

#### ⑤ DrugReX（Bioinformatics 2025）⭐⭐⭐⭐

- **链接**：<https://pubmed.ncbi.nlm.nih.gov/40585221/>
- **卖点**：literature-based KG + embedding + scoring + LLM 解释；明确给出可解释的药物重定位证据

→ **你能借鉴的点**：你的系统完全可以做**药物重定位的线索生成**，用 `DrugTargetDiseaseBridge` 查询：`drug → gene → disease`，生成"某药物可能对某疾病有效"的**假设 + 机制链 + 证据引用**。这可以做成**场景二（次要场景）**。

### 2.3 机制/假设生成方向的 2 篇

#### ⑥ RUGGED（Retrieval Under Graph-Guided Explainable Disease Distinction，2024）⭐⭐⭐⭐

- **链接**：<https://arxiv.org/abs/2407.12888>
- **卖点**：**可解释的生物医学假设生成**，明确"让研究者提出新假设"作为场景
- 用 KG-guided RAG 让 LLM 生成可追溯的假设

#### ⑦ Multi-agent LLM for Biomedical Hypothesis Generation（Cell Reports Methods 2025）⭐⭐⭐⭐

- **链接**：<https://www.sciencedirect.com/science/article/pii/S258900422502245X>
- **卖点**：多 Agent + LLM 做机制假设生成，预测了一个阿尔茨海默病的药物组合并**体外实验验证**
- **关键**：论文用 **in-vitro 实验验证** 了模型预测 → 场景价值被证实

### 2.4 MTB / 精准肿瘤学的 1 篇背景文献

#### ⑧ ESMO NGS Recommendations（Mosele et al., Annals of Oncology 2020）

> ⚠️ **2026-07-06 引文修正**：此前引用的 "ESMO Precision Oncology Working Group MTB Recommendations (Annals of Oncology 2025)" DOI `10.1016/S0923-7534(25)00080-8` 经 Crossref/doi.org 核实**不存在（404）**，属误引，已替换为下方真实文献。

- **正确引文**：F. Mosele et al., *"Recommendations for the use of next-generation sequencing (NGS) for patients with metastatic cancers: a report from the ESMO Precision Medicine Working Group"*, **Annals of Oncology, 2020, 31(11):1491–1505**, DOI `10.1016/j.annonc.2020.07.014`（已联网核实）
- **意义**：ESMO 官方对转移性癌症 NGS 使用的推荐，是论文引言里证明"精准肿瘤学多组学检测已是临床标准"的**权威依据**。
- **说明**：ESMO 是 *Precision **Medicine** Working Group*（非 "Precision Oncology"）。若需专门的 MTB 工作流权威背书，另可补引 Luchini/Horak 等 MTB 综述（引用前须逐一核实 DOI）。

### 2.5 对标论文的讲故事公式总结

```
公式：具体场景 + 明确用户 + 真实痛点 + 现有方案不足 + 我们的系统 + 外部 Baseline + 专家验证
例：
  场景：精准肿瘤学的 MTB 会议准备
  用户：肿瘤科医生 + 遗传咨询师
  痛点：每个病人 1-2 小时准备，要查 OncoKB / CIViC / PubMed / ClinicalTrials 四个源
  现有方案：Knowledge Connector (Nature Comm 2026) 但只做知识聚合，不做多跳机制推理
  我们：KG（PrimeKG 子集）+ Bridge 多跳 + 多 Agent 自动生成机制报告
  Baseline：GPT-4o 直答 / RAG only / 单 Agent / 专业医生
  验证：3 位肿瘤科医生对系统输出打分（Traceability / Utility / Hallucination）
```

---

## 3. 推荐的三层应用场景架构

### 3.1 主场景（毕业论文聚焦）：精准肿瘤学的机制解释辅助

#### 场景定义

> **"帮助肿瘤科医生在分子肿瘤委员会（MTB）准备阶段，快速生成某个癌症患者的'基因-疾病-通路-药物'机制解释报告，所有结论可追溯到 PrimeKG 的具体边和 Reactome 通路来源。"**

#### 为什么这个场景最适合你

| 评估维度 | 匹配度 | 理由 |
|---------|:------:|------|
| 与现有 KG 数据的匹配度 | ⭐⭐⭐⭐⭐ | 你的 20 种疾病**主要是癌症**（breast / lung / hepatocellular / ovarian / prostate / pancreatic carcinoma 等）——天然就是精准肿瘤学领域 |
| PrimeKG 的相关数据密度 | ⭐⭐⭐⭐⭐ | ASSOCIATED_WITH = 30,854 条；TREATS + OFF_LABEL_FOR + CONTRAINDICATED_FOR = 574 条；TARGETS = 18,392 条 |
| Bridge 查询的价值 | ⭐⭐⭐⭐⭐ | MTB 医生天然需要 `disease → gene → pathway → drug` 多跳推理 |
| 学术热点（2025-2026） | ⭐⭐⭐⭐⭐ | Nature Comm 2026 (Knowledge Connector)、Cancer Cell 2025 (context-LLM)、JCO-PO 2024（多篇） |
| 测试集可构建性 | ⭐⭐⭐⭐ | OncoKB / CIViC / ClinVar 每月更新；MTB 案例报告每年发表几百篇 |
| 导师认可可能性 | ⭐⭐⭐⭐⭐ | 应用场景清晰、有真实用户（肿瘤医生）、可合作临床资源 |

#### 用户画像与使用时刻

**典型用户 A：肿瘤科住院医生（Oncology Fellow）**
- **场景**：MTB 会议前 1 天，手上 3-5 个复杂病例需要准备
- **痛点**：每个病例要查 OncoKB（变异可行动性）→ CIViC（证据）→ PubMed（最新机制）→ ClinicalTrials（可用试验），耗时 1-2 小时
- **传统替代方案**：UpToDate + 手动搜索 PubMed
- **新替代方案（2025）**：直接问 GPT-4o → 问题是会幻觉、来源不可追溯
- **你的系统价值**：**自动生成机制草稿 + 所有结论可追溯到 KG 边 + 明确区分 "图谱事实" vs "LLM 推测"**

**典型用户 B：分子诊断实验室的遗传咨询师**
- **场景**：拿到一份测序报告，需要向临床医生和患者解释"这个突变意味着什么"
- **痛点**：需要同时解释基因功能、相关通路、疾病关联、可用药物
- **你的系统价值**：多角色 Agent 给出**"基因视角 + 通路视角 + 药物视角"** 的完整解释

#### 主场景下的 3 个典型用例

| 用例 ID | 用例描述 | 涉及 KG 查询 | 可对比 Baseline |
|:------:|---------|------------|-----------------|
| UC-1 | 乳腺癌患者 HER2+ 分型的治疗通路解释 | DiseaseToGene + DiseaseGenePathwayBridge + DiseaseToDrug | GPT-4o 直答 / Knowledge Connector 风格聚合 |
| UC-2 | 突变基因 PIK3CA 的信号通路与可用靶向药 | GeneToPathway + GeneToDrug + GeneToDisease | GPT-4o / UpToDate-style 搜索 |
| UC-3 | Tamoxifen 的作用机制、适应症与禁忌 | DrugTargetDiseaseBridge + DrugToDisease | DrugBank 直接查 + GPT-4o |

### 3.2 次要场景（论文讨论章节 + 案例演示）：药物重定位线索生成

#### 场景定义

> **"为药物研究者生成'某已知药物可能对某其它疾病有效'的假设及机制解释，支持早期 in silico 药物重定位筛选。"**

#### 用户画像

- **药物研发早期 discovery 阶段的研究者**：想快速筛一批候选重定位组合
- **学术机构的转化医学研究员**：在做假设生成

#### 价值点

- 用 `DrugTargetDiseaseBridge` 查询：drug → target gene → disease 多跳路径
- 多 Agent 输出"**支持证据 + 反对证据 + 机制链 + 文献线索**"
- 与 iKraph (Nature MI 2025)、DrugReX (Bioinformatics 2025) 对标

### 3.3 泛化场景（展望章节）：罕见遗传病机制解释

#### 场景定义

> **"接入更全面的罕见病 KG（如 Orphanet、HPO）后，系统可扩展用于罕见遗传病的多学科会诊辅助。"**

#### 说明

- **不作为主实验**（你现在 KG 只有 76 个表型，不足以做）
- 在**未来工作**章节说明：系统架构可直接迁移到 RareAgents 或 DeepRare 的场景
- 价值：说明系统的**可扩展性**

---

## 4. 研究思路升级：从"测性能"到"测系统"

### 4.1 新的评测维度（回应"测系统不测性能"）

| 维度 | 指标 | 计算方式 | 你要干什么 |
|-----|------|---------|-----------|
| **正确性** | Gene/Pathway/Drug F1（保留） | 已有 | 保持现有评测 |
| **可追溯性** | **Traceability Score**（新） | 输出中能追溯到 KG 边的结论占比 | 写脚本统计 Agent 输出里引用 `[KG: ...]` 的比例 |
| **忠实度** | **Hallucination Rate**（新） | 输出中**不能**追溯到 KG / 文献的"编造"比例 | 人工标注 3 类（KG 支持 / 文献支持 / 编造） |
| **完整性** | **Mechanism Completeness**（0-2） | 是否给出了完整的 Disease → Gene → Pathway → Drug 链 | 人工打分 |
| **临床效用** | **Utility Score**（1-5） | 医生觉得这份报告对临床决策"有用"吗 | 请 1-2 位肿瘤医生打分 |
| **效率** | **Time-to-insight** | 系统输出 vs 人工准备所用时间 | 记录系统耗时，对比医生估计时间 |
| **可用性** | **Usability Survey** | 仿 Knowledge Connector 的 5 维度用户调研 | 让医生填问卷 |

### 4.2 新的 Baseline 矩阵（回应"要有 baseline"）

把 Baseline 分为 3 档，避免"LLM Only 全零"这种无效对比：

#### Tier A：商业最强 LLM（证明 KG 的必要性）

| Baseline | 配置 | 你能证明什么 |
|---------|------|-------------|
| **GPT-4o 直答** | 裸 GPT-4o | "GPT-4o 很强，但**没有可追溯性 + 有幻觉**，所以需要 KG" |
| **Claude-3.7 直答** | 裸 Claude | 排除模型偏差 |
| **GPT-4o + Web Search** | GPT-4o + Bing | "就算加了搜索，还是不如结构化 KG 准确" |

#### Tier B：相关系统（证明你的架构设计）

| Baseline | 配置 | 你能证明什么 |
|---------|------|-------------|
| **单 Agent + KG** | 1 个 Agent 用你的 KG | "多 Agent 协同确实比单 Agent 好" |
| **RAG only（KG→文本）** | 把 KG 查询结果塞给 LLM，不做 Bridge | "多跳 Bridge 查询比单跳 RAG 好" |
| **GraphRAG** | 用 MS GraphRAG | "你的 Bridge 设计比通用 GraphRAG 好" |

#### Tier C：专业方案（证明临床价值）

| Baseline | 配置 | 你能证明什么 |
|---------|------|-------------|
| **OncoKB 手动查询** | 医生手动查 OncoKB | "你比人工查快 X 倍，信息更全" |
| **Knowledge Connector 风格聚合** | 只做 KG 聚合不做多跳推理 | "你比单纯聚合多了机制推理" |

### 4.3 新的测试集策略（回应"测试集要面向场景"）

#### 保留现有 4 套（做内部消融）

| 测试集 | 用途 |
|-------|-----|
| A 原始 30 题 | 已知循环评测，只做内部对比参考 |
| B/C Quick Enriched | 做 baseline 稳定性验证 |
| D KG 优化 38 题 | 当前主实验集，作内部消融 |

#### 新建 2 套（做主实验 + 泛化）

**新测试集 E：MTB 场景导向独立测试集（15-20 题，主实验）**
- **数据来源**：
  - OncoKB 2024-2025 新增 Level 1-2 可行动变异
  - CIViC 2024+ 新证据条目
  - ClinVar 2023.07+ Pathogenic / Likely Pathogenic
  - **2024-2025 真实 MTB 案例报告**（从 JCO Precision Oncology / Annals of Oncology 提取）
- **题目格式**：
  ```json
  {
    "id": "MTB_001",
    "question": "A 58yo female with HER2+ breast cancer, liver metastasis. What are the actionable alterations and treatment mechanisms?",
    "clinical_context": "...",
    "gold_actionable_genes": ["ERBB2"],
    "gold_pathways": ["PI3K/AKT", "MAPK"],
    "gold_drugs": ["Trastuzumab", "Tucatinib"],
    "gold_evidence_source": "OncoKB 2024-11, PMID: 12345678",
    "annotation_status": "clinician_verified"
  }
  ```
- **标注**：请 1-2 位合作医生/遗传咨询师验证
- **规模**：20 题（覆盖 5 种主要癌症 × 4 种任务）

**新测试集 F：时间分割泛化集（10-15 题，泛化实验）**
- 来源：PrimeKG 截止日期（2023.07）之后的 Open Targets 高置信度新关联
- 目的：测试系统在"KG 里压根没有的关联"上能否通过 LLM 的文献补充给出合理答案
- 这个就是你原来 Plan 里的 independent testset，**保留但降级为"泛化验证"而非主实验**

---

## 5. 论文结构重构建议

### 5.1 原结构 vs 新结构

| 原结构（性能导向） | 新结构（场景导向） |
|------|--------|
| 1. Intro：LLM+KG 很火 | 1. Intro：**MTB 是精准肿瘤的标准流程，但准备耗时且容易遗漏** |
| 2. 方法：多 Agent + KG | 2. **用户研究**：访谈 2 名肿瘤医生，梳理 MTB 准备痛点 |
| 3. 实验：F1 对比 | 3. 方法：Agent 设计**映射到 MTB 专家席位** |
| 4. 消融 | 4. 系统实现 |
| 5. 案例 | 5. 实验：**场景导向 + 多档 Baseline + 专家打分** |
| 6. 总结 | 6. **三个真实 MTB 案例深度分析** |
|       | 7. 局限（KG 只覆盖 20 种癌症、未接入真实 EHR）与泛化（罕见病） |

### 5.2 Intro 范例（给你参考）

> 精准肿瘤学依赖对肿瘤基因组的多组学检测来指导治疗决策，ESMO 已就转移性癌症的 NGS 使用给出官方推荐 [Mosele et al., Ann Oncol 2020]；分子肿瘤委员会（MTB）作为整合基因组、病理、临床等多源证据的会诊机制，其准备阶段需要医生查阅 OncoKB、CIViC、PubMed 等多个异构来源 [Nature Reviews Clin Oncol 2023]，平均每例耗时 1-2 小时。近期研究 [Knowledge Connector, Nature Commun 2026] 尝试用 AI 辅助聚合多源证据，但主要关注可视化与数据整合，未提供**机制层面的多跳推理**。与此同时，通用大语言模型（如 GPT-4o）虽然能生成流畅的解释文本 [JCO Precision Oncology 2024]，但存在**幻觉**和**证据不可追溯**两个关键问题，限制了其在高风险临床决策中的使用 [Cancer Cell 2025]。
>
> 本文提出 GDgpt，一个基于 PrimeKG 子图的多智能体机制解释系统，为 MTB 准备阶段提供**可追溯、结构化、多角度**的基因-疾病-通路-药物机制报告。系统的关键贡献包括：（1）设计 Bridge 多跳 Cypher 查询将 disease → gene → pathway → drug 的推理路径显式化；（2）7 种专家 Agent 映射 MTB 中的真实专家席位；（3）明确区分"图谱支持的事实"和"LLM 推测性结论"。在一个**基于 OncoKB 2024+ 新增证据和真实 MTB 案例报告构建的场景导向测试集** 上，GDgpt 相比 GPT-4o 直答在可追溯性上提升 5 倍，幻觉率降低至 3%，获得 3 位肿瘤医生 4.2/5 的临床效用评分。

---

## 6. 对你现在 Plan 的调整建议

### 6.1 原 Plan 的问题

你当前的 Plan 聚焦于"**构建独立测试集**"，这**仍然停留在"测性能"的层次**——只是换个 Gold 来源而已，**没有解决导师的核心反馈**。

### 6.2 建议的新 Plan 结构（分三步）

| 步骤 | 任务 | 预计时间 | 输出 |
|------|------|---------|------|
| **Step 1**（1 周） | 场景定位与论文叙事重构 | 1 周 | 给导师的汇报 PPT（说清楚 MTB 场景）+ 论文 intro v2 草稿 |
| **Step 2**（2 周） | 评测维度升级 | 2 周 | Traceability / Hallucination / Utility 指标的计算脚本 + 实现 GPT-4o Baseline |
| **Step 3**（3 周） | MTB 场景测试集构建 + 主实验 | 3 周 | 20 题 MTB 测试集 + 完整实验报告（含专家打分） |

> 原 Plan 里的"独立测试集构建"**作为 Step 3 的一部分**，但**降级**为"泛化实验"，不再是主实验。

### 6.3 对 KG 本身的建议

**不要重建 KG**。你的 20 种癌症 + 10,133 节点的 Task KG **对 MTB 场景完全够用**，理由：

- 20 种疾病几乎全是主流癌症 → 覆盖 MTB 高频病例
- 3,582 基因 + 1,725 通路 + 4,730 药物 + 30,854 疾病-基因关联 → 数据密度很高
- Knowledge Connector (Nature Comm 2026) 也只用 OncoKB / CIViC（远小于 PrimeKG 全量）

**可选的小改进**（性价比高）：

| 改进 | 成本 | 收益 |
|-----|-----|------|
| KG 查询改**证据加权排序**（而不是字母序） | 1 天 | Gene Recall 从 0.05 → 预估 0.2+ |
| 提高 `DiseaseToGene` 的 k 从 8 → 20 | 0.5 天 | 召回翻倍 |
| 补充 `kg_gene_count` 元数据以便评测 | 0.5 天 | 指标更准确 |

---

## 7. 与导师汇报的 3 个核心要点

### 要点 1：承认"场景不够明显"，但给出**清晰的新定位**

> "老师，您指出场景不明显非常对。我读了 Nature Comm 2026 的 Knowledge Connector、Nature 2026 的 DeepRare、AAAI-26 的 RareAgents 之后，重新梳理了我的定位：**我不是在做通用的 biomedical QA，而是在做精准肿瘤学 MTB 准备阶段的机制解释辅助工具**。我的 20 种疾病恰好主要是癌症，我的 Bridge 多跳查询恰好对应 MTB 里的 disease→gene→pathway→drug 推理需求。"

### 要点 2：承认"测试集有循环评测问题"，给出**双轨测试方案**

> "您说测试集要面向场景也非常对。我的新方案是：
> - 保留现有 38 题做内部消融（和 baseline 自比）
> - **新建 20 题 MTB 场景测试集**，数据来自 OncoKB 2024-2025 新增证据 + 真实 MTB 案例报告，让 1-2 位医生验证标签
> - 另建 15 题**时间分割泛化集**（2023.07 后新关联）做泛化验证"

### 要点 3：承认"不该只测性能"，给出**系统级评测方案**

> "传统 F1 指标不体现系统能不能用。我增加三个关键指标：
> - **Traceability Score**：每条结论能追溯到 KG 的比例——这是我对 GPT-4o 的核心优势
> - **Hallucination Rate**：输出中的幻觉比例——这是高风险临床决策的核心关切
> - **Clinical Utility（5 分制）**：请医生打分"这份报告对 MTB 决策有没有用"
>
> Baseline 也从原来的"LLM Only"升级为 **GPT-4o 直答 / GPT-4o+Web / 单 Agent+KG / RAG only**，让对比有说服力。"

---

## 8. 附录：关键参考文献清单

### 8.1 最对标的 5 篇（必读必引）

1. **DeepRare**：Nature 2026 - <https://www.nature.com/articles/s41586-025-10097-9>
2. **RareAgents**：AAAI-26 Oral - <https://arxiv.org/abs/2412.12475>
3. **Knowledge Connector**：Nature Commun 2026 - <https://www.nature.com/articles/s41467-026-68333-3>
4. **KG4Diagnosis**：AAAI-25 - <https://arxiv.org/abs/2412.16833>
5. **PrimeKG**：Nature Sci Data 2023 - Chandak et al.

### 8.2 方法论参考（选引）

6. **Drug Repurposing with GoT on PrimeKG**：OpenReview 2025 - <https://openreview.net/forum?id=lbnPkTlwyR>
7. **DrugReX**（Huang et al.）：⚠️ **Research Square 预印本 2025**（非 Bioinformatics），DOI `10.21203/rs.3.rs-6728958/v1` - 2026-07-06 核实更正。引用时须标注"preprint, not peer-reviewed"
8. **RUGGED**：arXiv 2024 - <https://arxiv.org/abs/2407.12888>
9. **iKraph**：Nature Machine Intelligence 2025 - <https://www.nature.com/articles/s42256-025-01014-w>
10. **MAGIC**：Information Fusion 2026 - <https://www.sciencedirect.com/science/article/pii/S1566253525006293>

### 8.3 背景文献（Intro 必引）

11. **ESMO NGS Recommendations**（Mosele et al.）：Annals of Oncology **2020**, 31(11):1491–1505 - DOI `10.1016/j.annonc.2020.07.014` ⚠️（原引 "Annals of Oncology 2025 / S0923-7534(25)00080-8" DOI 不存在，2026-07-06 已更正）
12. **Nature Rev Clin Oncol MTB Review**：2023 - <https://www.nature.com/articles/s41571-023-00824-4>
13. **context-augmented LLM for precision oncology**：Cancer Cell 2025 - <https://www.cell.com/cancer-cell/fulltext/S1535-6108(25)00551-3>
14. **Expert-Guided LLM for Clinical Oncology**：JCO Precision Oncology 2024 - <https://ascopubs.org/doi/10.1200/PO-24-00478>

### 8.4 多智能体 / AI Agents 综述

15. **Empowering biomedical discovery with AI agents**：Cell 2024 - <https://www.cell.com/cell/fulltext/S0092-8674(24)01070-5>
16. **A comprehensive survey of AI agents in healthcare**：Science Direct 2026

---

## 9. 下一步行动清单（今天就能做）

```
[ ] A. 把本文档发给导师，约一次 30 分钟汇报，确认场景定位是否认可
[ ] B. 用 2 天时间，精读 DeepRare + Knowledge Connector + RareAgents 三篇
[ ] C. 修改 docs/ADVISOR_FEEDBACK_ANALYSIS.md，把精准肿瘤学 MTB 放在最前面
[ ] D. 准备 15 分钟的汇报 PPT，3 页：
     - 第 1 页：场景定位（MTB + 用户画像 + 对标 Knowledge Connector）
     - 第 2 页：新的评测体系（3 档 baseline + 3 个新指标）
     - 第 3 页：新的测试集方案（20 题 MTB + 15 题时间分割）
[ ] E. 确认完场景后，再启动原 Plan 里的独立测试集构建（作为泛化实验）
[ ] F.（可选）联系 1-2 位临床医生，为后续专家打分铺垫
```

---

> **一句话总结**：你的系统不是"数据太少做不了毕业"，而是"没有讲好一个故事"。把场景锚定在**精准肿瘤学 MTB 辅助**上，把评测锚定在**可追溯性 + 幻觉率 + 临床效用**上，把 baseline 锚定在**GPT-4o + 专业工具**上——这三个锚一旦钉下去，整篇论文的叙事就立起来了。

---

*文档结束。欢迎讨论和迭代。*
