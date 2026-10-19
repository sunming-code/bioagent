"""
从 PcQA.json (405题) 筛选适合 GDgpt 评测的子集并转换格式。

PcQA 来源: GigaScience 2025, DOI:10.1093/gigascience/giae082
GitHub: https://github.com/yichun10/bioKGQA-KGT

筛选标准:
  - 优先保留"基因/通路↔癌症"关联题（GDgpt 核心能力）
  - 排除纯药物激活基因类（与 PrimeKG 结构不匹配）
  - 目标 ~100题：50 single-hop (gene-cancer/cancer-gene) + 50 multi-hop/pathway

输出格式与 testset_kg_optimized_enriched_with_edges.jsonl 一致，可直接接
  run_batch_eval_template.py --gold pcqa_100.jsonl

用法:
  python evaluation/external_benchmarks/build_pcqa_subset.py
"""

import json, re, hashlib, random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
RAW  = ROOT / "evaluation/external_benchmarks/PcQA_raw.json"
OUT  = ROOT / "evaluation/external_benchmarks/pcqa_100.jsonl"

# ── 实体提取工具 ──────────────────────────────────────────────

GENE_PAT = re.compile(r'\b([A-Z][A-Z0-9]{1,8}(?:[A-Z0-9])?)\b')
CANCER_KW = ['cancer','carcinoma','tumor','neoplasm','glioma','leukemia',
             'lymphoma','melanoma','sarcoma','adenoma','myeloma','blastoma',
             'mesothelioma','neuroblastoma']
PATHWAY_KW = ['pathway','signaling','apoptosis','proliferation','invasion',
              'metabolism','repair','cycle','expression']
DRUG_ONLY_KW = ['activated by','inhibited by','treat','therapy','drug',
                'inhibitor','chemotherapy','treatment for']

# 常见非基因大写词（过滤假阳性）
NON_GENE = {
    'MET','DNA','RNA','ATP','ADP','PCR','FDA','WHO','MTB','KG','LLM','AI',
    'BRCA','TP53','KRAS','EGFR','BRAF','PIK3CA','PTEN','AKT1','ERBB2',  # 这些是真基因，保留
}
SKIP_NON_GENE = {
    'DNA','RNA','ATP','ADP','PCR','FDA','WHO','MTB','KG','LLM','AI',
    'USA','UK','HER','PFS','OS','QA','KGT','SOKG','GBM','CRC','NSCLC',
    'HCC','AML','CLL','ALL','NHL','MM','CC','EC','GC','PC','BC',
}

def extract_genes(text):
    """从文本中提取可能的基因符号（2-8个大写字母+数字）。"""
    candidates = GENE_PAT.findall(text)
    return sorted(set(g for g in candidates if g not in SKIP_NON_GENE and len(g) >= 2))

def extract_cancers(text):
    """从文本中提取癌症类型短语。"""
    found = []
    text_l = text.lower()
    for kw in CANCER_KW:
        # 找包含此关键词的短语（向前取最多3个词）
        for m in re.finditer(r'[\w\-]+(?: [\w\-]+){0,2} ' + kw + r'|' + kw, text_l):
            phrase = m.group().strip()
            if len(phrase) > 3:
                found.append(phrase)
    return sorted(set(found))

def classify(item):
    """分类题目类型，返回 (type_str, priority_score)。"""
    q = item['question'].lower()
    a = item['answer'].lower()
    both = q + ' ' + a

    is_drug_only = any(kw in q for kw in ['activated by','inhibited by','what drugs','which drug'])
    is_gene_cancer = (
        any(kw in q for kw in ['gene','mutation','associated with','which gene','what gene']) and
        any(kw in both for kw in CANCER_KW)
    )
    is_cancer_gene = (
        any(kw in both for kw in CANCER_KW) and
        any(kw in q for kw in ['gene','mutation','associated','pathway','mechanism'])
    )
    is_pathway = any(kw in both for kw in PATHWAY_KW)
    is_treatment = any(kw in q for kw in ['treat','therapy','drug','inhibitor','medication'])

    if is_drug_only and not is_gene_cancer:
        return 'drug_only', 0
    if is_gene_cancer or is_cancer_gene:
        score = 3 + (1 if is_pathway else 0)
        return 'gene_cancer', score
    if is_pathway:
        return 'pathway', 2
    if is_treatment and any(kw in both for kw in CANCER_KW):
        return 'treatment', 1
    return 'other', 0

def make_id(q):
    return 'pcqa_' + hashlib.md5(q.encode()).hexdigest()[:8]

# ── 主流程 ──────────────────────────────────────────────────

data = json.load(open(RAW, encoding='utf-8'))
print(f"原始题数: {len(data)}")

# 分类 + 过滤
scored = []
for item in data:
    qtype, pri = classify(item)
    if pri > 0:  # 排除 drug_only 和 other
        scored.append((pri, item, qtype))

# 按优先级排序
scored.sort(key=lambda x: -x[0])
print(f"过滤后候选: {len(scored)}")

# 分层采样：gene_cancer 60题 + pathway/treatment 40题
gene_cancer_pool = [(pri, item, qt) for pri, item, qt in scored if qt == 'gene_cancer']
other_pool       = [(pri, item, qt) for pri, item, qt in scored if qt != 'gene_cancer']

random.seed(42)
selected_gc    = gene_cancer_pool[:60]  # 取前60（已按优先级排）
selected_other = other_pool[:40]
selected = selected_gc + selected_other
random.shuffle(selected)
print(f"最终选取: {len(selected)} 题")

# 打印类型分布
from collections import Counter
type_cnt = Counter(qt for _, _, qt in selected)
print("类型分布:", dict(type_cnt))

# ── 转换格式 ──────────────────────────────────────────────

out_lines = []
for pri, item, qtype in selected:
    q = item['question']
    a = item['answer']
    # 从 gold answer 提取实体
    gold_genes    = extract_genes(a)
    gold_cancers  = extract_cancers(a)

    record = {
        "id":              make_id(q),
        "question":        q,
        "gold_answer":     a,
        "question_type":   qtype,
        "source":          "PcQA",
        "source_doi":      "10.1093/gigascience/giae082",
        # 以下字段与 testset_kg_optimized_enriched_with_edges.jsonl 对齐
        "disease_name":    "",          # PcQA 没有单一 focal disease，留空
        "gold_genes":      gold_genes,
        "gold_pathways":   [],          # PcQA 无通路金标，留空
        "gold_phenotypes": [],
        "gold_drugs":      [],
        "expected_kg_edges": [],        # 无 KG 边注释（跨源）
        "task_type":       qtype,
        "kg_coverage":     "unknown",   # 不预设 KG 覆盖度
    }
    out_lines.append(record)

OUT.parent.mkdir(parents=True, exist_ok=True)
with open(OUT, 'w', encoding='utf-8') as f:
    for r in out_lines:
        f.write(json.dumps(r, ensure_ascii=False) + '\n')

print(f"\n✅ 已写出 {len(out_lines)} 题 → {OUT}")
print("\n前3题示例:")
for r in out_lines[:3]:
    print(f"  [{r['question_type']}] {r['question'][:80]}")
    print(f"    gold_genes: {r['gold_genes'][:5]}")
    print(f"    question_type: {r['question_type']}")
