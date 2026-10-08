"""步骤 3 共享核心：AIMs 特征、kNN 图、GAT、校准、baseline。"""
from __future__ import annotations

import json
import logging
import math
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F
from scipy.optimize import nnls
from sklearn.decomposition import PCA
from sklearn.neighbors import NearestNeighbors
from sklearn.model_selection import StratifiedKFold
from torch import nn
from torch_geometric.data import Data
from torch_geometric.nn import GATConv

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PANEL = ROOT / "data" / "reference" / "panel_1000g" / "ref_1000g_pruned"
SAMPLES_INFO = Path("/data/public/1000GP/samples.info")
SUPERPOPS = ["AFR", "EUR", "EAS", "SAS", "AMR"]
ADMIXED_SUBPOPS = {"ASW", "ACB", "MXL", "PUR", "CLM", "PEL"}
AFR_UNADMIXED = {"YRI", "LWK", "GWD", "MSL", "ESN"}
EASY_LOO = {
    "NA18486": ("YRI", "AFR"),
    "NA06985": ("CEU", "EUR"),
    "NA18526": ("CHB", "EAS"),
    "HG03713": ("ITU", "SAS"),
}
SUBPOP_TO_SUPERPOP = {
    "YRI": "AFR", "LWK": "AFR", "GWD": "AFR", "MSL": "AFR", "ESN": "AFR",
    "ASW": "AFR", "ACB": "AFR",
    "CEU": "EUR", "TSI": "EUR", "FIN": "EUR", "GBR": "EUR", "IBS": "EUR",
    "CHB": "EAS", "JPT": "EAS", "CHS": "EAS", "CDX": "EAS", "KHV": "EAS",
    "GIH": "SAS", "PJL": "SAS", "BEB": "SAS", "STU": "SAS", "ITU": "SAS",
    "MXL": "AMR", "PUR": "AMR", "CLM": "AMR", "PEL": "AMR",
}


@dataclass
class FeaturePack:
    pcs: np.ndarray
    iids: np.ndarray
    y_super: np.ndarray
    y_sub: np.ndarray
    snp_ids: np.ndarray
    geno: np.ndarray
    pca_mean: np.ndarray
    pca_components: np.ndarray
    pc_scaler_mean: np.ndarray
    pc_scaler_std: np.ndarray
    patient_index: int | None = None
    n_observed_patient: int | None = None
    sub_classes: list[str] = field(default_factory=list)
    k: int = 15


class AncestryGAT(nn.Module):
    def __init__(self, in_dim: int, n_super: int, n_sub: int, hidden: int = 64, heads: int = 4, dropout: float = 0.35):
        super().__init__()
        self.dropout = dropout
        self.conv1 = GATConv(in_dim, hidden, heads=heads, dropout=dropout)
        self.conv2 = GATConv(hidden * heads, hidden, heads=1, concat=True, dropout=dropout)
        self.head_super = nn.Linear(hidden, n_super)
        self.head_sub = nn.Linear(hidden, n_sub)

    def forward(self, x, edge_index):
        x = F.elu(self.conv1(x, edge_index))
        x = F.dropout(x, p=self.dropout, training=self.training)
        x = F.elu(self.conv2(x, edge_index))
        x = F.dropout(x, p=self.dropout, training=self.training)
        return self.head_super(x), self.head_sub(x)


def _run(cmd: str) -> subprocess.CompletedProcess:
    logger.info("RUN: %s", cmd)
    proc = subprocess.run(cmd, shell=True, text=True, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"命令失败 ({proc.returncode}): {cmd}\n{(proc.stderr or '')[-2000:]}")
    return proc


def load_labels(panel_prefix: Path, labels_path: Path | None = None) -> pd.DataFrame:
    tsv = panel_prefix.parent / "sample_superpop.tsv"
    fam = pd.read_csv(f"{panel_prefix}.fam", sep=r"\s+", header=None, engine="python")
    fam.columns = ["FID", "IID", "F", "M", "S", "P"]
    iids = fam["IID"].astype(str)
    if tsv.exists():
        lab = pd.read_csv(tsv, sep="\t")
        lab["IID"] = lab["IID"].astype(str)
        merged = fam[["IID"]].merge(lab, on="IID", how="left")
    else:
        src = Path(labels_path) if labels_path else SAMPLES_INFO
        raw = pd.read_csv(src, sep="\t", header=None, names=["IID", "SUBPOP", "SEX"])
        raw["IID"] = raw["IID"].astype(str)
        raw["SUPERPOP"] = raw["SUBPOP"].map(SUBPOP_TO_SUPERPOP)
        merged = fam[["IID"]].merge(raw[["IID", "SUBPOP", "SUPERPOP"]], on="IID", how="left")
    missing = merged["SUPERPOP"].isna().sum()
    if missing:
        raise RuntimeError(f"{missing} 个样本缺少超群标签")
    merged["IID"] = iids.values
    return merged.reset_index(drop=True)


def read_bed_subset(panel_prefix: Path, n_snps_keep: int, seed: int = 42) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """读 PLINK SNP-major BED，均匀抽 n_snps_keep 个位点，返回 (n_samples, n_keep) A1 剂量。"""
    bim = pd.read_csv(f"{panel_prefix}.bim", sep="\t", header=None)
    n_snps = len(bim)
    keep = np.unique(np.round(np.linspace(0, n_snps - 1, n_snps_keep)).astype(int))
    return read_bed_indices(panel_prefix, keep)


def read_bed_indices(panel_prefix: Path, keep: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    fam = pd.read_csv(f"{panel_prefix}.fam", sep=r"\s+", header=None, engine="python")
    bim = pd.read_csv(f"{panel_prefix}.bim", sep="\t", header=None)
    n_samples = len(fam)
    n_snps = len(bim)
    keep = np.asarray(keep, dtype=int)
    nbytes = (n_samples + 3) // 4
    bed_path = Path(str(panel_prefix) + ".bed")
    logger.info("读取 BED %s  | 样本 %s 位点 %s 抽取 %s", bed_path, n_samples, n_snps, len(keep))
    raw = np.fromfile(bed_path, dtype=np.uint8, offset=3)
    if raw.size != n_snps * nbytes:
        raise RuntimeError(f"BED 大小不符: {raw.size} vs {n_snps * nbytes}")
    raw = raw.reshape(n_snps, nbytes)[keep]
    geno = _unpack_bed_blocks(raw, n_samples)
    snp_ids = bim.iloc[keep, 1].astype(str).to_numpy()
    iids = fam[1].astype(str).to_numpy()
    logger.info("基因型矩阵 %s 缺失率 %.4f", geno.shape, float(np.isnan(geno).mean()))
    return geno, iids, snp_ids


def _unpack_bed_blocks(raw: np.ndarray, n_samples: int) -> np.ndarray:
    n_snps, nbytes = raw.shape
    codes = np.empty((n_snps, nbytes * 4), dtype=np.uint8)
    for bit in range(4):
        codes[:, bit::4] = (raw >> (2 * bit)) & 3
    codes = codes[:, :n_samples]
    dosage = np.empty((n_snps, n_samples), dtype=np.float32)
    dosage[:] = np.nan
    dosage[codes == 0] = 0.0
    dosage[codes == 2] = 1.0
    dosage[codes == 3] = 2.0
    return dosage.T.copy()


def impute_mean(geno: np.ndarray, mean: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    if mean is None:
        mean = np.nanmean(geno, axis=0)
    mean = np.where(np.isfinite(mean), mean, 0.0).astype(np.float32)
    filled = geno.copy()
    nan_mask = ~np.isfinite(filled)
    if nan_mask.any():
        filled[nan_mask] = np.take(mean, np.where(nan_mask)[1])
    return filled, mean


def fit_pca(geno: np.ndarray, n_pcs: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    filled, mean = impute_mean(geno)
    n_pcs = min(n_pcs, filled.shape[0] - 1, filled.shape[1])
    pca = PCA(n_components=n_pcs, svd_solver="randomized", random_state=42)
    pcs = pca.fit_transform(filled).astype(np.float32)
    return pcs, mean, pca.components_.astype(np.float32)


def transform_pca(geno: np.ndarray, mean: np.ndarray, components: np.ndarray) -> np.ndarray:
    """缺失位点不填均值（等价于该位点对 PC 贡献 0），并按观测比例放大，避免稀疏样本缩到原点。"""
    x = geno.astype(np.float32, copy=True)
    n_snps = x.shape[1]
    obs = np.isfinite(x)
    n_obs = obs.sum(axis=1).clip(min=1)
    col_mean = mean.astype(np.float32)
    x = np.where(obs, x, col_mean)
    centered = x - col_mean
    centered = np.where(obs, centered, 0.0)
    pcs = centered @ components.T
    scale = (n_snps / n_obs).astype(np.float32)[:, None]
    return (pcs * scale).astype(np.float32)


def standardize_pcs(pcs: np.ndarray, mean: np.ndarray | None = None, std: np.ndarray | None = None):
    if mean is None:
        mean = pcs.mean(axis=0)
        std = pcs.std(axis=0)
        std = np.where(std < 1e-8, 1.0, std)
    return ((pcs - mean) / std).astype(np.float32), mean.astype(np.float32), std.astype(np.float32)


def knn_edge_index(pcs: np.ndarray, k: int) -> torch.Tensor:
    n = pcs.shape[0]
    k = min(k, n - 1)
    nn_ = NearestNeighbors(n_neighbors=k + 1, algorithm="auto")
    nn_.fit(pcs)
    dist, idx = nn_.kneighbors(pcs)
    src, dst = [], []
    for i in range(n):
        for j, d in zip(idx[i], dist[i]):
            if i == j:
                continue
            src.append(i)
            dst.append(int(j))
            src.append(int(j))
            dst.append(i)
    edges = np.unique(np.stack([src, dst], axis=0), axis=1)
    return torch.tensor(edges, dtype=torch.long)


def _graph_from_features(features: FeaturePack, edge_index: torch.Tensor) -> Data:
    data = Data(
        x=torch.tensor(features.pcs, dtype=torch.float32),
        edge_index=edge_index,
        y_super=torch.tensor(features.y_super, dtype=torch.long),
        y_sub=torch.tensor(features.y_sub, dtype=torch.long),
    )
    data.patient_index = features.patient_index
    data.iids = features.iids
    return data


def build_similarity_graph(features: FeaturePack, k: int = 15) -> Data:
    """参考个体之间的 kNN（训练图）。含病人节点时请用 build_inductive_graph。"""
    return _graph_from_features(features, knn_edge_index(features.pcs, k=k))


def build_inductive_graph(features: FeaturePack, k: int | None = None) -> Data:
    """参考–参考边与训练时相同；病人只连到 k 个最近参考个体，不重训。"""
    if features.patient_index is None:
        return build_similarity_graph(features, k=k or features.k)
    k = int(k or features.k)
    idx = int(features.patient_index)
    ref_pcs = features.pcs[:idx]
    pat_pcs = features.pcs[idx : idx + 1]
    ref_edges = knn_edge_index(ref_pcs, k=k)
    k_use = min(k, ref_pcs.shape[0])
    nn_ = NearestNeighbors(n_neighbors=k_use, algorithm="auto")
    nn_.fit(ref_pcs)
    neigh = nn_.kneighbors(pat_pcs, return_distance=False)[0]
    extra_src: list[int] = []
    extra_dst: list[int] = []
    for j in neigh:
        j = int(j)
        extra_src.extend([idx, j])
        extra_dst.extend([j, idx])
    extra = torch.tensor([extra_src, extra_dst], dtype=torch.long)
    edge_index = torch.unique(torch.cat([ref_edges, extra], dim=1), dim=1)
    return _graph_from_features(features, edge_index)


def class_weights(y: np.ndarray, n_classes: int) -> torch.Tensor:
    valid = y[y >= 0]
    counts = np.bincount(valid, minlength=n_classes).astype(np.float64)
    counts = np.maximum(counts, 1.0)
    w = counts.sum() / (n_classes * counts)
    return torch.tensor(w, dtype=torch.float32)


def fit_temperature(logits: torch.Tensor, labels: torch.Tensor) -> float:
    T = nn.Parameter(torch.ones(1, device=logits.device))
    opt = torch.optim.LBFGS([T], lr=0.05, max_iter=80)

    def closure():
        opt.zero_grad()
        loss = F.cross_entropy(logits / T.clamp(min=0.05, max=20.0), labels)
        loss.backward()
        return loss

    opt.step(closure)
    return float(T.detach().clamp(min=0.05, max=20.0).cpu())


def softmax_np(logits: np.ndarray, T: float = 1.0) -> np.ndarray:
    z = logits / max(T, 1e-6)
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


def ece_score(probs: np.ndarray, y: np.ndarray, n_bins: int = 10) -> float:
    if len(y) == 0:
        return float("nan")
    conf = probs.max(axis=1)
    pred = probs.argmax(axis=1)
    correct = (pred == y).astype(np.float64)
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    for i in range(n_bins):
        m = (conf > bins[i]) & (conf <= bins[i + 1]) if i else (conf >= bins[i]) & (conf <= bins[i + 1])
        if not m.any():
            continue
        ece += m.mean() * abs(correct[m].mean() - conf[m].mean())
    return float(ece)


def accuracy(pred: np.ndarray, y: np.ndarray) -> float:
    if len(y) == 0:
        return float("nan")
    return float((pred == y).mean())


def pca_nearest(
    train_pcs: np.ndarray, train_y: np.ndarray, test_pcs: np.ndarray, n_pc: int, n_classes: int
) -> tuple[np.ndarray, np.ndarray]:
    use = min(n_pc, train_pcs.shape[1])
    centroids = np.zeros((n_classes, use), dtype=np.float64)
    for c in range(n_classes):
        m = train_y == c
        if not m.any():
            centroids[c] = 1e9
        else:
            centroids[c] = train_pcs[m, :use].mean(axis=0)
    d = ((test_pcs[:, :use][:, None, :] - centroids[None, :, :]) ** 2).sum(axis=2) ** 0.5
    pred = d.argmin(axis=1).astype(int)
    probs = softmax_np(-d.astype(np.float64), T=float(np.median(d) + 1e-6))
    return pred, probs


def admixture_nnls(train_geno: np.ndarray, train_y: np.ndarray, test_geno: np.ndarray, n_classes: int) -> tuple[np.ndarray, np.ndarray]:
    """监督等位基因频率 + NNLS 投影（ADMIXTURE 风格 Q）。"""
    filled_tr, mean = impute_mean(train_geno)
    filled_te, _ = impute_mean(test_geno, mean)
    F = np.zeros((filled_tr.shape[1], n_classes), dtype=np.float64)
    for c in range(n_classes):
        m = train_y == c
        F[:, c] = 0.5 * filled_tr[m].mean(axis=0) if m.any() else 0.5 * mean
    A = 2.0 * F
    q = np.zeros((filled_te.shape[0], n_classes), dtype=np.float64)
    for i in range(filled_te.shape[0]):
        coef, _ = nnls(A, filled_te[i].astype(np.float64))
        s = coef.sum()
        q[i] = coef / s if s > 0 else np.full(n_classes, 1.0 / n_classes)
    return q.argmax(axis=1).astype(int), q


def slice_mask(subpops: np.ndarray, name: str) -> np.ndarray:
    if name == "all":
        return np.ones(len(subpops), dtype=bool)
    if name == "continental":
        return np.array([s not in ADMIXED_SUBPOPS for s in subpops])
    if name == "admixed":
        return np.array([s in ADMIXED_SUBPOPS for s in subpops])
    if name == "amr":
        return np.array([s in {"MXL", "PUR", "CLM", "PEL"} for s in subpops])
    if name == "afr_admixed":
        return np.array([s in {"ASW", "ACB"} for s in subpops])
    if name == "easy_loo":
        return np.array([s in {v[0] for v in EASY_LOO.values()} for s in subpops])
    raise KeyError(name)


def metrics_block(probs: np.ndarray, y: np.ndarray, pred: np.ndarray | None = None) -> dict:
    if pred is None:
        pred = probs.argmax(axis=1)
    return {
        "n": int(len(y)),
        "acc": round(accuracy(pred, y), 4),
        "ece": round(ece_score(probs, y), 4),
        "mean_confidence": round(float(probs.max(axis=1).mean()) if len(y) else float("nan"), 4),
    }


def one_hot(y: np.ndarray, n: int) -> np.ndarray:
    oh = np.zeros((len(y), n), dtype=np.float64)
    oh[np.arange(len(y)), y] = 1.0
    return oh


def train_gat(
    data: Data,
    train_idx: np.ndarray,
    val_idx: np.ndarray,
    n_super: int,
    n_sub: int,
    epochs: int = 250,
    lr: float = 5e-3,
    patience: int = 40,
    device: str = "cpu",
    seed: int = 42,
    weighted: bool = True,
) -> AncestryGAT:
    torch.manual_seed(seed)
    model = AncestryGAT(data.x.size(1), n_super, n_sub).to(device)
    opt = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=5e-4)
    x = data.x.to(device)
    ei = data.edge_index.to(device)
    ys = data.y_super.to(device)
    yb = data.y_sub.to(device)
    tr = torch.tensor(train_idx, dtype=torch.long, device=device)
    va = torch.tensor(val_idx, dtype=torch.long, device=device)
    w_s = class_weights(data.y_super.cpu().numpy()[train_idx], n_super).to(device) if weighted else None
    w_b = class_weights(data.y_sub.cpu().numpy()[train_idx], n_sub).to(device) if weighted else None
    best_state, best_loss, stale = None, math.inf, 0
    for epoch in range(1, epochs + 1):
        model.train()
        opt.zero_grad()
        logit_s, logit_b = model(x, ei)
        loss = F.cross_entropy(logit_s[tr], ys[tr], weight=w_s) + 0.8 * F.cross_entropy(logit_b[tr], yb[tr], weight=w_b)
        loss.backward()
        opt.step()
        model.eval()
        with torch.no_grad():
            vs, vb = model(x, ei)
            vloss = float(F.cross_entropy(vs[va], ys[va]) + 0.8 * F.cross_entropy(vb[va], yb[va]))
        if vloss < best_loss - 1e-4:
            best_loss, stale = vloss, 0
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
        else:
            stale += 1
            if stale >= patience:
                logger.info("early stop epoch=%s val=%.4f", epoch, best_loss)
                break
    if best_state is None:
        best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
    model.load_state_dict(best_state)
    model.to(device)
    model.eval()
    return model


def predict_logits(model: AncestryGAT, data: Data, device: str) -> tuple[np.ndarray, np.ndarray]:
    model.eval()
    with torch.no_grad():
        s, b = model(data.x.to(device), data.edge_index.to(device))
    return s.cpu().numpy(), b.cpu().numpy()


def dosages_from_vcf(vcf: Path, snp_ids: np.ndarray, workdir: Path) -> tuple[np.ndarray, int]:
    """按底库 chr:pos:REF:ALT（A2:A1）从病人 VCF 取 A1 剂量。"""
    workdir.mkdir(parents=True, exist_ok=True)
    sites = workdir / "patient_sites.tsv"
    rows = []
    meta = []
    for sid in snp_ids:
        chrom, pos, ref, alt = str(sid).split(":")
        rows.append(f"{chrom}\t{pos}\n")
        meta.append((chrom, int(pos), ref, alt))
    sites.write_text("".join(rows))
    out = workdir / "patient_gt.tsv"
    _run(f"bcftools query -T {sites} -f '%CHROM\\t%POS\\t%REF\\t%ALT[\\t%GT]\\n' {vcf} > {out}")
    seen: dict[tuple, str] = {}
    if out.stat().st_size:
        for line in out.read_text().splitlines():
            parts = line.split("\t")
            if len(parts) < 5:
                continue
            chrom, pos, ref, alt, gt = parts[0], int(parts[1]), parts[2], parts[3], parts[4]
            seen[(chrom, pos, ref, alt)] = gt
            seen[(chrom, pos, alt, ref)] = f"FLIP:{gt}"

    def gt_to_dose(gt: str, flip: bool) -> float:
        g = gt.replace("|", "/")
        if g.startswith("FLIP:"):
            g = g[5:]
            flip = not flip
        if "." in g:
            return np.nan
        a, b = g.split("/")[:2]
        try:
            dose = int(a) + int(b)
        except ValueError:
            return np.nan
        return float(2 - dose if flip else dose)

    vec = np.full(len(meta), np.nan, dtype=np.float32)
    n_obs = 0
    for i, (chrom, pos, ref, alt) in enumerate(meta):
        key = (chrom, pos, ref, alt)
        if key in seen:
            raw = seen[key]
            flip = str(raw).startswith("FLIP:")
            d = gt_to_dose(raw, flip)
            vec[i] = d
            if np.isfinite(d):
                n_obs += 1
    logger.info("病人与抽定位点交集: %s / %s", n_obs, len(meta))
    return vec.reshape(1, -1), n_obs


def extract_intersect_pack(
    vcf: Path,
    panel_prefix: Path,
    labels_path: Path | None,
    workdir: Path,
    n_pcs: int,
    k: int,
) -> FeaturePack:
    """病人 VCF ∩ 全底库位点，供转导推理（不限训练抽的 30k）。"""
    bim = pd.read_csv(f"{panel_prefix}.bim", sep="\t", header=None)
    snp_ids_all = bim[1].astype(str).to_numpy()
    patient_vec, n_hit = dosages_from_vcf(vcf, snp_ids_all, workdir)
    obs = np.isfinite(patient_vec.reshape(-1))
    keep = np.where(obs)[0]
    logger.info("全底库交集位点 %s / %s", len(keep), len(snp_ids_all))
    if len(keep) < 200:
        raise RuntimeError(f"与底库交集过小 ({len(keep)})，无法做 GNN 祖先推断")
    geno, iids, snp_ids = read_bed_indices(panel_prefix, keep)
    lab = load_labels(panel_prefix, labels_path)
    lab = lab.set_index("IID").loc[iids]
    sub_classes = sorted(lab["SUBPOP"].unique())
    y_super = np.array([SUPERPOPS.index(s) for s in lab["SUPERPOP"]], dtype=np.int64)
    y_sub = np.array([sub_classes.index(s) for s in lab["SUBPOP"]], dtype=np.int64)
    pack = FeaturePack(
        pcs=np.zeros((len(iids), 1), dtype=np.float32),
        iids=iids,
        y_super=y_super,
        y_sub=y_sub,
        snp_ids=snp_ids,
        geno=geno,
        pca_mean=np.zeros(len(snp_ids), dtype=np.float32),
        pca_components=np.zeros((n_pcs, len(snp_ids)), dtype=np.float32),
        pc_scaler_mean=np.zeros(n_pcs, dtype=np.float32),
        pc_scaler_std=np.ones(n_pcs, dtype=np.float32),
        sub_classes=sub_classes,
        k=k,
    )
    fused = attach_patient_transductive(pack, patient_vec[:, keep], n_pcs=n_pcs)
    fused.n_observed_patient = int(len(keep))
    fused.k = k
    return fused


def feature_pack_from_checkpoint(ckpt: dict, panel_prefix: Path) -> FeaturePack:
    """用 checkpoint 里的位点、PCA 和标准化参数重建参考节点，不重新 fit。"""
    snp_ids = np.asarray(ckpt["snp_ids"]).astype(str)
    bim = pd.read_csv(f"{panel_prefix}.bim", sep="\t", header=None)
    lookup = {sid: i for i, sid in enumerate(bim[1].astype(str))}
    missing = [sid for sid in snp_ids if sid not in lookup]
    if missing:
        raise RuntimeError(f"checkpoint 位点不在底库 bim 中，例如 {missing[:3]}")
    keep = np.array([lookup[sid] for sid in snp_ids], dtype=int)
    geno, iids, got_ids = read_bed_indices(panel_prefix, keep)
    if not np.array_equal(got_ids.astype(str), snp_ids):
        raise RuntimeError("底库位点顺序与 checkpoint snp_ids 不一致")
    ckpt_iids = np.asarray(ckpt["iids"]).astype(str)
    if not np.array_equal(iids.astype(str), ckpt_iids):
        raise RuntimeError("底库个体顺序与 checkpoint iids 不一致")
    mean = np.asarray(ckpt["pca_mean"], dtype=np.float32)
    components = np.asarray(ckpt["pca_components"], dtype=np.float32)
    sc_mean = np.asarray(ckpt["pc_scaler_mean"], dtype=np.float32)
    sc_std = np.asarray(ckpt["pc_scaler_std"], dtype=np.float32)
    raw = transform_pca(geno, mean, components)
    pcs = ((raw - sc_mean) / sc_std).astype(np.float32)
    return FeaturePack(
        pcs=pcs,
        iids=iids,
        y_super=np.asarray(ckpt["y_super"], dtype=np.int64),
        y_sub=np.asarray(ckpt["y_sub"], dtype=np.int64),
        snp_ids=snp_ids,
        geno=geno,
        pca_mean=mean,
        pca_components=components,
        pc_scaler_mean=sc_mean,
        pc_scaler_std=sc_std,
        sub_classes=list(ckpt["sub_classes"]),
        k=int(ckpt["k"]),
    )


def drop_iid(panel: FeaturePack, iid: str) -> FeaturePack:
    """从参考图拿走该个体，避免留一推理时病人连到自己。"""
    keep = panel.iids.astype(str) != str(iid)
    if int(keep.sum()) == len(panel.iids):
        raise KeyError(f"底库中没有个体 {iid}")
    return FeaturePack(
        pcs=panel.pcs[keep],
        iids=panel.iids[keep],
        y_super=panel.y_super[keep],
        y_sub=panel.y_sub[keep],
        snp_ids=panel.snp_ids,
        geno=panel.geno[keep],
        pca_mean=panel.pca_mean,
        pca_components=panel.pca_components,
        pc_scaler_mean=panel.pc_scaler_mean,
        pc_scaler_std=panel.pc_scaler_std,
        sub_classes=list(panel.sub_classes),
        k=panel.k,
    )


def extract_panel_features(
    panel_prefix: Path,
    labels_path: Path | None,
    n_snps: int,
    n_pcs: int,
    k: int,
) -> FeaturePack:
    geno, iids, snp_ids = read_bed_subset(panel_prefix, n_snps)
    lab = load_labels(panel_prefix, labels_path)
    lab = lab.set_index("IID").loc[iids]
    sub_classes = sorted(lab["SUBPOP"].unique())
    y_super = np.array([SUPERPOPS.index(s) for s in lab["SUPERPOP"]], dtype=np.int64)
    y_sub = np.array([sub_classes.index(s) for s in lab["SUBPOP"]], dtype=np.int64)
    pcs, pca_mean, components = fit_pca(geno, n_pcs)
    pcs, sc_mean, sc_std = standardize_pcs(pcs)
    pack = FeaturePack(
        pcs=pcs,
        iids=iids,
        y_super=y_super,
        y_sub=y_sub,
        snp_ids=snp_ids,
        geno=geno,
        pca_mean=pca_mean,
        pca_components=components,
        pc_scaler_mean=sc_mean,
        pc_scaler_std=sc_std,
        sub_classes=sub_classes,
        k=k,
    )
    return pack


def attach_patient(panel: FeaturePack, patient_geno: np.ndarray, patient_iid: str = "patient") -> FeaturePack:
    raw_pc = transform_pca(patient_geno, panel.pca_mean, panel.pca_components)
    pcs_p = ((raw_pc - panel.pc_scaler_mean) / panel.pc_scaler_std).astype(np.float32)
    pcs = np.vstack([panel.pcs, pcs_p])
    iids = np.concatenate([panel.iids, np.array([patient_iid])])
    y_super = np.concatenate([panel.y_super, np.array([-1], dtype=np.int64)])
    y_sub = np.concatenate([panel.y_sub, np.array([-1], dtype=np.int64)])
    geno = np.vstack([panel.geno, patient_geno.astype(np.float32)])
    return FeaturePack(
        pcs=pcs,
        iids=iids,
        y_super=y_super,
        y_sub=y_sub,
        snp_ids=panel.snp_ids,
        geno=geno,
        pca_mean=panel.pca_mean,
        pca_components=panel.pca_components,
        pc_scaler_mean=panel.pc_scaler_mean,
        pc_scaler_std=panel.pc_scaler_std,
        patient_index=len(iids) - 1,
        n_observed_patient=int(np.isfinite(patient_geno).sum()),
        sub_classes=list(panel.sub_classes),
        k=panel.k,
    )


def attach_patient_transductive(
    panel: FeaturePack,
    patient_geno: np.ndarray,
    n_pcs: int = 30,
    patient_iid: str = "patient",
) -> FeaturePack:
    """只用病人观测到的位点重做 PCA，避免 90% 缺失把坐标压到原点。"""
    obs = np.isfinite(patient_geno.reshape(-1))
    n_obs = int(obs.sum())
    if n_obs < 200:
        raise RuntimeError(f"与底库抽定位点交集过小 ({n_obs})")
    geno_obs = panel.geno[:, obs]
    pat_obs = patient_geno[:, obs]
    n_pcs = min(n_pcs, geno_obs.shape[0] - 1, geno_obs.shape[1])
    pcs_panel, mean, comp = fit_pca(geno_obs, n_pcs)
    pcs_pat = transform_pca(pat_obs, mean, comp)
    pcs = np.vstack([pcs_panel, pcs_pat])
    pcs, sc_mean, sc_std = standardize_pcs(pcs)
    iids = np.concatenate([panel.iids, np.array([patient_iid])])
    logger.info("转导 PCA：观测位点 %s，PC=%s", n_obs, n_pcs)
    return FeaturePack(
        pcs=pcs,
        iids=iids,
        y_super=np.concatenate([panel.y_super, np.array([-1], dtype=np.int64)]),
        y_sub=np.concatenate([panel.y_sub, np.array([-1], dtype=np.int64)]),
        snp_ids=panel.snp_ids[obs],
        geno=np.vstack([geno_obs, pat_obs.astype(np.float32)]),
        pca_mean=mean,
        pca_components=comp,
        pc_scaler_mean=sc_mean,
        pc_scaler_std=sc_std,
        patient_index=len(iids) - 1,
        n_observed_patient=n_obs,
        sub_classes=list(panel.sub_classes),
        k=panel.k,
    )
