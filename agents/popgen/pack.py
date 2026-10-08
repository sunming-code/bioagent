"""把步骤 2 的 partial_evidence 汇总成 e-Gene 交付目录（schema 1.0）。不重跑分析。"""
from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCHEMA_PATH = ROOT / "contracts" / "evidence_pack.schema.json"
SCHEMA_VERSION = "1.0"
CATALOG_POPS = ["AFR", "EUR", "EAS", "SAS", "AMR"]

USAGE_MUST = [
    "Look up matched-population AF only in allele_freq.tsv using join_key CHROM+POS+REF+ALT (GRCh38, contig like chr1).",
    "The lookup population is ancestry.analysis_based.af_population. Do not use admixture_dominant, max Q, or ancestry.gnn_based.predicted to choose AF_*.",
    "Apply BA1/BS1 from matched_pop_AF only if ancestry.analysis_based.use_for_acmg_ba1_bs1 is true.",
    "If use_for_acmg_ba1_bs1 is false, matched_pop_AF and global_AF are informational only; they must not be used as stand-alone or strong benign evidence.",
    "assignment=admixed means the matched population is not locked; it does not mean interpret as AFR (or any Q-max population).",
    "If ancestry.gnn_based is non-null, treat it as supplementary ancestry evidence only. BA1/BS1 still follows analysis_based.use_for_acmg_ba1_bs1.",
]

USAGE_MUST_NOT = [
    "Do not treat q.AFR (or any max-Q bin) as the ancestry call when concordant is false.",
    "Do not use structure.unsupervised_best_k or unsupervised C1–Ck labels as af_population; there is no AF_K9 table.",
    "Do not ingest allele_freq.tsv as a pathogenic-variant list; it is an AF annotation table for variants present in the patient VCF.",
    "Do not embed or require the 800k+ AF rows inside evidence_pack.json.",
    "Do not use ancestry.gnn_based.predicted to override af_population or to retarget AF_AMR/AF_AFR/AF_*.",
    "If gnn_based.concordant_with_pca3 is false, do not treat GNN predicted as a locked ancestry call.",
    "If gnn_based.usable_for_lookup is false, do not use GNN predicted or confidence to choose AF_*.",
]


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _count_tsv_rows(path: Path) -> int:
    with path.open() as fh:
        header = fh.readline()
        if not header:
            return 0
        return sum(1 for _ in fh)


def _link_or_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def _gnn_fields(gnn: dict) -> tuple[dict | None, float | None]:
    """把 decide.py 输出收成 schema 的 gnn_based；桩或缺失则 (None, None)。"""
    if not gnn or gnn.get("status") in {None, "SKELETON"}:
        return None, None
    if gnn.get("status") not in {"OK", "ok"}:
        return None, None
    q = gnn.get("ancestry") or {}
    if not q:
        return None, gnn.get("confidence")
    predicted = gnn.get("predicted") or max(q, key=q.get)
    qmax = gnn.get("confidence")
    if qmax is None and q:
        qmax = max(q.values())
    gnn_based = {
        "predicted": predicted,
        "q": {k: float(v) for k, v in q.items()},
        "qmax": float(qmax) if qmax is not None else None,
        "subpop_predicted": gnn.get("subpop_predicted"),
        "pca3_nearest": gnn.get("pca3_nearest"),
        "concordant_with_pca3": gnn.get("gnn_pca_concordant"),
        "note": gnn.get("note"),
        "n_snps": gnn.get("n_snps") or gnn.get("n_snps_observed"),
        "method": gnn.get("method"),
        "inference": gnn.get("inference"),
        "usable_for_lookup": bool(gnn.get("usable_for_lookup")) and gnn.get("gnn_pca_concordant") is True,
        "discordance_reason": gnn.get("discordance_reason"),
    }
    return gnn_based, gnn.get("confidence")


def build_evidence_pack(
    partial_evidence: Path,
    gnn_decision: Path | None,
    pack_dir: Path,
    results_dir: Path,
    sample_alias: str | None = "HG002",
) -> Path:
    """写出 pack_dir/evidence_pack.json，并把 allele_freq.tsv 放到同一目录。"""
    analysis = _load_json(partial_evidence)
    gnn = _load_json(gnn_decision) if gnn_decision else {}
    ancestry_in = analysis.get("ancestry") or {}
    based = ancestry_in.get("analysis_based")
    if not based:
        raise RuntimeError(f"{partial_evidence} 缺少 ancestry.analysis_based，无法交付")

    af_src = results_dir / "allele_freq.tsv"
    if not af_src.exists():
        raise FileNotFoundError(f"缺少频率表: {af_src}")
    n_rows = _count_tsv_rows(af_src)

    pack_dir.mkdir(parents=True, exist_ok=True)
    _link_or_copy(af_src, pack_dir / "allele_freq.tsv")

    gnn_based, gnn_conf = _gnn_fields(gnn)
    if gnn_based is not None and based.get("assignment") != "in_reference":
        gnn_based["usable_for_lookup"] = False
        if not gnn_based.get("discordance_reason"):
            gnn_based["discordance_reason"] = (
                f"assignment_{based.get('assignment')}; do not lock lookup; "
                "analysis_based.af_population stays authoritative"
            )
    meta = dict(analysis.get("metadata") or {})
    meta["sample_id"] = meta.get("sample_id") or "patient"
    meta["sample_alias"] = sample_alias
    meta["reference_panel"] = "1kGP_high_coverage_GRCh38_n3202"
    meta.pop("reference_panel_path", None)
    # 不把本机绝对路径交给下游
    if isinstance(meta.get("reference_panel"), str) and meta["reference_panel"].startswith("/"):
        meta["reference_panel"] = "1kGP_high_coverage_GRCh38_n3202"

    structure = dict(analysis.get("structure") or {})
    structure.setdefault("catalog_k", 5)
    structure.setdefault("catalog_k_meaning", "1000G_superpopulation_directory")
    structure["catalog_pops"] = CATALOG_POPS
    structure["unsupervised_note"] = (
        "unsupervised_best_k describes panel substructure only; "
        "it is not a frequency-population name and has no AF_* column."
    )

    unsup = ((analysis.get("findings") or {}).get("admixture") or {}).get("unsupervised_patient") or {}
    files = {
        "allele_frequency": "allele_freq.tsv",
        "interface": "INTERFACE.md",
        "admixture_supervised": "../admixture_results_K5.tsv",
        "admixture_cv": "../admixture_cv.tsv",
        "admixture_unsupervised": "../admixture_unsupervised_K9.tsv",
        "pca": "../ancestry_pca.tsv",
        "patient_vcf": "../patient.vcf.gz",
        "partial_evidence": "../partial_evidence.json",
        "gnn_decision": "../gnn_decision.json" if gnn_based else None,
    }

    pack = {
        "schema_version": SCHEMA_VERSION,
        "producer": {
            "agent": "popgen_agent",
            "pack_built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "metadata": {
            "sample_id": meta["sample_id"],
            "sample_alias": meta.get("sample_alias"),
            "sample_vcf": meta.get("sample_vcf", "patient.vcf.gz"),
            "variant_count": meta.get("variant_count"),
            "genome_build": "GRCh38",
            "reference_panel": "1kGP_high_coverage_GRCh38_n3202",
            "mode": "Real_Pipeline",
        },
        "ancestry": {
            "analysis_based": based,
            "gnn_based": gnn_based,
            "confidence": gnn_conf,
        },
        "structure": {
            "catalog_k": 5,
            "catalog_k_meaning": structure["catalog_k_meaning"],
            "catalog_pops": CATALOG_POPS,
            "unsupervised_best_k": structure.get("unsupervised_best_k"),
            "unsupervised_best_k_cv_error": structure.get("unsupervised_best_k_cv_error"),
            "unsupervised_note": structure["unsupervised_note"],
        },
        "allele_frequency": {
            "path": "allele_freq.tsv",
            "format": "tsv",
            "n_rows": n_rows,
            "genome_build": "GRCh38",
            "join_key": ["CHROM", "POS", "REF", "ALT"],
            "columns": [
                "CHROM",
                "POS",
                "REF",
                "ALT",
                "matched_pop",
                "matched_pop_AF",
                "global_AF",
            ],
            "matched_pop": based.get("af_population"),
            "matched_pop_must_equal": "ancestry.analysis_based.af_population",
            "note": "Rows are variants present in the patient VCF; homozygous-reference fills are not included.",
        },
        "usage": {"must": USAGE_MUST, "must_not": USAGE_MUST_NOT},
        "qc": {
            "n_aim_intersect": unsup.get("n_snps") or (gnn_based or {}).get("n_snps"),
            "snpEff": "off",
            "vqsr": "off",
            "capture_bed": "not_provided",
        },
        "files": files,
    }

    if pack["allele_frequency"]["matched_pop"] != based.get("af_population"):
        raise RuntimeError("allele_frequency.matched_pop 必须等于 af_population")

    pack_path = pack_dir / "evidence_pack.json"
    pack_path.write_text(json.dumps(pack, indent=2, ensure_ascii=False) + "\n")
    write_interface_md(pack_dir, pack)
    root_copy = results_dir / "evidence_pack.json"
    if root_copy.resolve() != pack_path.resolve():
        _link_or_copy(pack_path, root_copy)
    if gnn_based:
        analysis["ancestry"] = dict(analysis.get("ancestry") or {})
        analysis["ancestry"]["gnn_based"] = gnn_based
        analysis["ancestry"]["confidence"] = gnn_conf
        partial_evidence.write_text(json.dumps(analysis, indent=2, ensure_ascii=False) + "\n")
    logging.info("写出交付包 %s", pack_path)
    return pack_path


def write_interface_md(pack_dir: Path, pack: dict) -> Path:
    based = pack["ancestry"]["analysis_based"]
    gnn = pack["ancestry"].get("gnn_based")
    ba1 = based["use_for_acmg_ba1_bs1"]
    if ba1:
        ba1_zh = (
            f"- 因此：可以用 `matched_pop_AF` 按你们 SOP 评估 BA1/BS1（查表人群 `{based['af_population']}`）。\n"
            "- 仍禁止改去用最大 Q 档或 GNN predicted 换人群。"
        )
    else:
        ba1_zh = (
            "- 因此：**禁止**用 `matched_pop_AF` 打 BA1/BS1。表仍可给人看，也可作罕见程度参考，但不能一票良性。\n"
            "- 禁止改去查 AFR、GNN predicted，或任何最大 Q 档的频率。"
        )
    if gnn:
        gnn_zh = f"""
## GNN（步骤 3）

- `gnn_based.predicted` = `{gnn.get("predicted")}`；`confidence` = {pack["ancestry"].get("confidence")}
- 同图 PCA3 最近档 = `{gnn.get("pca3_nearest")}`；`concordant_with_pca3` = **{str(gnn.get("concordant_with_pca3")).lower()}**
- `usable_for_lookup` = **{str(gnn.get("usable_for_lookup")).lower()}**
- `{gnn.get("note") or "无不一致标记"}`
- `{gnn.get("discordance_reason") or ""}`
- **禁止**用 GNN predicted 改查表人群。查表仍是 `analysis_based.af_population`。
"""
        missing = """## 本轮没有的字段

- 无 snpEff 基因后果、无 VQSR、无捕获 BED
- 频率表不含 BAM 补上的 0/0 位点
"""
    else:
        gnn_zh = ""
        missing = """## 本轮没有的字段

- `ancestry.gnn_based` / `confidence` = null（步骤 3 未写入）
- 无 snpEff 基因后果、无 VQSR、无捕获 BED
- 频率表不含 BAM 补上的 0/0 位点
"""
    text = f"""# PopGen → e-Gene 接口说明（schema {SCHEMA_VERSION}）

平台接入：读取本目录的 `evidence_pack.json`，再用同目录 `allele_freq.tsv` 按变异连接。不要解析步骤 2 的 `findings` 杂项。

## 必读文件

| 文件 | 作用 |
|---|---|
| `evidence_pack.json` | 祖先结论、查表人群、BA1 权限、用法硬规则 |
| `allele_freq.tsv` | 每个病人 VCF 变异的匹配人群 AF + 全球 AF |

连接键：`CHROM`, `POS`, `REF`, `ALT`（GRCh38，`chr1` 形式）。不要只按位置连接。

## 本样本（{pack["metadata"].get("sample_alias") or pack["metadata"]["sample_id"]}）必须执行的行为

- 查表人群：`{based["af_population"]}`（`{based["af_source"]}`）
- `use_for_acmg_ba1_bs1` = **{str(ba1).lower()}**
- `assignment` = `{based["assignment"]}`；`reason` = `{based["reason"]}`
- PCA 最近档 = `{based["pca_nearest"]}`；监督最大档 = `{based["admixture_dominant"]}`。**最大 Q 不是祖先结论。**
{ba1_zh}
- `structure.unsupervised_best_k` = {pack["structure"].get("unsupervised_best_k")} 只描述 1000G 底库细结构，没有 `AF_K9`。
{gnn_zh}
## `usage.must` / `usage.must_not`

以 JSON 里的英文条款为准（机器可读）。上文是同一规则的中文说明。

{missing}
e-Gene 按本包调整即可；字段以 schema `contracts/evidence_pack.schema.json` 锁定。
"""
    path = pack_dir / "INTERFACE.md"
    path.write_text(text)
    return path


def validate_pack(pack_path: Path, schema_path: Path = SCHEMA_PATH) -> None:
    pack = json.loads(pack_path.read_text())
    schema = json.loads(schema_path.read_text())
    try:
        import jsonschema
    except ImportError:
        jsonschema = None
    if jsonschema:
        jsonschema.validate(pack, schema)
        logging.info("jsonschema 校验通过: %s", pack_path)
        return
    missing = [k for k in schema.get("required", []) if k not in pack]
    if missing:
        raise RuntimeError(f"缺少顶层字段: {missing}")
    based = pack["ancestry"]["analysis_based"]
    for k in (
        "af_population",
        "use_for_acmg_ba1_bs1",
        "assignment",
        "reason",
        "pca_nearest",
        "admixture_dominant",
    ):
        if k not in based:
            raise RuntimeError(f"缺少 ancestry.analysis_based.{k}")
    af_tsv = pack_path.parent / pack["allele_frequency"]["path"]
    if not af_tsv.exists():
        raise FileNotFoundError(af_tsv)
    if pack["allele_frequency"]["matched_pop"] != based["af_population"]:
        raise RuntimeError("matched_pop 与 af_population 不一致")
    gnn = pack["ancestry"].get("gnn_based")
    if gnn == {}:
        raise RuntimeError("gnn_based 不得用空对象 {}；未跑请用 null")
    if isinstance(gnn, dict):
        for k in ("predicted", "q", "qmax"):
            if k not in gnn:
                raise RuntimeError(f"缺少 ancestry.gnn_based.{k}")
    logging.info("轻量校验通过（未安装 jsonschema）: %s", pack_path)
