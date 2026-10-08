"""
步骤 3 · GNN 祖先决策（定位 A）
==============================

任务：判断病人的祖先 / 群体结构，输出祖先概率 + 置信度，服务临床变异解读
（让步骤 2 选对"祖先匹配的等位基因频率"，支撑 ACMG PM2/BA1/BS1）。

方法：个体相似度图 + 半监督节点分类
    - 节点 = 病人 + 1000G 参考个体（3202 人，带人群标签，GRCh38 高覆盖面板）
    - 边   = 个体间遗传相似度（kNN，基于祖先信息位点 / PCA 距离）
    - GNN 消息传递 → 对病人节点做 softmax → 祖先概率 + 置信度
    - 相对 PCA/ADMIXTURE 的优势需在【混血/细分/低质量】样本上实测打赢 baseline

参考数据（只读）：
    /data/public/1000GP/20220422_3202_phased_SNV_INDEL_SV/  (GRCh38, 26 群, 3202 人)
    /data/public/1000GP/samples.info                        (样本→亚群标签)

运行环境：popgen_gnn（torch 2.1 + CUDA + PyG 2.4 + scikit-allel）
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gnn_core import (
    DEFAULT_PANEL,
    EASY_LOO,
    SUPERPOPS,
    AncestryGAT,
    attach_patient,
    build_inductive_graph,
    dosages_from_vcf,
    drop_iid,
    feature_pack_from_checkpoint,
    pca_nearest,
    predict_logits,
    softmax_np,
)

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
logger = logging.getLogger("decide")

REF_PANEL_DIR = Path("/data/public/1000GP/20220422_3202_phased_SNV_INDEL_SV")
DEFAULT_MODEL = Path(__file__).resolve().parent / "model.pt"


def _device() -> str:
    return "cuda" if torch.cuda.is_available() else "cpu"


def _load_ckpt(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"缺少训练好的模型 {path}，请先运行 steps/03_gnn/train.py")
    return torch.load(path, map_location="cpu")


def _frozen_model(ckpt: dict, device: str) -> AncestryGAT:
    model = AncestryGAT(int(ckpt["in_dim"]), int(ckpt["n_super"]), int(ckpt["n_sub"]))
    model.load_state_dict(ckpt["model_state"])
    model.to(device)
    model.eval()
    return model


def run_gnn_inference(graph, ckpt: dict | None = None, device: str | None = None):
    """加载 checkpoint，在归纳图上做一次前向。温度用交叉验证写入的值。"""
    ckpt = ckpt if ckpt is not None else _load_ckpt(DEFAULT_MODEL)
    if "temperature" not in ckpt:
        raise RuntimeError("checkpoint 缺少 temperature，不能做冻结推理")
    device = device or _device()
    idx = graph.patient_index
    if idx is None:
        raise RuntimeError("图中没有病人节点")
    model = _frozen_model(ckpt, device)
    logits_s, logits_b = predict_logits(model, graph, device)
    T = float(ckpt["temperature"])
    n_super = int(ckpt["n_super"])
    labeled = np.arange(graph.x.size(0))
    labeled = labeled[labeled != idx]
    pcs = graph.x.cpu().numpy()
    y = graph.y_super.cpu().numpy()
    pca_pred, _ = pca_nearest(
        pcs[labeled], y[labeled], pcs[idx : idx + 1], n_pc=min(3, pcs.shape[1]), n_classes=n_super
    )
    pca3 = SUPERPOPS[int(pca_pred[0])]
    probs = softmax_np(logits_s[idx : idx + 1], T=T)[0]
    ancestry = {SUPERPOPS[i]: round(float(probs[i]), 6) for i in range(len(SUPERPOPS))}
    pred = SUPERPOPS[int(probs.argmax())]
    confidence = float(probs.max())
    sub_logits = logits_b[idx]
    sub_classes = ckpt.get("sub_classes") or []
    sub_pred = None
    if len(sub_classes) == len(sub_logits):
        sub_pred = sub_classes[int(np.argmax(sub_logits))]
    return ancestry, confidence, pred, T, sub_pred, pca3


def decision_from_features(features, ckpt: dict, device: str | None = None) -> dict:
    graph = build_inductive_graph(features, k=int(ckpt.get("k", 20)))
    ancestry, confidence, pred, T, sub_pred, pca3 = run_gnn_inference(graph, ckpt, device)
    concordant = pred == pca3
    n_obs = int(features.n_observed_patient or 0)
    n_snps = int(len(features.snp_ids))
    note = None if concordant else f"pca3_{pca3}_gnn_{pred}_discordant"
    discordance_reason = None
    if not concordant:
        if n_snps and n_obs / n_snps < 0.5:
            discordance_reason = (
                "sparse_overlap_with_genomewide_aims;"
                "exome_capture_can_shift_the_patient_node;"
                "report confidence but do not lock lookup;"
                "analysis_based.af_population stays authoritative"
            )
        else:
            discordance_reason = "pca3_gnn_discordant_on_dense_overlap; do not lock lookup"
    return {
        "status": "OK",
        "note": note,
        "discordance_reason": discordance_reason,
        "ancestry": ancestry,
        "predicted": pred,
        "confidence": round(confidence, 6),
        "temperature": round(T, 4),
        "subpop_predicted": sub_pred,
        "pca3_nearest": pca3,
        "gnn_pca_concordant": concordant,
        "usable_for_lookup": bool(concordant),
        "n_ref": int(len(features.iids) - 1),
        "n_snps": n_snps,
        "n_snps_observed": n_obs,
        "k": int(ckpt.get("k", 20)),
        "inference": "inductive_frozen_checkpoint",
        "method": "frozen GAT checkpoint + patient-to-reference kNN",
    }


def _patient_from_vcf(vcf: Path, panel, ckpt: dict, workdir: Path):
    patient_vec, n_obs = dosages_from_vcf(vcf, panel.snp_ids, workdir)
    if n_obs < 200:
        raise RuntimeError(f"与训练位点交集过小 ({n_obs})，无法做 GNN 祖先推断")
    return attach_patient(panel, patient_vec)


def _write_decision(decision: dict, outdir: Path) -> Path:
    outdir.mkdir(parents=True, exist_ok=True)
    out = outdir / "gnn_decision.json"
    out.write_text(json.dumps(decision, indent=2, ensure_ascii=False) + "\n")
    logger.info(
        "已写出: %s  pred=%s conf=%.3f concordant=%s",
        out,
        decision["predicted"],
        decision["confidence"],
        decision["gnn_pca_concordant"],
    )
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="GNN 祖先决策（冻结 checkpoint）")
    parser.add_argument("--vcf", type=Path, help="病人 VCF")
    parser.add_argument("--panel-iid", help="从底库取该个体当病人，并从参考图中移除")
    parser.add_argument("--check-easy-loo", action="store_true", help="对四个大陆留一个体做冻结推理")
    parser.add_argument("--outdir", type=Path, required=True)
    parser.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    args = parser.parse_args()
    if not args.vcf and not args.panel_iid and not args.check_easy_loo:
        parser.error("需要 --vcf、--panel-iid 或 --check-easy-loo")
    args.outdir.mkdir(parents=True, exist_ok=True)

    ckpt = _load_ckpt(args.model)
    panel = feature_pack_from_checkpoint(ckpt, args.panel)
    device = _device()

    if args.check_easy_loo:
        rows = []
        for iid, (sub, true) in EASY_LOO.items():
            held = drop_iid(panel, iid)
            geno = panel.geno[panel.iids.astype(str) == iid]
            features = attach_patient(held, geno, patient_iid=iid)
            decision = decision_from_features(features, ckpt, device)
            ok = decision["predicted"] == true
            rows.append(
                {
                    "IID": iid,
                    "SUBPOP": sub,
                    "TRUE": true,
                    "GNN": decision["predicted"],
                    "GNN_pmax": decision["confidence"],
                    "PCA3": decision["pca3_nearest"],
                    "PASS": int(ok),
                }
            )
            logger.info("easy-loo %s true=%s pred=%s pass=%s", iid, true, decision["predicted"], ok)
        import pandas as pd

        out = args.outdir / "inductive_loo.tsv"
        pd.DataFrame(rows).to_csv(out, sep="\t", index=False)
        if not all(r["PASS"] for r in rows):
            raise SystemExit(f"冻结推理留一未全部命中标签: {out}")
        logger.info("已写出: %s", out)
        return

    if args.panel_iid:
        held = drop_iid(panel, args.panel_iid)
        geno = panel.geno[panel.iids.astype(str) == args.panel_iid]
        features = attach_patient(held, geno, patient_iid=args.panel_iid)
    else:
        logger.info("GNN 冻结推理 | 病人 VCF: %s", args.vcf)
        features = _patient_from_vcf(args.vcf, panel, ckpt, args.outdir / "gnn_tmp")
    decision = decision_from_features(features, ckpt, device)
    _write_decision(decision, args.outdir)


if __name__ == "__main__":
    main()
