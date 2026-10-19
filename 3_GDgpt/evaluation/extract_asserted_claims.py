"""
从预测的 answer_text 抽取 asserted_claims，供 compute_system_metrics 计算 Hallucination Rate。

两档判定（KG支持 vs 未支持），**公平地衡量内容而非引用行为**，不依赖外部文献：
  判定核心 = 一句话是否锚定在 KG 认识的真实生物实体（基因）上。
  1) 显式 [LLM-inferred]/insufficient 标签 → 直接判未支持。
  2) 否则：正则抽句中的候选基因符号（大写+数字，如 BRCA1/TP53），去 Aura 核实
     是否为 KG 里的真实 Gene 节点。
       句含 ≥1 个 KG 真实基因 → has_kg_support=True（有据，内容锚定在KG实体上）
       句不含任何 KG 基因（纯泛泛描述/未锚定）→ False（潜在幻觉）
  → 对 GDgpt 和 GPT-4o 用同一把尺子量内容：谁说的实体 KG 认识就算有据，
     不惩罚"不引用"（BRCA1 说得对就不算幻觉，即使 GPT-4o 没 cited_edges）。

Hallucination Rate = #(has_kg_support=False) / #claims。
基因存在性查询带本地缓存，避免重复查 Aura。

用法：
  python evaluation/extract_asserted_claims.py --config config.json \
    --pred evaluation/results/cmp3_full_ext.jsonl \
    --out  evaluation/results/cmp3_full_claims.jsonl
"""

import argparse
import base64
import json
import re
import ssl
import urllib.request

# 句子切分：句号/分号/换行（英文为主，兼顾中文句号）
_SENT_SPLIT = re.compile(r"(?<=[.;。;!?])\s+|\n+")

# 显式可信度标签
_KG_TAG = re.compile(r"\[KG[-: ]", re.IGNORECASE)
_LLM_TAG = re.compile(r"\[LLM[- ]?inferred", re.IGNORECASE)
_INSUFFICIENT = re.compile(r"insufficient\s+kg\s+evidence|证据不足", re.IGNORECASE)


def _norm(s):
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


# 候选基因符号：2+ 个大写字母/数字，如 BRCA1, TP53, ABCA3, ERBB2（含连字符如 HLA-A）
_GENE_RE = re.compile(r"\b[A-Z][A-Z0-9]{1,}(?:-[A-Z0-9]+)?\b")
# 常见非基因大写词，排除以降噪
_STOP = {"DNA", "RNA", "HBOC", "KG", "LLM", "MAP", "PI3K", "AKT", "RAF", "II", "III",
         "IV", "MTB", "US", "FDA", "NGS", "SNV", "CNV", "TMB", "HRD", "OK", "ID"}


class GeneVerifier:
    """查基因符号是否为 KG 真实 Gene 节点（带缓存）。"""

    def __init__(self, config_path):
        cfg = json.load(open(config_path, encoding="utf-8"))
        uri = cfg["neo4j_uri"].strip()
        self.host = uri.split("://", 1)[1].split("/", 1)[0].split(":", 1)[0].strip()
        self.user = cfg["neo4j_user"].strip()
        self.pw = cfg["neo4j_password"].strip()
        self.db = (cfg.get("neo4j_database") or "").strip() or self.user
        self.endpoint = f"https://{self.host}/db/{self.db}/query/v2"
        self.auth = base64.b64encode(f"{self.user}:{self.pw}".encode()).decode()
        self.ctx = ssl.create_default_context()
        self.cache = {}

    def is_kg_gene(self, symbol):
        key = symbol.strip().lower()
        if key in self.cache:
            return self.cache[key]
        body = {
            "statement": "MATCH (g:Gene) WHERE toLower(g.name)=$n OR toLower(g.normalized_name)=$n "
                         "RETURN count(g) AS c",
            "parameters": {"n": key},
        }
        req = urllib.request.Request(self.endpoint, data=json.dumps(body).encode(), method="POST")
        req.add_header("Authorization", f"Basic {self.auth}")
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=30, context=self.ctx) as r:
                c = json.loads(r.read().decode())["data"]["values"][0][0]
            ok = c > 0
        except Exception:
            ok = False
        self.cache[key] = ok
        return ok


def split_claims(text):
    parts = [p.strip() for p in _SENT_SPLIT.split(text or "") if p.strip()]
    return [p for p in parts if len(p) >= 15]


def candidate_genes(sentence):
    """抽句中候选基因符号（去停用词、去纯数字）。"""
    out = []
    for m in _GENE_RE.findall(sentence):
        if m in _STOP or m.isdigit() or len(m) < 3:
            continue
        out.append(m)
    return out


def judge_claim(sentence, verifier):
    """返回 (has_kg_support, reason)。以'句中是否含 KG 真实基因'判有据。"""
    if _LLM_TAG.search(sentence) or _INSUFFICIENT.search(sentence):
        return False, "explicit [LLM-inferred]/insufficient"
    for sym in candidate_genes(sentence):
        if verifier.is_kg_gene(sym):
            return True, f"anchored on KG gene '{sym}'"
    return False, "no KG gene mentioned (generic/unanchored)"


def build_claims(row, verifier):
    text = row.get("answer_text") or row.get("final_answer") or ""
    claims = []
    for sent in split_claims(text):
        supported, reason = judge_claim(sent, verifier)
        claims.append({
            "claim": sent,
            "has_kg_support": supported,
            "reason": reason,
        })
    return claims


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--pred", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    verifier = GeneVerifier(args.config)
    rows = [json.loads(l) for l in open(args.pred, encoding="utf-8") if l.strip()]
    total_claims = 0
    total_unsup = 0
    for r in rows:
        claims = build_claims(r, verifier)
        r["asserted_claims"] = claims
        total_claims += len(claims)
        total_unsup += sum(1 for c in claims if not c["has_kg_support"])

    with open(args.out, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    rate = total_unsup / total_claims if total_claims else float("nan")
    print(f"[saved] {args.out}")
    print(f"[rows] {len(rows)}  claims共 {total_claims}  未支持 {total_unsup}")
    print(f"[hallucination_rate 预览] {rate:.3f}" if total_claims else "[无 claim]")


if __name__ == "__main__":
    main()
