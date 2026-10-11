#!/usr/bin/env python3
"""Read-only presence checks; does not import scientific packages or run analysis."""
from __future__ import annotations

import argparse
import os
from pathlib import Path


STAGES = (
    "scdrs-preprocess", "scdrs-annotate", "scdrs-prepare", "scdrs-score",
    "gsmap-prepare", "gsmap-run", "gsmap-domains",
)


def requirements(stage: str, root: Path) -> list[tuple[Path, str]]:
    """Return paths and their type. No directories are created."""
    if stage == "scdrs-preprocess":
        return [(root / name, "file") for name in
                ("matrix.mtx.gz", "features.tsv.gz", "barcodes.tsv.gz")]
    scdrs_files = {
        "scdrs-annotate": (
            "merged/GSE159677_filtered_batch_corrected.h5ad",
            "metadata/final_report_marker_manual.tsv",
        ),
        "scdrs-prepare": ("merged/GSE159677_harmony_highlevel_annotated_final.h5ad",),
        "scdrs-score": (
            "merged/GSE159677_for_scdrs_rawcount.h5ad",
            "metadata/GSE159677_scdrs_covariates.tsv",
            "scdrs_input/trait_gene_sets.gs",
        ),
    }
    if stage in scdrs_files:
        return [(root / name, "file") for name in scdrs_files[stage]]

    if stage == "gsmap-prepare":
        suffixes = (
            "matrix.mtx.gz", "features.tsv.gz", "barcodes.tsv.gz",
            "tissue_positions_list.csv.gz", "scalefactors_json.json.gz",
            "tissue_hires_image.png.gz",
        )
        return [(root / "data/spatial/GSE241346/raw" /
                 f"*{sample}*{suffix}", "unique_glob")
                for sample in ("GSM7727539", "GSM7727540") for suffix in suffixes]

    sample_names = ("GSE241346_sample1", "GSE241346_sample2")
    paths = [(root / "data/spatial/GSE241346/h5ad" /
              f"{sample}_gsmap_spagcn.h5ad", "file") for sample in sample_names]
    if stage == "gsmap-run":
        paths.append((root / "data/gwas/GCST007435_gsmap.sumstats.gz", "file"))
        resource = root / "resources/gsMap_resource"
        for relative, kind in (
            ("quick_mode/snp_gene_weight_matrix.h5ad", "file"),
            ("quick_mode/baseline", "exists"),
            ("quick_mode/SNP_gene_pair", "exists"),
            ("LDSC_resource/weights_hm3_no_hla", "exists"),
            ("LD_Reference_Panel/1000G_EUR_Phase3_plink", "exists"),
            ("genome_annotation/gtf/gencode.v46lift37.basic.annotation.gtf", "file"),
        ):
            paths.append((resource / relative, kind))
    elif stage == "gsmap-domains":
        for sample in sample_names:
            paths.extend([
                (root / "results/cell2location/spatial_mapping" / sample /
                 f"{sample}_means_cell_abundance_w_sf.csv", "file"),
                (root / "results/gsmap_quick_mode/GSE241346" / sample /
                 "cauchy_combination" / f"{sample}_GCST007435.Cauchy.csv.gz", "file"),
            ])
    return paths


def check(path: Path, kind: str) -> tuple[bool, str]:
    try:
        if kind == "unique_glob":
            hits = sorted(p for p in path.parent.rglob(path.name) if p.is_file())
            if len(hits) != 1:
                return False, f"expected exactly 1 matching file, found {len(hits)}"
            return hits[0].stat().st_size > 0, str(hits[0])
        if kind == "file":
            return path.is_file() and path.stat().st_size > 0, "nonempty file required"
        return path.exists(), "path must exist; directory contents are not checked"
    except OSError as error:
        return False, str(error)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=STAGES, required=True)
    parser.add_argument("--root", type=Path,
                        help="Override workspace (or raw matrix directory for scdrs-preprocess)")
    args = parser.parse_args()
    if args.stage == "scdrs-preprocess":
        env_name = "ATHEROMAP_SCDRS_INPUT_DIR"
    elif args.stage.startswith("scdrs-"):
        env_name = "ATHEROMAP_SCDRS_WORK_DIR"
    else:
        env_name = "ATHEROMAP_GSMAP_WORK_DIR"
    raw_root = args.root or os.environ.get(env_name)
    if not raw_root:
        parser.error(f"Set {env_name} or pass --root")
    root = Path(raw_root).expanduser().resolve()
    print(f"Stage: {args.stage}\nRoot: {root}")
    missing = 0
    for path, kind in requirements(args.stage, root):
        ok, detail = check(path, kind)
        missing += not ok
        print(f"{'OK' if ok else 'MISSING/INVALID'}\t{path}\t{detail}")
    print(f"Missing/invalid items: {missing}")
    print("Presence check only: contents, software compatibility and results are not validated.")
    if args.stage.startswith("scdrs-") and missing:
        print("Existing numbered server files may need review: see docs/FILE_MAP.md.")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
