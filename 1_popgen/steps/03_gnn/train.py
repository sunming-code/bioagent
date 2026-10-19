#!/usr/bin/env python3
"""1000G 半监督 GAT 训练 + 与 PCA / ADMIXTURE-NNLS baseline 交叉验证。"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from sklearn.model_selection import StratifiedKFold

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gnn_core import (
    ADMIXED_SUBPOPS,
    DEFAULT_PANEL,
    EASY_LOO,
    ROOT,
    SAMPLES_INFO,
    SUPERPOPS,
    FeaturePack,
    admixture_nnls,
    accuracy,
    build_similarity_graph,
    extract_panel_features,
    fit_temperature,
    metrics_block,
    pca_nearest,
    predict_logits,
    softmax_np,
    standardize_pcs,
    train_gat,
    transform_pca,
)

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
logger = logging.getLogger("train")

SLICES = ["all", "continental", "admixed", "amr", "afr_admixed"]


def _device() -> str:
    return "cuda" if torch.cuda.is_available() else "cpu"


def _slice_idx(subpops: np.ndarray, test_idx: np.ndarray, name: str) -> np.ndarray:
    sub = subpops[test_idx]
    if name == "all":
        m = np.ones(len(sub), dtype=bool)
    elif name == "continental":
        m = np.array([s not in ADMIXED_SUBPOPS for s in sub])
    elif name == "admixed":
        m = np.array([s in ADMIXED_SUBPOPS for s in sub])
    elif name == "amr":
        m = np.array([s in {"MXL", "PUR", "CLM", "PEL"} for s in sub])
    elif name == "afr_admixed":
        m = np.array([s in {"ASW", "ACB"} for s in sub])
    else:
        raise KeyError(name)
    return test_idx[m]


def _method_metrics(pred: np.ndarray, probs: np.ndarray, y: np.ndarray, idx: np.ndarray) -> dict:
    return metrics_block(probs[idx], y[idx], pred[idx])


def run_cv(pack, n_splits: int, epochs: int, k: int, seed: int, device: str, lowq_frac: float) -> dict:
    n = len(pack.iids)
    y = pack.y_super
    y_sub = pack.y_sub
    subpops = np.array(pack.sub_classes)[y_sub]
    n_super, n_sub = len(SUPERPOPS), len(pack.sub_classes)
    skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=seed)

    gnn_logits = np.zeros((n, n_super), dtype=np.float32)
    gnn_sub_pred = np.full(n, -1, dtype=int)
    pca3_pred = np.full(n, -1, dtype=int)
    pca20_pred = np.full(n, -1, dtype=int)
    pca3_probs = np.zeros((n, n_super), dtype=np.float64)
    pca20_probs = np.zeros((n, n_super), dtype=np.float64)
    adm_pred = np.full(n, -1, dtype=int)
    adm_q = np.zeros((n, n_super), dtype=np.float64)
    pca_sub_pred = np.full(n, -1, dtype=int)
    lowq_gnn_pred = np.full(n, -1, dtype=int)
    lowq_pca_pred = np.full(n, -1, dtype=int)
    lowq_adm_pred = np.full(n, -1, dtype=int)
    lowq_gnn_probs = np.zeros((n, n_super), dtype=np.float64)
    lowq_pca_probs = np.zeros((n, n_super), dtype=np.float64)
    lowq_adm_q = np.zeros((n, n_super), dtype=np.float64)

    rng = np.random.default_rng(seed)
    n_snps = pack.geno.shape[1]
    n_keep_lowq = max(200, int(n_snps * lowq_frac))

    for fold, (tr, te) in enumerate(skf.split(np.zeros(n), y), start=1):
        logger.info("==== fold %s train=%s test=%s ====", fold, len(tr), len(te))
        pcs_raw_tr, mean, comp = _fit_pca_local(pack.geno[tr], pack.pcs.shape[1])
        pcs_raw_te = transform_pca(pack.geno[te], mean, comp)
        pcs_raw = np.zeros((n, pcs_raw_tr.shape[1]), dtype=np.float32)
        pcs_raw[tr] = pcs_raw_tr
        pcs_raw[te] = pcs_raw_te
        pcs, sc_mean, sc_std = standardize_pcs(pcs_raw[tr])
        pcs_all = np.zeros_like(pcs_raw)
        pcs_all[tr] = pcs
        pcs_all[te] = ((pcs_raw[te] - sc_mean) / sc_std).astype(np.float32)

        fp = FeaturePack(
            pcs=pcs_all,
            iids=pack.iids,
            y_super=pack.y_super,
            y_sub=pack.y_sub,
            snp_ids=pack.snp_ids,
            geno=pack.geno,
            pca_mean=mean,
            pca_components=comp,
            pc_scaler_mean=sc_mean,
            pc_scaler_std=sc_std,
            sub_classes=pack.sub_classes,
            k=k,
        )
        data = build_similarity_graph(fp, k=k)
        n_val = max(1, int(0.15 * len(tr)))
        perm = rng.permutation(tr)
        va, tr_fit = perm[:n_val], perm[n_val:]
        model = train_gat(data, tr_fit, va, n_super, n_sub, epochs=epochs, device=device, seed=seed + fold)
        logits_s, logits_b = predict_logits(model, data, device)
        gnn_logits[te] = logits_s[te]
        gnn_sub_pred[te] = logits_b[te].argmax(axis=1)

        pca3_pred[te], pca3_fold_p = pca_nearest(pcs_raw[tr], y[tr], pcs_raw[te], n_pc=3, n_classes=n_super)
        pca20_pred[te], pca20_fold_p = pca_nearest(pcs_raw[tr], y[tr], pcs_raw[te], n_pc=pcs_raw.shape[1], n_classes=n_super)
        pca_sub_pred[te], _ = pca_nearest(pcs_raw[tr], y_sub[tr], pcs_raw[te], n_pc=min(10, pcs_raw.shape[1]), n_classes=n_sub)
        adm_pred[te], adm_q[te] = admixture_nnls(pack.geno[tr], y[tr], pack.geno[te], n_super)
        pca3_probs[te] = pca3_fold_p
        pca20_probs[te] = pca20_fold_p

        keep = rng.choice(n_snps, size=n_keep_lowq, replace=False)
        g_tr, g_te = pack.geno[tr][:, keep], pack.geno[te][:, keep]
        pcs_lq_tr, mean_lq, comp_lq = _fit_pca_local(g_tr, min(20, pack.pcs.shape[1]))
        pcs_lq_te = transform_pca(g_te, mean_lq, comp_lq)
        pcs_lq = np.zeros((n, pcs_lq_tr.shape[1]), dtype=np.float32)
        pcs_lq[tr] = pcs_lq_tr
        pcs_lq[te] = pcs_lq_te
        pcs_lq_std, lq_mean, lq_std = standardize_pcs(pcs_lq[tr])
        pcs_lq_all = np.zeros_like(pcs_lq)
        pcs_lq_all[tr] = pcs_lq_std
        pcs_lq_all[te] = ((pcs_lq[te] - lq_mean) / lq_std).astype(np.float32)
        fp_lq = FeaturePack(
            pcs=pcs_lq_all,
            iids=pack.iids,
            y_super=pack.y_super,
            y_sub=pack.y_sub,
            snp_ids=pack.snp_ids,
            geno=pack.geno,
            pca_mean=mean_lq,
            pca_components=comp_lq,
            pc_scaler_mean=lq_mean,
            pc_scaler_std=lq_std,
            sub_classes=pack.sub_classes,
            k=k,
        )
        data_lq = build_similarity_graph(fp_lq, k=k)
        model_lq = train_gat(
            data_lq, tr_fit, va, n_super, n_sub, epochs=max(80, epochs // 2), device=device, seed=seed + 100 + fold
        )
        lq_logits, _ = predict_logits(model_lq, data_lq, device)
        lowq_gnn_pred[te] = lq_logits[te].argmax(axis=1)
        lowq_gnn_probs[te] = softmax_np(lq_logits[te], T=1.0)
        lowq_pca_pred[te], lowq_pca_probs[te] = pca_nearest(pcs_lq[tr], y[tr], pcs_lq[te], n_pc=3, n_classes=n_super)
        lowq_adm_pred[te], lowq_adm_q[te] = admixture_nnls(g_tr, y[tr], g_te, n_super)

    T = fit_temperature(torch.tensor(gnn_logits), torch.tensor(y, dtype=torch.long))
    logger.info("temperature = %.4f", T)
    gnn_probs = softmax_np(gnn_logits, T=T)
    gnn_pred = gnn_probs.argmax(axis=1)

    rows = []
    summary = {"temperature": round(T, 4), "n": n, "n_splits": n_splits, "slices": {}, "low_quality": {}, "fine_scale": {}}
    for sl in SLICES:
        idx = _slice_idx(subpops, np.arange(n), sl)
        block = {
            "gnn": _method_metrics(gnn_pred, gnn_probs, y, idx),
            "pca3": _method_metrics(pca3_pred, pca3_probs, y, idx),
            "pca20": _method_metrics(pca20_pred, pca20_probs, y, idx),
            "admixture_nnls": _method_metrics(adm_pred, adm_q, y, idx),
        }
        summary["slices"][sl] = block
        for method, m in block.items():
            rows.append({"slice": sl, "method": method, **m})
        logger.info(
            "%s  GNN acc=%.3f ece=%.3f | PCA3 acc=%.3f | ADM acc=%.3f",
            sl,
            block["gnn"]["acc"],
            block["gnn"]["ece"],
            block["pca3"]["acc"],
            block["admixture_nnls"]["acc"],
        )

    idx_all = np.arange(n)
    summary["low_quality"] = {
        "snp_keep_frac": lowq_frac,
        "gnn": _method_metrics(lowq_gnn_pred, lowq_gnn_probs, y, idx_all),
        "pca3": _method_metrics(lowq_pca_pred, lowq_pca_probs, y, idx_all),
        "admixture_nnls": _method_metrics(lowq_adm_pred, lowq_adm_q, y, idx_all),
        "admixed": {
            "gnn": _method_metrics(lowq_gnn_pred, lowq_gnn_probs, y, _slice_idx(subpops, idx_all, "admixed")),
            "pca3": _method_metrics(lowq_pca_pred, lowq_pca_probs, y, _slice_idx(subpops, idx_all, "admixed")),
            "admixture_nnls": _method_metrics(lowq_adm_pred, lowq_adm_q, y, _slice_idx(subpops, idx_all, "admixed")),
        },
    }
    summary["fine_scale"] = {
        "n_classes": n_sub,
        "gnn_acc": round(accuracy(gnn_sub_pred, y_sub), 4),
        "pca10_centroid_acc": round(accuracy(pca_sub_pred, y_sub), 4),
        "continental_only": {
            "gnn_acc": round(accuracy(gnn_sub_pred[_slice_idx(subpops, idx_all, "continental")], y_sub[_slice_idx(subpops, idx_all, "continental")]), 4),
            "pca10_centroid_acc": round(accuracy(pca_sub_pred[_slice_idx(subpops, idx_all, "continental")], y_sub[_slice_idx(subpops, idx_all, "continental")]), 4),
        },
    }

    easy_rows = []
    for iid, (sub, true) in EASY_LOO.items():
        hit = np.where(pack.iids == iid)[0]
        if not len(hit):
            continue
        i = int(hit[0])
        easy_rows.append(
            {
                "IID": iid,
                "SUBPOP": sub,
                "TRUE": true,
                "GNN": SUPERPOPS[int(gnn_pred[i])],
                "GNN_pmax": round(float(gnn_probs[i].max()), 4),
                "PCA3": SUPERPOPS[int(pca3_pred[i])],
                "ADMIXTURE_NNLS": SUPERPOPS[int(adm_pred[i])],
                "ADM_qmax": round(float(adm_q[i].max()), 4),
            }
        )
    summary["easy_loo"] = easy_rows

    summary["win"] = _declare_win(summary)
    pred_df = pd.DataFrame(
        {
            "IID": pack.iids,
            "SUBPOP": subpops,
            "TRUE": [SUPERPOPS[i] for i in y],
            "GNN": [SUPERPOPS[i] for i in gnn_pred],
            "GNN_pmax": gnn_probs.max(axis=1),
            "PCA3": [SUPERPOPS[i] for i in pca3_pred],
            "PCA20": [SUPERPOPS[i] for i in pca20_pred],
            "ADMIXTURE_NNLS": [SUPERPOPS[i] for i in adm_pred],
            "ADM_qmax": adm_q.max(axis=1),
            "GNN_SUB": [pack.sub_classes[i] for i in gnn_sub_pred],
            "TRUE_SUB": subpops,
        }
    )
    return summary, pred_df, T, pd.DataFrame(rows)


def _fit_pca_local(geno, n_pcs):
    from gnn_core import fit_pca

    return fit_pca(geno, n_pcs)


def _declare_win(summary: dict) -> dict:
    """定位 A：难样本上准确率或 ECE 打赢 PCA3 与 ADMIXTURE。"""
    checks = {}
    for sl in ("admixed", "amr", "afr_admixed"):
        g, p, a = (summary["slices"][sl][m] for m in ("gnn", "pca3", "admixture_nnls"))
        acc_win = g["acc"] >= max(p["acc"], a["acc"])
        ece_win = g["ece"] <= min(p["ece"], a["ece"])
        checks[sl] = {"acc_win": bool(acc_win), "ece_win": bool(ece_win), "pass": bool(acc_win or ece_win)}
    lq = summary["low_quality"]
    lq_ad = lq["admixed"]
    lq_acc = lq_ad["gnn"]["acc"] >= max(lq_ad["pca3"]["acc"], lq_ad["admixture_nnls"]["acc"])
    lq_ece = lq_ad["gnn"]["ece"] <= min(lq_ad["pca3"]["ece"], lq_ad["admixture_nnls"]["ece"])
    checks["low_quality_admixed"] = {"acc_win": bool(lq_acc), "ece_win": bool(lq_ece), "pass": bool(lq_acc or lq_ece)}
    fine = summary["fine_scale"]["continental_only"]
    checks["fine_scale_continental"] = {
        "acc_win": bool(fine["gnn_acc"] >= fine["pca10_centroid_acc"]),
        "pass": bool(fine["gnn_acc"] >= fine["pca10_centroid_acc"]),
    }
    checks["passed"] = all(v["pass"] for v in checks.values())
    return checks


def train_full(pack, epochs: int, k: int, device: str, seed: int):
    data = build_similarity_graph(pack, k=k)
    n = len(pack.iids)
    rng = np.random.default_rng(seed)
    perm = rng.permutation(n)
    n_val = max(32, int(0.1 * n))
    va, tr = perm[:n_val], perm[n_val:]
    model = train_gat(data, tr, va, len(SUPERPOPS), len(pack.sub_classes), epochs=epochs, device=device, seed=seed)
    return model, data


def main() -> None:
    parser = argparse.ArgumentParser(description="步骤3：训练祖先 GAT 并评测 baseline")
    parser.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    parser.add_argument("--labels", type=Path, default=SAMPLES_INFO)
    parser.add_argument("--out", type=Path, default=ROOT / "steps" / "03_gnn" / "model.pt")
    parser.add_argument("--results-dir", type=Path, default=ROOT / "results" / "gnn")
    parser.add_argument("--n-snps", type=int, default=30000)
    parser.add_argument("--n-pcs", type=int, default=30)
    parser.add_argument("--k", type=int, default=20)
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--epochs", type=int, default=220)
    parser.add_argument("--lowq-frac", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    device = _device()
    logger.info("device=%s panel=%s", device, args.panel)
    pack = extract_panel_features(args.panel, args.labels, args.n_snps, args.n_pcs, args.k)
    summary, pred_df, T, slice_df = run_cv(pack, args.folds, args.epochs, args.k, args.seed, device, args.lowq_frac)

    args.results_dir.mkdir(parents=True, exist_ok=True)
    pred_df.to_csv(args.results_dir / "cv_predictions.tsv", sep="\t", index=False)
    slice_df.to_csv(args.results_dir / "cv_slices.tsv", sep="\t", index=False)
    (args.results_dir / "cv_metrics.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")

    logger.info("全量训练最终模型")
    model, data = train_full(pack, args.epochs, args.k, device, args.seed)
    ckpt = {
        "model_state": model.cpu().state_dict(),
        "in_dim": int(data.x.size(1)),
        "n_super": len(SUPERPOPS),
        "n_sub": len(pack.sub_classes),
        "sub_classes": pack.sub_classes,
        "superpops": SUPERPOPS,
        "temperature": T,
        "k": args.k,
        "n_pcs": args.n_pcs,
        "n_snps": args.n_snps,
        "snp_ids": pack.snp_ids,
        "pca_mean": pack.pca_mean,
        "pca_components": pack.pca_components,
        "pc_scaler_mean": pack.pc_scaler_mean,
        "pc_scaler_std": pack.pc_scaler_std,
        "panel_prefix": str(args.panel),
        "iids": pack.iids,
        "y_super": pack.y_super,
        "y_sub": pack.y_sub,
        "cv": summary,
        "method": "GAT kNN-graph + semi-supervised node classification",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    torch.save(ckpt, args.out)
    logger.info("写出模型 %s  | passed=%s", args.out, summary["win"]["passed"])
    print(json.dumps({"out": str(args.out), "passed": summary["win"]["passed"], "win": summary["win"]}, indent=2))


if __name__ == "__main__":
    main()
