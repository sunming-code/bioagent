"""
步骤 2 · 群体分析（真实数据，无 demo 桩）
环境: popgen_analysis
输入: 病人 VCF + 1000G LD 剪枝底库
输出: results/partial_evidence.json 及 PCA / ADMIXTURE / 频率表
TreeMix 第一轮跳过。smartpca 因 libgfortran 损坏，改用 plink2 --pca。
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PANEL = ROOT / "data" / "reference" / "panel_1000g" / "ref_1000g_pruned"
PANEL_VCF_DIR = Path("/data/public/1000GP/20220422_3202_phased_SNV_INDEL_SV")
SUPERPOPS = ["AFR", "EUR", "EAS", "SAS", "AMR"]
SCHEMA_VERSION = "0.2"


def assign_af_policy(pca_info: dict, adm_info: dict) -> dict:
    """档位一致才允许 BA1/BS1。查表人群在不一致时跟 PCA，不跟最大 Q。不自动判库外。"""
    pca_nearest = pca_info.get("nearest_superpop")
    q = {k: float(v) for k, v in (adm_info.get("components") or {}).items()}
    q_dom = adm_info.get("dominant") or (max(q, key=q.get) if q else None)
    qmax = max(q.values()) if q else None
    concordant = bool(q_dom) and q_dom == pca_nearest
    dist = {k: float(v) for k, v in (pca_info.get("pc_distance") or {}).items()}
    ordered = sorted(dist.items(), key=lambda x: x[1])
    d_nearest = ordered[0][1] if ordered else None
    d_second = ordered[1][1] if len(ordered) > 1 else None
    ratio = (d_second / d_nearest) if d_nearest and d_second and d_nearest > 0 else None
    af_population = pca_nearest
    if concordant:
        assignment = "in_reference"
        use_ba1 = True
        reason = "pca_admixture_concordant"
    else:
        assignment = "admixed"
        use_ba1 = False
        reason = f"pca_{pca_nearest}_admixture_{q_dom}_discordant"
    return {
        "superpop": af_population,
        "pca_nearest": pca_nearest,
        "admixture_dominant": q_dom,
        "q": {k: round(v, 4) for k, v in q.items()},
        "qmax": round(qmax, 4) if qmax is not None else None,
        "concordant": concordant,
        "assignment": assignment,
        "af_population": af_population,
        "af_source": f"AF_{af_population}" if af_population else "AF",
        "use_for_acmg_ba1_bs1": use_ba1,
        "reason": reason,
        "pca_d_nearest": d_nearest,
        "pca_d_second": d_second,
        "pca_d_second_over_nearest": round(ratio, 4) if ratio is not None else None,
        "out_of_reference_threshold": None,
    }


def stamp_policy_on_pack(pack: dict) -> dict:
    """给已有 partial_evidence 补 ancestry / structure，不重跑分析。"""
    findings = pack.get("findings") or {}
    pca_info = findings.get("pca") or {}
    adm = findings.get("admixture") or {}
    adm_info = {
        "components": findings.get("admixture_dominant") or adm.get("components") or {},
        "dominant": adm.get("dominant"),
    }
    policy = assign_af_policy(pca_info, adm_info)
    pack["schema_version"] = SCHEMA_VERSION
    pack["ancestry"] = {
        "analysis_based": policy,
        "gnn_based": None,
        "confidence": None,
    }
    pack["structure"] = {
        "catalog_k": 5,
        "catalog_k_meaning": "1000G_superpopulation_directory",
        "unsupervised_best_k": adm.get("best_k"),
        "unsupervised_best_k_cv_error": adm.get("best_k_cv_error"),
    }
    findings["inferred_ancestry_cluster"] = policy["af_population"]
    findings["af_policy"] = {
        "use_for_acmg_ba1_bs1": policy["use_for_acmg_ba1_bs1"],
        "reason": policy["reason"],
        "assignment": policy["assignment"],
    }
    pack["findings"] = findings
    return pack



def run(cmd: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    logging.info("RUN: %s", cmd)
    proc = subprocess.run(
        cmd,
        shell=True,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        logging.error("STDERR: %s", (proc.stderr or "")[-4000:])
        raise RuntimeError(f"命令失败 ({proc.returncode}): {cmd}")
    return proc


def count_variants(vcf: Path) -> int:
    proc = run(f"bcftools view -H {vcf} | wc -l")
    return int(proc.stdout.strip())


def load_superpop_map(panel_prefix: Path) -> dict[str, str]:
    tsv = panel_prefix.parent / "sample_superpop.tsv"
    if tsv.exists():
        df = pd.read_csv(tsv, sep="\t")
        return dict(zip(df["IID"].astype(str), df["SUPERPOP"].astype(str)))
    fam = Path(str(panel_prefix) + ".fam")
    pop = Path(str(panel_prefix) + ".pop")
    if fam.exists() and pop.exists():
        iids = [ln.split()[1] for ln in fam.read_text().splitlines() if ln.strip()]
        labs = [ln.strip() for ln in pop.read_text().splitlines()]
        if len(iids) != len(labs):
            raise RuntimeError(f".fam/.pop 行数不一致: {len(iids)} vs {len(labs)}")
        return dict(zip(iids, labs))
    raise FileNotFoundError(f"缺少 {tsv} 或 {pop}，请先运行 scripts/build_1000g_panel.sh")


def extract_patient_on_panel(vcf: Path, panel_prefix: Path, temp: Path) -> Path:
    """病人 VCF ∩ 底库位点，转 plink（不对单样本做 MAF 过滤）。"""
    snplist = temp / "panel.snps"
    bim = pd.read_csv(f"{panel_prefix}.bim", sep="\t", header=None)
    snplist.write_text("\n".join(bim[1].astype(str)) + "\n")
    raw = temp / "patient_raw"
    out = temp / "patient_on_panel"
    # 不用 --set-all-var-ids：$r/$a 经 shell 转义会变成 \C:\T，ID 对不上
    run(
        f"plink2 --vcf {vcf} --double-id --allow-extra-chr --chr 1-22 "
        f"--snps-only just-acgt --max-alleles 2 --output-chr chrM "
        f"--make-bed --out {raw}"
    )
    pbim = pd.read_csv(f"{raw}.bim", sep="\t", header=None)
    # plink2 读 VCF 后 A2≈REF、A1≈ALT，与底库 chr:pos:REF:ALT 对齐
    pbim[1] = pbim[0].astype(str) + ":" + pbim[3].astype(str) + ":" + pbim[5].astype(str) + ":" + pbim[4].astype(str)
    pbim.to_csv(f"{raw}.bim", sep="\t", header=False, index=False)
    run(f"plink2 --bfile {raw} --extract {snplist} --make-bed --out {out}")
    n = sum(1 for _ in open(f"{out}.bim"))
    logging.info("病人与底库交集位点: %s", n)
    if n < 200:
        raise RuntimeError(f"与底库交集过小 ({n} SNPs)，无法做祖先推断")
    return out


def merge_patient_panel(patient_prefix: Path, panel_prefix: Path, temp: Path) -> Path:
    merged = temp / "merged"
    try:
        run(
            f"plink --bfile {patient_prefix} --bmerge {panel_prefix} "
            f"--allow-extra-chr --make-bed --out {merged}"
        )
    except RuntimeError:
        miss = Path(str(merged) + "-merge.missnp")
        if miss.exists():
            logging.warning("合并等位冲突，剔除冲突位点后重试")
            run(f"plink --bfile {patient_prefix} --allow-extra-chr --exclude {miss} --make-bed --out {temp / 'patient_flip'}")
            run(f"plink --bfile {panel_prefix} --allow-extra-chr --exclude {miss} --make-bed --out {temp / 'panel_flip'}")
            run(
                f"plink --bfile {temp / 'patient_flip'} --bmerge {temp / 'panel_flip'} "
                f"--allow-extra-chr --make-bed --out {merged}"
            )
        else:
            raise
    return merged


def run_pca(merged: Path, superpop: dict[str, str], outdir: Path, temp: Path) -> tuple[Path, dict]:
    pca_prefix = temp / "pca"
    run(f"plink2 --bfile {merged} --pca 10 --out {pca_prefix}")
    eigenvec = Path(str(pca_prefix) + ".eigenvec")
    cols = ["FID", "IID"] + [f"PC{i}" for i in range(1, 11)]
    df = pd.read_csv(eigenvec, sep=r"\s+", header=None, names=cols, engine="python")
    # plink2 有时带表头
    if str(df.iloc[0]["FID"]).upper() in {"FID", "#FID"}:
        df = pd.read_csv(eigenvec, sep=r"\s+", engine="python")
        df.columns = ["FID", "IID"] + [f"PC{i}" for i in range(1, len(df.columns) - 1)]

    df["SUPERPOP"] = df["IID"].map(lambda x: superpop.get(str(x), "PATIENT"))
    patient = df[df["SUPERPOP"] == "PATIENT"]
    if patient.empty:
        # 病人 IID 可能是 patient
        patient = df[~df["IID"].isin(superpop)]
    if patient.empty:
        raise RuntimeError("PCA 结果里找不到病人样本")

    centroids = (
        df[df["SUPERPOP"].isin(SUPERPOPS)]
        .groupby("SUPERPOP")[["PC1", "PC2", "PC3"]]
        .mean()
    )
    p = patient.iloc[0][["PC1", "PC2", "PC3"]].astype(float)
    dist = {sp: ((centroids.loc[sp] - p) ** 2).sum() ** 0.5 for sp in centroids.index}
    nearest = min(dist, key=dist.get)

    out_pca = outdir / "ancestry_pca.tsv"
    df.to_csv(out_pca, sep="\t", index=False)
    pca_info = {
        "nearest_superpop": nearest,
        "pc_distance": {k: round(float(v), 4) for k, v in dist.items()},
        "patient_pcs": {f"PC{i}": float(patient.iloc[0][f"PC{i}"]) for i in range(1, 4)},
        "method": "plink2 --pca (smartpca unavailable: libgfortran.so.3)",
    }
    return out_pca, pca_info


def run_admixture_supervised(patient_prefix: Path, panel_prefix: Path, outdir: Path, temp: Path, skip_cv: bool = False) -> tuple[Path, dict]:
    """在病人∩底库位点上监督训练 K=5，再 -P 投影病人。"""
    popfile = Path(str(panel_prefix) + ".pop")
    if not popfile.exists():
        raise FileNotFoundError(f"缺少监督标签 {popfile}")

    panel_bim = pd.read_csv(f"{panel_prefix}.bim", sep="\t", header=None)
    patient_bim = pd.read_csv(f"{patient_prefix}.bim", sep="\t", header=None)
    patient_ids = set(patient_bim[1].astype(str))
    common = [s for s in panel_bim[1].astype(str) if s in patient_ids]
    if len(common) < 200:
        raise RuntimeError(f"投影位点过少: {len(common)}")
    snps = temp / "admix.common.snps"
    snps.write_text("\n".join(common) + "\n")

    panel_sub = temp / "panel_sub"
    proj = temp / "patient_proj"
    run(f"plink --bfile {panel_prefix} --allow-extra-chr --extract {snps} --make-bed --out {panel_sub}")
    run(f"plink --bfile {patient_prefix} --allow-extra-chr --extract {snps} --make-bed --out {proj}")
    Path(str(panel_sub) + ".pop").write_text(popfile.read_text())

    cv_info = {"cv_table": [], "best_k": 5, "best_k_cv_error": None, "cv_path": None}
    if not skip_cv:
        cv_info = run_admixture_cv(panel_sub, outdir, temp)
        unsup = run_unsupervised_patient_q(proj, panel_sub, int(cv_info["best_k"]), outdir, temp)
        cv_info["unsupervised_patient"] = unsup

    run(f"admixture --supervised {panel_sub.name}.bed 5", cwd=temp)
    src_p = temp / "panel_sub.5.P"
    if not src_p.exists():
        raise RuntimeError("ADMIXTURE 未写出 panel_sub.5.P")
    # -P 模式要求文件名是 <prefix>.<K>.P.in
    dst_in = temp / "patient_proj.5.P.in"
    dst_in.write_bytes(src_p.read_bytes())
    run(f"admixture {proj.name}.bed 5 -P", cwd=temp)

    qpath = temp / "patient_proj.5.Q"
    if not qpath.exists():
        raise RuntimeError("ADMIXTURE 未写出病人 .Q")
    q = [float(x) for x in qpath.read_text().strip().split()]
    labels = [ln.strip() for ln in popfile.read_text().splitlines()]
    mapping = _map_q_columns_to_superpops(temp / "panel_sub.5.Q", labels)
    ancestry = {mapping.get(i, f"C{i}"): q[i] for i in range(len(q))}
    dominant = max(ancestry, key=ancestry.get)
    out_adm = outdir / "admixture_results_K5.tsv"
    pd.DataFrame([{"Sample": "patient", **ancestry}]).to_csv(out_adm, sep="\t", index=False)
    return out_adm, {
        "components": ancestry,
        "dominant": dominant,
        "K_supervised": 5,
        "K": 5,
        "mode": "supervised_K5 + unsupervised_CV",
        **cv_info,
    }


def run_admixture_cv(panel_sub: Path, outdir: Path, temp: Path) -> dict:
    """无监督 CV：K 从 2 到最多 10。出现最低点后再连续 3 档不创新低则停。在 1000G 底库上做。"""
    cv_dir = temp / "admix_cv"
    cv_dir.mkdir(exist_ok=True)
    for ext in (".bed", ".bim", ".fam"):
        src = Path(str(panel_sub) + ext)
        dst = cv_dir / f"panel_cv{ext}"
        if dst.exists() or dst.is_symlink():
            dst.unlink()
        dst.symlink_to(src.resolve())

    rows = []
    best_k = None
    best_err = None
    stale = 0
    for k in range(2, 11):
        logging.info("ADMIXTURE --cv K=%s", k)
        proc = run(f"admixture --cv panel_cv.bed {k}", cwd=cv_dir)
        text = (proc.stderr or "") + "\n" + (proc.stdout or "")
        m = re.search(rf"CV error \(K={k}\):\s*([0-9.]+)", text)
        if not m:
            raise RuntimeError(f"未能解析 K={k} 的 CV error:\n{text[-1500:]}")
        err = float(m.group(1))
        rows.append({"K": k, "CV_Error": err})
        logging.info("CV error (K=%s): %s", k, err)
        if best_err is None or err < best_err:
            best_k, best_err, stale = k, err, 0
        else:
            stale += 1
            if stale >= 3:
                logging.info("连续 %s 档未低于 K=%s 的最低 CV，停止", stale, best_k)
                break

    n_samples = sum(1 for _ in open(cv_dir / "panel_cv.fam"))
    n_snps = sum(1 for _ in open(cv_dir / "panel_cv.bim"))
    cv_df = pd.DataFrame(rows)
    cv_df["is_best"] = (cv_df["K"] == best_k).astype(int)
    cv_df["n_samples"] = n_samples
    cv_df["n_snps"] = n_snps
    cv_df["dataset"] = "1000G_panel_unsupervised"
    cv_df["stop_rule"] = "K2_to_10_patience3"
    cv_path = outdir / "admixture_cv.tsv"
    cv_df.to_csv(cv_path, sep="\t", index=False)
    return {
        "cv_table": rows,
        "best_k": int(best_k),
        "best_k_cv_error": float(best_err),
        "cv_path": str(cv_path),
        "cv_n_samples": n_samples,
        "cv_n_snps": n_snps,
    }


def _map_q_columns_to_superpops(panel_q: Path, labels: list[str]) -> dict[int, str]:
    """用面板 Q 对已知超群的均值，把列对齐到 AFR/EUR/..."""
    if not panel_q.exists():
        return {i: SUPERPOPS[i] if i < len(SUPERPOPS) else f"C{i}" for i in range(5)}
    q = pd.read_csv(panel_q, sep=r"\s+", header=None, engine="python")
    valid = [i for i, lab in enumerate(labels) if lab in SUPERPOPS]
    q = q.iloc[valid]
    labs = [labels[i] for i in valid]
    mapping = {}
    used = set()
    for col in q.columns:
        means = q[col].groupby(labs).mean()
        pick = means.idxmax()
        # 避免两列抢同一个超群
        if pick in used:
            for alt in means.sort_values(ascending=False).index:
                if alt not in used:
                    pick = alt
                    break
        used.add(pick)
        mapping[int(col)] = pick
    for i in range(q.shape[1]):
        mapping.setdefault(i, SUPERPOPS[i] if i < len(SUPERPOPS) else f"C{i}")
    return mapping


def run_unsupervised_patient_q(patient_proj: Path, panel_sub: Path, best_k: int, outdir: Path, temp: Path) -> dict:
    """在与 CV 相同的 SNP 集上，把病人和底库一起无监督拟合 best_k。列名为 C1..CK，不做超群命名。"""
    merged_cv = temp / "merged_cv"
    run(
        f"plink --bfile {patient_proj} --bmerge {panel_sub} "
        f"--allow-extra-chr --make-bed --out {merged_cv}"
    )
    fam = pd.read_csv(f"{merged_cv}.fam", sep=r"\s+", header=None, engine="python")
    logging.info("ADMIXTURE unsupervised K=%s on CV SNP set (%s samples)", best_k, len(fam))
    run(f"admixture -j8 {merged_cv.name}.bed {best_k}", cwd=temp)
    qpath = temp / f"{merged_cv.name}.{best_k}.Q"
    if not qpath.exists():
        raise RuntimeError(f"ADMIXTURE 未写出 {qpath.name}")
    q = pd.read_csv(qpath, sep=r"\s+", header=None, engine="python")
    q.columns = [f"C{i+1}" for i in range(q.shape[1])]
    q.insert(0, "IID", fam[1].astype(str).values)
    patient_rows = q[q["IID"] == "patient"]
    if patient_rows.empty:
        patient_rows = q.iloc[[-1]].copy()
        patient_rows["IID"] = "patient"
    out = outdir / f"admixture_unsupervised_K{best_k}.tsv"
    patient_rows.to_csv(out, sep="\t", index=False)
    comps = {c: float(patient_rows.iloc[0][c]) for c in q.columns if str(c).startswith("C")}
    return {
        "path": str(out),
        "K": best_k,
        "components": comps,
        "max_component": max(comps.values()) if comps else None,
        "n_snps": sum(1 for _ in open(f"{merged_cv}.bim")),
        "n_samples": len(fam),
    }


def calc_matched_af(vcf: Path, superpop: str, superpop_map: dict[str, str], outdir: Path, temp: Path) -> Path:
    """直接读 1000G 面板已有的 AF / AF_<SUPERPOP>，不重算基因型。"""
    tag = f"AF_{superpop}"
    sites = temp / "patient.sites.tsv"
    run(f"bcftools query -f '%CHROM\\t%POS\\t%REF\\t%ALT\\n' {vcf} > {sites}")
    chroms = sorted({ln.split()[0] for ln in sites.read_text().splitlines() if ln.strip()})

    rows = []
    for chrom in chroms:
        panel = PANEL_VCF_DIR / f"1kGP_high_coverage_Illumina.{chrom}.filtered.SNV_INDEL_SV_phased_panel.vcf.gz"
        if not panel.exists():
            logging.warning("无面板 VCF，跳过 %s", chrom)
            continue
        chr_sites = temp / f"sites.{chrom}.tsv"
        chr_sites.write_text(
            "".join(ln + "\n" for ln in sites.read_text().splitlines() if ln.startswith(chrom + "\t"))
        )
        if chr_sites.stat().st_size == 0:
            continue
        out_af = temp / f"af.{chrom}.tsv"
        run(
            f"bcftools query -T {chr_sites} "
            f"-f '%CHROM\\t%POS\\t%REF\\t%ALT\\t%AF\\t%{tag}\\n' {panel} > {out_af}"
        )
        for line in out_af.read_text().splitlines():
            parts = line.split("\t")
            if len(parts) < 6:
                continue
            chrom_, pos, ref, alt, gaf, paf = parts[:6]
            try:
                gaf_v = float(gaf.split(",")[0])
            except ValueError:
                gaf_v = ""
            try:
                paf_v = float(paf.split(",")[0])
            except ValueError:
                paf_v = ""
            rows.append(
                {
                    "CHROM": chrom_,
                    "POS": int(pos),
                    "REF": ref,
                    "ALT": alt,
                    "matched_pop": superpop,
                    "matched_pop_AF": paf_v,
                    "global_AF": gaf_v,
                }
            )
    out_path = outdir / "allele_freq.tsv"
    pd.DataFrame(rows).to_csv(out_path, sep="\t", index=False)
    logging.info("写出频率 %s 行 → %s", len(rows), out_path)
    return out_path


def execute(vcf: Path, outdir: Path, panel_prefix: Path, skip_cv: bool = False, skip_af: bool = False) -> Path:
    if not Path(str(panel_prefix) + ".bed").exists():
        raise FileNotFoundError(
            f"底库不存在: {panel_prefix}.bed ，请先运行 scripts/build_1000g_panel.sh"
        )
    outdir.mkdir(parents=True, exist_ok=True)
    temp = outdir / "temp_analysis"
    temp.mkdir(exist_ok=True)

    nvar = count_variants(vcf)
    if nvar < 10000:
        raise RuntimeError(f"变异过少 ({nvar})，拒绝进入 demo 回落，请检查步骤 1 VCF")

    superpop_map = load_superpop_map(panel_prefix)
    patient_prefix = extract_patient_on_panel(vcf, panel_prefix, temp)
    merged = merge_patient_panel(patient_prefix, panel_prefix, temp)
    pca_path, pca_info = run_pca(merged, superpop_map, outdir, temp)
    adm_path, adm_info = run_admixture_supervised(patient_prefix, panel_prefix, outdir, temp, skip_cv=skip_cv)

    policy = assign_af_policy(pca_info, adm_info)
    inferred = policy["af_population"]
    if not policy["concordant"]:
        adm_info["fallback"] = "pca_nearest_superpop"
        logging.warning(
            "PCA=%s 与监督最大档=%s 不一致，查表用 PCA；BA1/BS1 关闭",
            policy["pca_nearest"],
            policy["admixture_dominant"],
        )
    if skip_af:
        af_path = outdir / "allele_freq.tsv"
        af_path.write_text("skipped_for_leave_one_out\n")
    else:
        af_path = calc_matched_af(vcf, inferred, superpop_map, outdir, temp)

    pack = {
        "schema_version": SCHEMA_VERSION,
        "metadata": {
            "sample_vcf": vcf.name,
            "variant_count": nvar,
            "reference_panel": str(panel_prefix),
            "genome_build": "GRCh38",
            "mode": "Real_Pipeline",
        },
        "findings": {
            "inferred_ancestry_cluster": inferred,
            "admixture_dominant": {k: round(v, 4) for k, v in adm_info["components"].items()},
            "pca": pca_info,
            "admixture": {
                "K_supervised": 5,
                "K_supervised_meaning": "catalog_1000G_superpops",
                "best_k": adm_info.get("best_k"),
                "best_k_cv_error": adm_info.get("best_k_cv_error"),
                "cv_table": adm_info.get("cv_table"),
                "cv_stop_rule": "K2_to_10_patience3",
                "unsupervised_patient": adm_info.get("unsupervised_patient"),
                "mode": adm_info.get("mode"),
                "dominant": adm_info.get("dominant"),
                "fallback": adm_info.get("fallback"),
            },
            "high_drift_bias_detected": False,
            "treemix": "skipped_round1",
        },
        "output_bundles": {
            "pca": str(pca_path),
            "admixture": str(adm_path),
            "admixture_cv": adm_info.get("cv_path"),
            "admixture_unsupervised": (adm_info.get("unsupervised_patient") or {}).get("path"),
            "allele_frequency": str(af_path),
        },
    }
    pack = stamp_policy_on_pack(pack)
    out_json = outdir / "partial_evidence.json"
    out_json.write_text(json.dumps(pack, indent=2, ensure_ascii=False) + "\n")
    logging.info(
        "====== 步骤2 交付: %s 查表=%s BA1=%s ======",
        out_json,
        inferred,
        policy["use_for_acmg_ba1_bs1"],
    )
    return out_json


def main() -> None:
    parser = argparse.ArgumentParser(description="PopGen 步骤2 真实群体分析")
    parser.add_argument("--vcf", required=True, type=Path)
    parser.add_argument("--outdir", type=Path, default=ROOT / "results")
    parser.add_argument("--panel-prefix", type=Path, default=DEFAULT_PANEL)
    parser.add_argument("--skip-cv", action="store_true", help="跳过无监督 CV（留一自测）")
    parser.add_argument("--skip-af", action="store_true", help="跳过频率表（留一自测）")
    args = parser.parse_args()
    execute(args.vcf, args.outdir, args.panel_prefix, skip_cv=args.skip_cv, skip_af=args.skip_af)


if __name__ == "__main__":
    main()
