# 导师反馈深度分析与应对策略

> **日期**：2026 年 4 月 17 日  
> **反馈来源**：导师会议  
> **核心问题**：  
> 1. 应用场景不明显，故事没讲好，目前不足以毕业  
> 2. 测试集要面向场景，测的是系统不是性能，需要有 baseline 对比

---

## 目录

1. [问题诊断：当前论文的叙事缺陷](#一问题诊断当前论文的叙事缺陷)
2. [可借鉴的论文与讲故事方法](#二可借鉴的论文与讲故事方法)
3. [重新定义应用场景](#三重新定义应用场景)
4. [测试集：面向场景设计](#四测试集面向场景设计)
5. [测试系统 vs 测试性能](#五测试系统-vs-测试性能)
6. [Baseline 对比方案](#六baseline-对比方案)
7. [具体执行建议](#七具体执行建议)

---

## 一、问题诊断：当前论文的叙事缺陷

### 导师说"故事没讲好"，本质问题是什么？

当前你的项目叙事是**技术驱动**的：

```
现状："我做了一个多智能体+KG系统，然后测了一下，KG比不用KG好。"

问题：
  ❌ 没有回答"谁需要这个系统？"
  ❌ 没有回答"在什么真实场景下使用？"
  ❌ 没有回答"解决了用户的什么痛点？"
  ❌ 指标只证明了技术有效性，没有证明实用价值
```

而能毕业/发论文的叙事应该是**场景驱动**的：

```
应该是："某类用户在某个场景下有某个问题，现有工具解决不了，
        我的系统在这个场景下比现有工具更好。"
```

### 当前论文的三个核心缺陷

| # | 缺陷 | 具体表现 |
|:-:|------|---------|
| 1 | **没有明确的目标用户** | "生物医学研究者"太笼统，不知道谁在什么场景下需要这个 |
| 2 | **没有真实使用场景** | 测试题目是自动生成的，不来自真实的科研/临床需求 |
| 3 | **没有有说服力的 baseline** | 只对比了"有KG vs 无KG"（内部消融），没有对比外部工具/方法 |

---

## 二、可借鉴的论文与讲故事方法

### 2.1 直接对标论文（多智能体 + KG + 生物医学）

#### 📌 论文 1：KG4Diagnosis（AAAI-25 Bridge Program）

> *KG4Diagnosis: A Hierarchical Multi-Agent LLM Framework with Knowledge Graph Enhancement for Medical Diagnosis*  
> 华威大学/剑桥大学/牛津大学, 2024

**它是怎么讲故事的**：

| 维度 | KG4Diagnosis | 你的项目（当前） |
|------|-------------|----------------|
| **目标用户** | 全科医生（GP） | ❌ 未明确 |
| **场景** | "患者来找GP描述症状，GP用系统辅助初步诊断和分诊" | ❌ 泛泛的"生物医学问答" |
| **痛点** | GP需要跨362种疾病做判断，人脑不够用 | ❌ 未明确痛点 |
| **系统设计** | GP-Agent → 专科-Agent（模拟真实转诊流程） | 多角色专家会诊 |
| **评测** | 诊断准确性 + 幻觉预防 + 多代理协调 | 检索指标 (P/R/F1) |

**可借鉴的点**：
- ✅ **场景具体化**：不是"医疗AI"，而是"GP初诊辅助"
- ✅ **用户具体化**：不是"医生"，而是"全科医生"，面临的是"跨科判断"的挑战
- ✅ **系统设计映射真实流程**：GP→专科转诊 = 分诊Agent→专家Agent

---

#### 📌 论文 2：RareAgents（AAAI-26 Oral）

> *RareAgents: Autonomous Multi-disciplinary Team for Rare Disease Diagnosis and Treatment*  
> 清华大学, 2024

**讲故事的方式**：

| 维度 | RareAgents | 启发 |
|------|-----------|------|
| **场景** | 罕见病的多学科会诊(MDT) | 这是你的"多角色会诊"设计的完美对标 |
| **痛点** | 罕见病涉及多器官、多学科，单个专科医生无法独立诊断 | 同理：基因-疾病-通路关系涉及多个知识维度 |
| **baseline** | GPT-4o、领域特定模型、通用Agent框架 | 你也需要对比 GPT-4 直接回答 |
| **数据集** | 自建 MIMIC-IV-Ext-Rare（从真实临床数据构建） | 你需要从真实需求构建测试集 |
| **评测** | 诊断准确性、治疗方案质量 | 需要评估系统的实际价值 |

**核心启发**：
- ✅ **找到一个"多智能体真正有用"的场景**：罕见病 MDT 天然需要多角色协作
- ✅ **从真实数据构建测试集**：MIMIC-IV 是真实 ICU 记录
- ✅ **和 GPT-4o 直接对比**：这才是有说服力的 baseline

---

#### 📌 论文 3：iKraph（Nature Machine Intelligence, 2025）

> *A comprehensive large-scale biomedical knowledge graph for AI-powered data-driven biomedical research*

**讲故事的方式**：

| 维度 | iKraph | 启发 |
|------|--------|------|
| **场景** | COVID-19 药物重定位（Drug Repurposing） | 极其具体的应用场景 |
| **评测** | 前4个月发现~1200种候选药物，1/3被后续临床试验验证 | **真实世界验证**，不只是数字指标 |
| **叙事** | "疫情爆发→急需快速找药→KG能在几天内发现潜在治疗方案" | 故事有紧迫感、有价值 |

**核心启发**：
- ✅ **把你的系统放到一个紧迫的、有价值的场景中**
- ✅ **评测不只看数字，要看系统的实际输出是否有用**

---

#### 📌 论文 4：MAGIC（Information Fusion, 2026）

> *Magic: AN LLM-based Multi-agent Activated Graph-reasoning Intelligent Collaboration*

**讲故事的方式**：

| 维度 | MAGIC |
|------|-------|
| **场景** | 肝病诊断——聚焦单一疾病领域，做深做透 |
| **设计** | 多Agent + 图推理，每个Agent有明确的推理职责 |
| **启发** | **不要"什么都做"，选一个疾病领域做深** |

---

#### 📌 论文 5：MIRAGE Benchmark（2024）

> *Benchmarking Retrieval-Augmented Generation for Medicine*

**评测方法论的启发**：

| 维度 | MIRAGE |
|------|--------|
| **数据集** | 整合 5 个现有医学QA数据集（7663题） |
| **baseline** | 6种LLM × 多种检索器 = 41种组合 |
| **核心发现** | "RAG可以把GPT-3.5提升到GPT-4水平" |
| **启发** | baseline要有外部模型对比，不只是内部消融 |

---

#### 📌 论文 6：BioMedAgent（Nature Biomedical Engineering, 2026）

> *Empowering AI data scientists using a multi-agent LLM framework with self-evolving capabilities*

| 维度 | BioMedAgent |
|------|------------|
| **场景** | 生物信息学数据分析自动化 |
| **评测** | 自建 BioMed-AQA benchmark（5类任务） |
| **baseline** | 与多种LLM直接比较 |
| **启发** | 评测要有标准benchmark，展示在实际任务上的能力 |

---

### 2.2 从这些论文中提炼的"讲故事公式"

```
好论文的叙事公式：

  [具体场景] + [明确用户] + [真实痛点] + [你的方案] + [外部baseline对比] + [实际价值验证]

例如：
  "临床基因组学分析师在解读NGS报告时，需要快速查明某突变基因涉及的通路和
   已知药物靶点。目前他们需要分别查询ClinVar、COSMIC、Reactome等多个数据库，
   耗时30-60分钟/样本。我们的系统可以一站式完成这个过程，并且在XX题的真实
   临床案例测试中，准确率优于GPT-4直接回答（XX% vs XX%）。"
```

---

## 三、重新定义应用场景

### 3.1 你的系统最适合什么场景？

分析你系统的能力特征：

| 系统能力 | 具体表现 |
|---------|---------|
| 多跳推理 | Disease→Gene→Pathway 桥接查询 |
| 多维度信息聚合 | 基因+通路+表型+药物一次输出 |
| 可追溯性 | 每条关联标注来源（KG vs LLM推测） |
| 多角色专家分析 | 从基因、通路、药物等多角度解读 |

### 3.2 推荐的三个应用场景（选一个主打）

#### 🎯 场景 A：精准肿瘤学中的基因变异解读辅助（推荐度 ⭐⭐⭐⭐⭐）

```
用户：临床基因组学分析师 / 肿瘤科医生
场景：患者做了基因检测(NGS)，报告显示 BRCA1 突变
需求：快速了解 BRCA1 与患者癌症的关联通路、可用靶向药物、预后表型
痛点：需要分别查 ClinVar + COSMIC + DrugBank + Reactome，耗时且易遗漏

你的系统解决方案：
  输入："BRCA1 mutation in breast carcinoma, what pathways and drugs are relevant?"
  输出：
    - 关联通路：DNA Repair, Homologous Recombination（来自KG，可追溯）
    - 靶向药物：Olaparib（PARP抑制剂，来自KG）
    - 相关表型：家族聚集性癌症（来自KG）
    - 机制解释：BRCA1→DNA修复缺陷→PARP依赖→Olaparib敏感（多Agent综合）
```

**为什么这个场景好**：
1. ✅ **精准肿瘤学是热门方向**——Nature、Lancet 持续有高影响力论文
2. ✅ **完美匹配你的 Disease→Gene→Pathway 多跳查询**
3. ✅ **你的 PrimeKG 主要是癌症疾病（20种都是癌症类）**，天然适配
4. ✅ **测试集可以从真实的 NGS 报告解读需求构建**
5. ✅ **有明确的价值衡量标准**：解读是否准确、是否遗漏重要信息

---

#### 🎯 场景 B：罕见病的多学科机制探索辅助（推荐度 ⭐⭐⭐⭐）

```
用户：罕见病/遗传病研究者
场景：研究一种罕见遗传病（如 Li-Fraumeni 综合征），需要理清基因-通路-表型的全貌
痛点：罕见病信息分散在不同数据库，手动整合困难
你的系统价值：多Agent从不同角度分析，一次性给出全景式机制图谱
```

**注意**：这个场景的挑战是你的 KG 只有 20 种疾病，可能覆盖不够。

---

#### 🎯 场景 C：药物重定位的初步筛选辅助（推荐度 ⭐⭐⭐）

```
用户：药物研究者
场景：探索某种已知药物是否可以用于其他疾病
需求：Drug→Gene→Disease→Pathway 多跳推理
你的系统价值：DrugTargetDiseaseBridge 查询 + 多Agent机制解释
```

---

### 3.3 推荐选择：场景 A（精准肿瘤学基因变异解读）

**理由**：

| 评估维度 | 场景A得分 |
|---------|:--------:|
| 与现有系统能力匹配度 | ⭐⭐⭐⭐⭐ |
| PrimeKG 数据覆盖度 | ⭐⭐⭐⭐⭐ (癌症为主) |
| 学术热度与影响力 | ⭐⭐⭐⭐⭐ |
| 测试集可构建性 | ⭐⭐⭐⭐ |
| 导师认可可能性 | ⭐⭐⭐⭐⭐ |

---

## 四、测试集：面向场景设计

### 4.1 导师说的"面向场景"是什么意思？

```
❌ 当前做法："自动从数据库抓了一批基因-疾病关联，组成题目"
             → 题目不来自真实需求，只是数据的排列组合

✅ 导师期望："从真实的使用场景出发，设计贴近实际的测试用例"
             → 题目应该模拟真实用户在真实场景下会问的问题
```

### 4.2 面向"精准肿瘤学变异解读"场景的测试集设计

#### 测试集来源：真实的临床基因组学问题

| 来源 | 说明 | 独立性 |
|------|------|:------:|
| **ClinVar 致病性变异** | 2023.07 后新提交的 Pathogenic 变异，附带关联疾病 | ✅ |
| **COSMIC（肿瘤变异数据库）** | 高频体细胞突变及关联癌型 | ✅ |
| **OncoKB（精准肿瘤学知识库）** | FDA 批准的靶向治疗证据 | ✅ |
| **高影响力 Case Report** | 2024-2025 年发表的典型临床案例 | ✅ |

#### 测试题目类型：模拟真实临床问题

```
类型1：基因变异解读（Gene Variant Interpretation）
  "A patient with non-small cell lung cancer has an EGFR L858R mutation.
   What are the relevant pathways and approved targeted therapies?"
  
  Gold: 
    - pathways: EGFR signaling, PI3K/AKT, MAPK/ERK
    - drugs: Osimertinib, Gefitinib, Erlotinib
    - genes: EGFR, KRAS, ALK (differential diagnosis)

类型2：治疗方案探索（Treatment Exploration）
  "What targeted therapies are available for HER2-positive breast cancer,
   and what are the molecular mechanisms?"
  
  Gold:
    - drugs: Trastuzumab, Pertuzumab, T-DM1
    - pathways: PI3K/AKT, MAPK via ERBB2
    - genes: ERBB2(HER2), PIK3CA, PTEN

类型3：耐药机制分析（Resistance Mechanism）
  "A colorectal cancer patient developed resistance to Cetuximab.
   What genes and pathways might be involved?"
  
  Gold:
    - genes: KRAS, NRAS, BRAF (resistance markers)
    - pathways: MAPK/ERK, PI3K/AKT
    - mechanism: downstream MAPK activation bypasses EGFR blockade

类型4：多基因综合征分析（Multi-gene Syndrome）
  "A patient with Li-Fraumeni syndrome. What cancers, genes, and 
   surveillance pathways should be considered?"
  
  Gold:
    - genes: TP53 (primary), CHEK2, BRCA1/2 (differential)
    - pathways: p53 signaling, DNA damage response, Cell cycle
    - phenotypes: multiple primary cancers, early onset
```

#### 关键设计原则

| 原则 | 说明 |
|------|------|
| **场景真实性** | 每道题模拟一个临床基因组学分析师的真实查询 |
| **答案多维度** | 每道题都需要基因+通路+药物+机制解释（不是只答基因列表） |
| **难度分级** | Easy（单基因-单疾病）/ Medium（多基因-通路）/ Hard（耐药/综合征） |
| **来源标注** | 每道题的 Gold 标准标注来源（ClinVar ID / COSMIC ID / 论文 DOI） |
| **独立性保证** | Gold 答案来自外部数据库，不来自 PrimeKG |

---

## 五、测试系统 vs 测试性能

### 5.1 导师说的"测试系统不是测试性能"是什么意思？

```
❌ 测试性能："Gene F1 = 0.052, Pathway F1 = 0.337" → 冷冰冰的数字
   → 导师疑问：所以呢？这些数字说明什么？系统到底能不能用？

✅ 测试系统："在XX个真实临床变异解读案例中，系统正确识别了YY%的关键通路，
              且在ZZ%的案例中发现了至少一个有效的靶向药物"
   → 回答了"系统有没有用"这个关键问题
```

### 5.2 系统级评测的四个维度

| 维度 | 评估什么 | 怎么评 | 对应指标 |
|------|---------|--------|---------|
| **信息完整性** | 系统输出是否覆盖了所有关键维度 | 每道题检查基因/通路/药物/表型是否都有输出 | Coverage（已有） |
| **关键信息命中** | 是否找到了最重要的基因/通路/药物 | 不看全集 F1，看"关键实体是否被命中" | Key Entity Hit Rate（新增） |
| **可追溯性** | 每条关联是否标注了来源 | 检查输出中 KG 证据 vs LLM 推测的比例 | Traceability Score（新增） |
| **实用性** | 对真实用户是否有用 | 专家评分 / 模拟用户评估 | Utility Score (1-5)（已有但未填） |

### 5.3 新增"关键实体命中率"指标

```python
# Key Entity Hit Rate 的概念
# 不再看"所有20个gold基因中你命中了几个"（这个数字永远很低）
# 而是看"最关键的3个基因你命中了几个"

def key_entity_hit_rate(gold_key_entities, predicted_entities):
    """
    gold_key_entities: 标注的关键实体（每题3-5个，由专家标注为"必须找到"的）
    predicted_entities: 系统输出的所有实体
    """
    hits = len(set(gold_key_entities) & set(predicted_entities))
    return hits / len(gold_key_entities)

# 例如：
# 乳腺癌的关键基因 = [BRCA1, ERBB2, TP53]（必须找到这3个）
# 系统输出 = [AKT1, ERBB2, TP53, MTOR, SRC, ...]
# Key Hit Rate = 2/3 = 66.7%  ← 这比 Gene R@5 = 4% 有意义多了
```

### 5.4 面向场景的评测报告模板

```
=== 案例 #1：EGFR L858R 非小细胞肺癌变异解读 ===

📋 输入：A patient with NSCLC has EGFR L858R mutation. What pathways and drugs?

🔍 系统输出分析：
  ┌─────────────────────────────────────────────┐
  │ 维度          │ 输出         │ Gold     │ ✓/✗ │
  │───────────────│──────────────│──────────│─────│
  │ 关键基因      │ EGFR ✓      │ EGFR     │ ✅  │
  │ 关联通路      │ PI3K/AKT ✓  │ PI3K/AKT │ ✅  │
  │               │ MAPK ✓      │ MAPK     │ ✅  │
  │ 靶向药物      │ Gefitinib ✓ │ Osimertinib│ ⚠️ │
  │ 耐药提示      │ 无          │ T790M    │ ❌  │
  │ 证据追溯      │ 3条来自KG   │ —        │ ✅  │
  └─────────────────────────────────────────────┘

📊 案例评分：
  - 关键实体命中: 3/4 = 75%
  - 信息完整性: 4/5 维度有输出
  - 可追溯性: 60% 的关联标注了 KG 来源
  - 实用性评分: 4/5（缺少耐药提示扣分）

💡 分析：
  系统成功识别了核心通路(PI3K/AKT, MAPK)和部分靶向药物(Gefitinib)，
  但未能识别更新的一线推荐(Osimertinib)和关键耐药标志物(T790M)。
  这反映了 KG 数据时效性的局限——PrimeKG 可能不包含 2022 年后
  更新的用药指南。
```

---

## 六、Baseline 对比方案

### 6.1 当前问题：只有内部消融，没有外部对比

```
❌ 当前："Full KG vs LLM Only" → 这是消融实验，不是 baseline 对比
   → 相当于"有没有KG"的对比，不是"和别人比怎么样"

✅ 需要的：和"用户目前用的替代方案"做对比
   → 用户不用你的系统，会用什么？
```

### 6.2 推荐的 Baseline 矩阵

| Baseline | 描述 | 测什么 | 实现难度 |
|----------|------|--------|:--------:|
| **B1: GPT-4/GPT-4o 直接问答** | 直接把问题扔给 GPT-4，不接 KG | "商业最强LLM能做到什么？" | ⭐ 极易 |
| **B2: GPT-4 + 简单 Prompt** | GPT-4 + few-shot + 要求结构化输出 | "精心设计 prompt 的 LLM 够不够？" | ⭐ 易 |
| **B3: 单Agent + KG** | 1个Agent接KG，不用多Agent | "多Agent协作到底有没有用？" | ⭐⭐ 中 |
| **B4: RAG（文献检索）** | 用 PubMed 摘要做 RAG，不用 KG | "文献RAG vs KG检索哪个好？" | ⭐⭐ 中 |
| **B5: 你的完整系统** | Multi-Agent + KG + Bridge + Prefetch | 主实验 | ✅ 已有 |

### 6.3 最低可行 Baseline 方案（毕设够用）

如果时间有限，**至少做 B1 + B3 + B5**：

```
B1 vs B5：证明 "LLM + KG 优于纯 LLM"（但这次是和 GPT-4 比，而不是和你自己的 LLM Only 比）
B3 vs B5：证明 "多Agent协作有额外价值"
```

### 6.4 如何实现 GPT-4 Baseline（B1）

```python
# 极其简单的实现
import openai

def gpt4_baseline(question):
    response = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=[{
            "role": "system",
            "content": """You are a biomedical expert. Given a question about 
            gene-disease-pathway relationships, provide a structured answer with:
            1. Relevant genes (list)
            2. Relevant pathways (list)
            3. Relevant drugs (list)
            4. Phenotypes (list)
            5. Mechanism explanation
            
            Format your answer as JSON."""
        }, {
            "role": "user",
            "content": question
        }]
    )
    return parse_structured_output(response)
```

**关键点**：这个 baseline 的意义不在于 GPT-4 答不答得出来，而在于：
1. GPT-4 的回答**不可追溯**——它不告诉你信息来自哪里
2. GPT-4 可能**产生幻觉**——编造不存在的基因-通路关联
3. 你的系统的每条关联都可以追溯到 KG 节点

### 6.5 对比结果的预期叙事

```
预期结果：

| 系统 | Key Gene Hit | Key Pathway Hit | Traceability | Hallucination |
|------|:-----------:|:---------------:|:------------:|:-------------:|
| GPT-4 直接回答    | ~70%   | ~50%   | 0%     | ~30%   |
| 单Agent + KG     | ~40%   | ~60%   | ~80%   | ~5%    |
| 你的完整系统      | ~45%   | ~70%   | ~90%   | ~3%    |

叙事框架：
  "GPT-4 在基因命中率上较高（依赖参数化知识），但缺乏可追溯性
   且有30%的幻觉率。我们的系统虽然基因命中率略低，但通路命中率
   更高（+20%），且90%的关联可追溯到KG来源，幻觉率仅3%。
   在精准肿瘤学这类对准确性和可追溯性要求极高的场景中，
   KG增强的系统更适合作为临床决策支持工具。"
```

这个叙事的核心转变：**不是"我的系统更准"，而是"我的系统更可靠、更适合高风险场景"**。

---

## 七、具体执行建议

### 7.1 优先级排序

| 优先级 | 任务 | 预计耗时 | 影响 |
|:------:|------|:--------:|------|
| **P0** | 确定场景（建议：精准肿瘤学变异解读） | 0.5 天 | 重定义整个论文叙事 |
| **P0** | 构建场景化测试集（15-20 题） | 2-3 天 | 测试集面向场景 |
| **P0** | 实现 GPT-4 Baseline (B1) | 0.5 天 | 有外部 baseline |
| **P1** | 实现单Agent+KG Baseline (B3) | 1 天 | 证明多Agent的价值 |
| **P1** | 添加 Key Entity Hit Rate 指标 | 0.5 天 | "测系统不测性能" |
| **P1** | 写 3-5 个详细案例分析 | 2 天 | 展示系统在场景中的实际价值 |
| **P2** | Hallucination Rate 指标 | 1 天 | 差异化优势 |
| **P2** | Traceability Score 指标 | 0.5 天 | 差异化优势 |

### 7.2 论文叙事重构建议

```
旧叙事（技术驱动）：
  "我们提出了一个基于Task KG的多智能体系统，在基因-疾病-通路问答上
   优于纯LLM。"

新叙事（场景驱动）：
  "精准肿瘤学的临床实践中，基因变异解读需要整合多个异构数据库的知识
  （基因-通路-药物-表型），这一过程耗时且易遗漏关键信息。
   我们提出了GDgpt，一个知识图谱增强的多智能体系统，模拟多学科会诊流程，
   一站式完成变异解读的信息聚合与机制分析。
   在15个真实临床基因组学案例的评测中，GDgpt在关键通路命中率上
   优于GPT-4直接回答（70% vs 50%），且90%的关联可追溯到
   知识图谱来源（vs GPT-4的0%），幻觉率仅3%（vs GPT-4的30%）。
   结果表明，在对准确性和可追溯性要求极高的精准医疗场景中，
   KG增强的多智能体系统比纯LLM更适合作为临床决策支持工具。"
```

### 7.3 论文结构调整建议

```
旧结构：
  1. 背景（笼统的"LLM+KG"）
  2. 系统设计
  3. 实验（P/R/F1 数字）
  4. 结论

新结构：
  1. 背景：精准肿瘤学中基因变异解读的挑战 ← 场景化
  2. 相关工作：KG4Diagnosis、RareAgents、MIRAGE 等 ← 有对标
  3. 系统设计：面向变异解读的多Agent+KG架构
  4. 实验：
     4.1 场景化测试集构建（来源、设计原则）
     4.2 Baseline 对比（GPT-4、单Agent、完整系统）
     4.3 系统级评测（Key Hit Rate、Traceability、案例分析）
     4.4 消融实验（Bridge、Prefetch、多角色的增量贡献）
  5. 案例分析：3-5 个详细的真实变异解读案例
  6. 讨论：KG 增强的条件性有效性、局限性
  7. 结论与展望
```

---

## 附录：参考论文完整列表

| # | 论文 | 发表处 | 与你的关联 |
|:-:|------|--------|-----------|
| 1 | KG4Diagnosis | AAAI-25 | 最直接对标——多Agent+KG+医疗诊断 |
| 2 | RareAgents | AAAI-26 Oral | MDT多学科会诊思路+自建数据集 |
| 3 | iKraph | Nature MI 2025 | KG+AI的应用场景叙事（药物重定位） |
| 4 | MAGIC | Info Fusion 2026 | 多Agent图推理+聚焦单一疾病领域 |
| 5 | MIRAGE/MedRAG | arXiv 2024 | 医学RAG的标准评测方法论 |
| 6 | BioMedAgent | Nature BME 2026 | 多Agent+自建benchmark |
| 7 | KG-EHR (arXiv 2512.01210) | arXiv 2025 | KG辅助LLM的临床预测 |
| 8 | VariantKG | Frontiers 2025 | KG用于基因组变异分析 |
| 9 | Onkopus | NAR 2025 | 精准肿瘤学变异解读框架 |
| 10 | KDGene | Brief. Bioinform. 2024 | KG补全用于基因-疾病关联发现 |

---

> **总结**：导师的两个反馈本质上是同一个问题——**缺乏场景**。  
> "应用场景不明显" = 没说清楚给谁用、解决什么问题  
> "测试集面向场景" = 测试题目不来自真实需求  
> "测系统不测性能" = 不只看 F1 数字，要看系统实际能做什么  
> "有 baseline 对比" = 要和用户真正的替代方案（GPT-4）比  
>  
> **核心行动**：选定"精准肿瘤学基因变异解读"场景，从真实临床需求出发重构测试集，  
> 加入 GPT-4 等外部 baseline，用案例分析展示系统的实际价值。
