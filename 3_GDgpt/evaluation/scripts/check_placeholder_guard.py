#!/usr/bin/env python3
"""占位符 guard 回归检查（红先行）。

判据来自真实产物 evaluation/results/adapt15_full_raw.jsonl：
v2.2 的 guard 用 `strip().lower()` 精确比对占位符短语，而 safety_reviewer 实际
返回的是 'Continuing discussion\\n```'（带 markdown 栅栏），guard 不命中，
Lead 综合的实质内容被丢掉。

本检查断言两件事，缺一不可：
  POSITIVE —— 产物里真实出现过的占位符串必须被判为占位符；
  NEGATIVE —— 产物里真实的实质答案必须 *不* 被判为占位符（防止修过头把
              正文也当占位符丢掉）。

用法：从仓库根目录运行  python3 evaluation/scripts/check_placeholder_guard.py
退出码 0 = 通过，1 = 失败。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO_ROOT)

RAW = os.path.join(REPO_ROOT, "evaluation", "results", "adapt15_full_raw.jsonl")
# v2.3 的产物。它用的是另一句占位符（agents.py:501 DIVERGED 分支的
# "Continuing analysis — further rounds needed."），只看 adapt15 会漏掉。
RAW_V23 = os.path.join(REPO_ROOT, "evaluation", "results", "pcqa100_gdgpt_raw.jsonl")

# 真实产物之外再补几个同类变体，确保修复是"规范化"而不是把观测串写死
EXTRA_PLACEHOLDERS = [
    "Continuing discussion",            # 裸短语（旧 guard 唯一能命中的形态）
    "```\nContinuing discussion\n```",  # 前后都有栅栏
    "continuing the discussion  \n```",
    "  \n```\n\nN/A\n```  ",
    "None",
    "",
    "   ",
    "Continuing analysis — further rounds needed.",       # agents.py:501 DIVERGED
    "Continuing analysis — further rounds needed.\n```",
    "continuing analysis",
    "TBD",
]

# 必须**不**被当成占位符的实质答案。这些是修过头就会被丢掉的形态。
NEGATIVE_CASES = [
    # 以占位符短语开头但后面是实质内容的长答案
    ("long-tail",
     "Continuing discussion of the mechanism: BRCA1 and BRCA2 loss impairs "
     "homologous recombination repair, which sensitises tumours to PARP "
     "inhibition; TP53 status further modulates the response across the cohort."),
    # "none" 前缀但其实是别的词 —— 卡词边界才不会误伤
    ("none-prefix-word", "Nonetheless, consider olaparib for this patient."),
    # 合法的短否定答案，不是占位符
    ("legit-none-sentence", "None of the eight candidate genes are clinically actionable."),
    # 单行就被栅栏包住的实质答案 —— 整行丢栅栏就会归一化成空串
    ("single-line-fenced", "```BRCA1 loss drives repair deficiency in this tumour```"),
    # 带语言标注的代码块里的实质内容
    ("fenced-json", '```json\n{"gene": "BRCA1", "mechanism": "HR deficiency"}\n```'),
]


def load_real_cases():
    """从两份真实产物里取 final_answer，分成占位符组与实质答案组。

    两份都要读：adapt15 用的是 "Continuing discussion"，v2.3 的 PcQA 产物用的是
    "Continuing analysis — further rounds needed."。只盯一份就会漏掉另一种。
    """
    placeholders, substantive = [], []
    for path in (RAW, RAW_V23):
        if not os.path.exists(path):
            continue
        tag = os.path.basename(path)
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                row = json.loads(line)
                fa = row.get("final_answer", "")
                low = fa.strip().lower()
                is_ph = ((low.startswith("continuing discussion")
                          or low.startswith("continuing analysis"))
                         and len(fa.split()) <= 8)
                if is_ph:
                    placeholders.append(("%s/%s" % (tag[:9], row.get("id")), fa))
                elif len(fa.split()) >= 20:
                    substantive.append(("%s/%s" % (tag[:9], row.get("id")), fa))
    return placeholders, substantive


def main():
    from workflow import is_placeholder_final_answer as guard

    real_ph, real_sub = load_real_cases()
    print("source: %s" % os.path.relpath(RAW, REPO_ROOT))
    print("real placeholder final_answers: %d" % len(real_ph))
    print("real substantive final_answers: %d" % len(real_sub))
    if not real_ph:
        print("FAIL: no placeholder rows found in the raw file; check is vacuous")
        return 1
    print()

    failures = []

    print("--- POSITIVE: must be classified as placeholder ---")
    for qid, text in real_ph:
        ok = guard(text)
        print("  %-5s %-22s %r" % ("ok" if ok else "FAIL", qid, text))
        if not ok:
            failures.append(("positive/real", qid, text))
    for text in EXTRA_PLACEHOLDERS:
        ok = guard(text)
        print("  %-5s %-22s %r" % ("ok" if ok else "FAIL", "(variant)", text))
        if not ok:
            failures.append(("positive/variant", "(variant)", text))

    print()
    print("--- NEGATIVE: must NOT be classified as placeholder ---")
    for qid, text in real_sub:
        ok = not guard(text)
        print("  %-5s %-28s %dw %r..." % ("ok" if ok else "FAIL", qid, len(text.split()), text[:40]))
        if not ok:
            failures.append(("negative/real", qid, text))
    for name, text in NEGATIVE_CASES:
        ok = not guard(text)
        print("  %-5s %-28s %dw %r..." % ("ok" if ok else "FAIL", name, len(text.split()), text[:40]))
        if not ok:
            failures.append(("negative/" + name, name, text))

    print()
    if failures:
        print("RESULT: FAIL (%d case(s))" % len(failures))
        for kind, qid, text in failures:
            print("  %-26s %-28s %r" % (kind, qid, text[:60]))
        return 1
    print("RESULT: PASS (%d positive + %d negative cases)"
          % (len(real_ph) + len(EXTRA_PLACEHOLDERS), len(real_sub) + len(NEGATIVE_CASES)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
