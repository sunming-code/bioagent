#!/usr/bin/env python3
"""Internal dependency checks; all outputs go to a temporary workspace."""
from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import importlib.util
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def load_script(relative):
    spec = importlib.util.spec_from_file_location("atheromap_smoke_module", ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(cmd):
    print("Running:", " ".join(map(str, cmd)), flush=True)
    if "--help" in cmd:
        result = subprocess.run(list(map(str, cmd)), text=True, capture_output=True)
        if result.returncode:
            print(result.stdout, result.stderr, flush=True)
            result.check_returncode()
        print("CLI help passed", flush=True)
    else:
        subprocess.run(list(map(str, cmd)), check=True)


def common_data():
    import anndata as ad
    import numpy as np
    import pandas as pd
    import scanpy as sc
    from scipy import sparse

    rng = np.random.default_rng(1729)
    n_cells, n_genes = 240, 1200
    gene_rates = rng.lognormal(0.0, 0.7, n_genes)
    cell_rates = rng.uniform(0.6, 1.8, n_cells)
    means = cell_rates[:, None] * gene_rates[None, :]
    means[:120, :60] *= 3
    means[120:, 60:120] *= 3
    counts = sparse.csr_matrix(rng.poisson(means).astype("float64"))
    obs = pd.DataFrame(index=[f"cell_{i}" for i in range(n_cells)])
    obs["patient"] = [f"P{i % 2 + 1}" for i in range(n_cells)]
    # Every synthetic sample contains both expression clusters, as required by scDblFinder.
    obs["condition"] = ["H" if i % 4 < 2 else "D" for i in range(n_cells)]
    obs["sample_id"] = obs["patient"] + "_" + obs["condition"]
    obs["clusters"] = [str(i // 120) for i in range(n_cells)]
    obs["leiden_filt"] = obs["clusters"]
    obs["final_high_level_celltype_10"] = ["Macrophage" if i < 120 else "VSMC" for i in range(n_cells)]
    var = pd.DataFrame(index=[f"GENE{i}" for i in range(n_genes)])
    var["gene_name"] = var.index
    data = ad.AnnData(X=counts, obs=obs, var=var)
    data.layers["raw_counts"] = counts.copy()
    data.obs["n_counts"] = np.asarray(counts.sum(axis=1)).ravel()
    data.obs["mt_frac"] = rng.uniform(0.0, 0.05, n_cells)
    sc.pp.normalize_total(data, target_sum=10000)
    sc.pp.log1p(data)
    sc.pp.pca(data, n_comps=20)
    sc.pp.neighbors(data, n_neighbors=10, n_pcs=20)
    sc.tl.leiden(data, key_added="harmony_leiden", random_state=0)
    sc.tl.umap(data, random_state=0)
    print("Scanpy PCA/neighbors/Leiden/UMAP passed", flush=True)
    return data


def scdrs_smoke(data, with_r):
    import harmonypy as hm
    import numpy as np
    import pandas as pd

    harmony = hm.run_harmony(data.obsm["X_pca"], data.obs, "patient", max_iter_harmony=3)
    assert np.isfinite(harmony.Z_corr).all()
    data.obsm["X_harmony"] = harmony.Z_corr.T
    with tempfile.TemporaryDirectory(prefix="atheromap_scdrs_smoke_") as tmp:
        tmp = Path(tmp)
        workspace = Path(os.environ["ATHEROMAP_SCDRS_WORK_DIR"])
        (workspace / "merged").mkdir(parents=True, exist_ok=True)
        raw = data.copy()
        raw.X = raw.layers["raw_counts"].copy()
        raw.uns.pop("log1p", None)
        raw.write_h5ad(workspace / "merged/GSE159677_harmony_highlevel_annotated_final.h5ad")
        (tmp / "trait.gs").write_text("TRAIT\tGENESET\nsmoke\t" + ",".join(raw.var_names[:40]) + "\n")
        run([sys.executable, ROOT / "scdrs/scripts/overall_analysis/run_GSE159677_prepare_scdrs.py"])
        run(["bash", ROOT / "scdrs/scripts/overall_analysis/run_GSE159677_scdrs_cli.sh", "smoke", tmp / "trait.gs"])
        score_file = workspace / "scdrs_out/smoke.full_score.gz"
        scores = pd.read_csv(score_file, sep="\t", index_col=0)
        assert scores.shape[0] == raw.n_obs and np.isfinite(scores["norm_score"]).all()
        for group in ("final_high_level_celltype_10", "patient", "condition", "harmony_leiden"):
            assert (workspace / f"scdrs_out/smoke.scdrs_group.{group}").is_file()
        print("Harmony, project scDRS preparation and original scoring/downstream shell passed (n_ctrl=1000)", flush=True)
        if with_r:
            pre = load_script("scdrs/scripts/overall_analysis/run_GSE159677_pre_scdrs_harmony.py")
            doublets = pre.run_scDblFinder(raw)
            assert "scDblFinder.class" in doublets.obs
            normalized = pre.run_acosh_norm(raw)
            assert np.isfinite(normalized.obs["size_factors"]).all()
            assert (normalized.obs["size_factors"] > 0).all()
            assert "acosh" in normalized.layers
            print("Project Python/R H5AD exchange, scDblFinder and scran passed", flush=True)


def gsmap_smoke(data):
    import cv2
    import numpy as np
    import plotly.graph_objects as go
    import SpaGCN as spg
    import torch
    from torch_geometric.nn import GCNConv

    torch.manual_seed(100)
    random.seed(100)
    np.random.seed(100)
    output = GCNConv(4, 3)(torch.randn(4, 4), torch.tensor([[0, 1, 2, 3], [1, 2, 3, 0]]))
    assert output.shape == (4, 3) and torch.isfinite(output).all()
    adj = spg.calculate_adj_matrix(x=np.repeat(np.arange(20), 12).tolist(),
                                   y=np.tile(np.arange(12), 20).tolist(), histology=False)
    model = spg.SpaGCN()
    model.set_l(1.0)
    model.train(data, adj, init_spa=True, init="louvain", res=0.5,
                tol=0.005, lr=0.05, max_epochs=5)
    labels, probabilities = model.predict()
    assert len(labels) == data.n_obs and np.isfinite(probabilities).all()
    print("Torch, torch-geometric and SpaGCN adjacency/training/prediction passed", flush=True)
    ok, encoded = cv2.imencode(".png", np.zeros((8, 8, 3), dtype=np.uint8))
    assert ok and cv2.imdecode(encoded, cv2.IMREAD_COLOR).shape == (8, 8, 3)
    rendered = go.Figure(go.Scatter(x=[0, 1], y=[0, 1])).to_image(format="png", width=240, height=180)
    assert rendered.startswith(b"\x89PNG")
    print("OpenCV PNG round-trip and Plotly/Kaleido report image export passed", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("group", choices=("scdrs", "gsmap"))
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--with-r", action="store_true")
    args = parser.parse_args()
    if args.smoke:
        temporary_root = os.environ.get("ATHEROMAP_SMOKE_WORKSPACE")
        if not temporary_root:
            parser.error("Run numerical tests through tools/check_environments.py --smoke")
        for key in ("ATHEROMAP_SCDRS_WORK_DIR", "ATHEROMAP_GSMAP_WORK_DIR"):
            if not Path(os.environ[key]).resolve().is_relative_to(Path(temporary_root).resolve()):
                parser.error("Numerical tests require a temporary workspace")
    common = ["numpy", "pandas", "scipy", "scanpy", "anndata", "matplotlib", "seaborn",
              "skmisc", "numba", "h5py", "igraph", "leidenalg"]
    specific = ["scdrs", "harmonypy"] if args.group == "scdrs" else ["gsMap", "SpaGCN", "torch", "torch_geometric", "cv2", "louvain", "pyarrow", "gsMap.run_all_mode"]
    print(sys.version, flush=True)
    for name in common + specific:
        module = importlib.import_module(name)
        print(name, getattr(module, "__version__", "import OK"), flush=True)
    if args.group == "scdrs":
        run(["scdrs", "compute-score", "--help"])
        run(["scdrs", "perform-downstream", "--help"])
    else:
        run(["gsmap", "quick_mode", "--help"])
    if args.smoke:
        data = common_data()
        if args.group == "scdrs":
            scdrs_smoke(data, args.with_r)
        else:
            gsmap_smoke(data)


if __name__ == "__main__":
    main()
