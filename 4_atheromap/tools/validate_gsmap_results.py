#!/usr/bin/env python3
"""Audit real gsMap outputs against prepared H5AD and independent statistics."""
from __future__ import annotations
import argparse
import hashlib
import json
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse, unquote

import anndata as ad
import numpy as np
import pandas as pd
import scipy.sparse as sparse
from scipy.stats import norm, cauchy
from PIL import Image
from statsmodels.stats.multitest import multipletests


def check(value, message):
    if not value:
        raise ValueError(message)


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


class ReportParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.assets, self.tables, self.options, self.text = [], [], [], []
        self.table = None
        self.row = None
        self.cell = None
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ('img', 'script', 'link'):
            value = attrs.get('src') or attrs.get('href')
            if value:
                self.assets.append((tag, value))
        if tag == 'table':
            self.table = []
        if tag == 'tr' and self.table is not None:
            self.row = []
        if tag in ('th', 'td') and self.row is not None:
            self.cell = ''
        if tag == 'option':
            self.options.append(attrs.get('value'))
    def handle_data(self, data):
        self.text.append(data)
        if self.cell is not None:
            self.cell += data
    def handle_endtag(self, tag):
        if tag in ('th', 'td') and self.cell is not None:
            self.row.append(self.cell.strip())
            self.cell = None
        if tag == 'tr' and self.row is not None:
            self.table.append(self.row)
            self.row = None
        if tag == 'table' and self.table is not None:
            self.tables.append(self.table)
            self.table = None


def combined_p(values):
    values = np.asarray(values, dtype=float)
    if np.any(values == 0):
        return 0.0
    if np.any(values == 1):
        return 1.0
    contributions = np.empty_like(values)
    small = values < 1e-15
    contributions[small] = 1 / (np.pi * values[small])
    contributions[~small] = np.tan(np.pi * (0.5 - values[~small]))
    return float(cauchy.sf(np.mean(contributions)))


def validate_sample(root, sample, audit_dir):
    trait = 'GCST007435'
    base = root / 'results/gsmap_quick_mode/GSE241346' / sample
    source = root / f'data/spatial/GSE241346/h5ad/{sample}_gsmap_spagcn.h5ad'
    latent_path = base / f'find_latent_representations/{sample}_add_latent.h5ad'
    marker_path = base / f'latent_to_gene/{sample}_gene_marker_score.feather'
    ldsc_path = base / f'spatial_ldsc/{sample}_{trait}.csv.gz'
    cauchy_path = base / f'cauchy_combination/{sample}_{trait}.Cauchy.csv.gz'
    report_dir = base / f'report/{trait}'
    report_path = report_dir / f'{sample}_{trait}_gsMap_Report.html'
    diagnostic_path = report_dir / f'{sample}_{trait}_Gene_Diagnostic_Info.csv'
    required = [latent_path, marker_path, ldsc_path, cauchy_path, report_path, diagnostic_path]
    for path in required:
        check(path.is_file() and path.stat().st_size > 0, f'{sample}: missing {path}')
    original = ad.read_h5ad(source)
    latent = ad.read_h5ad(latent_path)
    check(original.obs_names.equals(latent.obs_names), f'{sample}: latent spot membership changed')
    check(original.var_names.equals(latent.var_names), f'{sample}: latent gene membership changed')
    check((sparse.csr_matrix(original.layers['count']) - sparse.csr_matrix(latent.layers['count'])).nnz == 0, f'{sample}: original count layer changed')
    check(np.array_equal(original.obsm['spatial'], latent.obsm['spatial']), f'{sample}: coordinates changed')
    labels = original.obs['annotation'].astype(str)
    check(np.array_equal(labels, latent.obs['annotation'].astype(str)), f'{sample}: annotations changed')
    for key, width in [('latent_GVAE', 30), ('latent_PCA', 300)]:
        values = latent.obsm[key]
        check(values.shape == (original.n_obs, width) and np.isfinite(values).all(), f'{sample}: invalid {key}')
        check(np.std(values) > 0, f'{sample}: constant {key}')
    check(np.isfinite(sparse.csr_matrix(latent.X).data).all(), f'{sample}: nonfinite normalized expression')
    marker = pd.read_feather(marker_path).set_index('HUMAN_GENE_SYM')
    expected_genes = original.var_names[~original.var_names.str.upper().str.startswith('MT-')]
    check(marker.index.is_unique and set(marker.index) == set(expected_genes), f'{sample}: marker gene mismatch')
    check(pd.Index(marker.columns).equals(original.obs_names), f'{sample}: marker spot mismatch')
    marker_values = marker.to_numpy()
    check(np.isfinite(marker_values).all() and (marker_values >= 0).all(), f'{sample}: invalid marker scores')
    check((marker_values > 0).any(axis=0).all(), f'{sample}: spot with no marker signal')
    ldsc = pd.read_csv(ldsc_path, dtype={'spot': str}).set_index('spot')
    check(list(ldsc.columns) == ['beta', 'se', 'z', 'p'], f'{sample}: LDSC columns invalid')
    check(ldsc.index.is_unique and set(ldsc.index) == set(original.obs_names), f'{sample}: LDSC spot coverage incomplete')
    check(np.isfinite(ldsc.to_numpy()).all() and ldsc.se.gt(0).all(), f'{sample}: invalid LDSC estimates')
    check(ldsc.p.gt(0).all() and ldsc.p.le(1).all(), f'{sample}: invalid P values')
    check(np.allclose(ldsc.z, ldsc.beta / ldsc.se, rtol=1e-9, atol=1e-12), f'{sample}: z != beta/se')
    check(np.allclose(ldsc.p, norm.sf(ldsc.z), rtol=1e-9, atol=1e-14), f'{sample}: P values do not match one-sided z test')
    ldsc = ldsc.loc[original.obs_names]
    ldsc['annotation'] = labels.to_numpy()
    ldsc['q_bh_within_sample'] = multipletests(ldsc.p, method='fdr_bh')[1]
    ldsc.to_csv(audit_dir / f'{sample}_spot_statistics.tsv', sep='\t')
    groups = pd.read_csv(cauchy_path, dtype={'annotation': str}).set_index('annotation')
    check(groups.index.is_unique and set(groups.index) == set(labels), f'{sample}: Cauchy groups missing or duplicated')
    check(np.isfinite(groups.to_numpy()).all() and groups.p_cauchy.between(0, 1).all(), f'{sample}: invalid group P values')
    rows = []
    for annotation in sorted(set(labels)):
        values = ldsc.loc[ldsc.annotation == annotation, 'p'].to_numpy()
        logp = -np.log10(values)
        cutoff = np.median(logp) + 3 * (np.percentile(logp, 75) - np.percentile(logp, 25))
        filtered = values[logp < cutoff]
        n_removed = len(values) - len(filtered)
        used = filtered if 0 < n_removed < max(0.01 * len(values), 20) else values
        expected_cauchy = combined_p(used)
        expected_median = float(np.median(values))
        check(np.isclose(groups.loc[annotation, 'p_cauchy'], expected_cauchy, rtol=1e-8, atol=1e-14), f'{sample}/{annotation}: Cauchy recomputation differs')
        check(np.isclose(groups.loc[annotation, 'p_median'], expected_median, rtol=1e-10, atol=1e-14), f'{sample}/{annotation}: median differs')
        rows.append(dict(sample=sample, annotation=annotation, n_spots=len(values), n_used_for_cauchy=len(used), outliers_removed=len(values)-len(used), p_cauchy=float(groups.loc[annotation, 'p_cauchy']), p_median=expected_median, p_min=float(values.min()), nominal_significant_spots=int((values < 0.05).sum())))
    grouped = pd.DataFrame(rows)
    grouped['q_bh_within_sample'] = multipletests(grouped.p_cauchy, method='fdr_bh')[1]
    grouped.to_csv(audit_dir / f'{sample}_group_statistics.tsv', sep='\t', index=False)
    diagnostic = pd.read_csv(diagnostic_path, dtype={'Annotation': str})
    check(len(diagnostic) >= 50 and diagnostic.Gene.is_unique, f'{sample}: invalid gene diagnostic table')
    check(diagnostic.Gene.isin(marker.index).all() and diagnostic.Annotation.isin(set(labels)).all(), f'{sample}: diagnostic IDs invalid')
    check(np.isfinite(diagnostic[['Median_GSS', 'PCC']].to_numpy()).all(), f'{sample}: nonfinite gene diagnostics')
    check(diagnostic.PCC.between(-1, 1).all() and diagnostic.PCC.is_monotonic_decreasing, f'{sample}: diagnostic correlations invalid')
    scores = marker.loc[diagnostic.Gene, original.obs_names].to_numpy(dtype=np.float64)
    centered = scores - scores.mean(axis=1, keepdims=True)
    y = -np.log10(ldsc.p.to_numpy())
    y -= y.mean()
    correlation = centered @ y / np.sqrt(np.square(centered).sum(axis=1) * np.square(y).sum())
    check(np.allclose(correlation, diagnostic.PCC, rtol=1e-6, atol=1e-8), f'{sample}: diagnostic PCC differs from spot associations')
    group_order = sorted(set(labels))
    medians = np.stack([np.median(scores[:, labels.to_numpy() == label], axis=1) for label in group_order], axis=1)
    check(np.allclose(medians.max(axis=1), diagnostic.Median_GSS, rtol=1e-6, atol=1e-8), f'{sample}: diagnostic median GSS differs')
    selected_medians = medians[np.arange(len(diagnostic)), pd.Index(group_order).get_indexer(diagnostic.Annotation)]
    check(np.allclose(selected_medians, medians.max(axis=1), rtol=1e-6, atol=1e-8), f'{sample}: diagnostic gene assigned to wrong group')
    html = report_path.read_text()
    parser = ReportParser()
    parser.feed(html)
    check(f'{sample} Genetic Spatial Mapping Report' in html, f'{sample}: report sample title incorrect')
    check('Genetic Spatial Mapping Plot' in html and 'Diagnosis Manhattan Plot' in html and 'Cauchy Combination Result' in html, f'{sample}: report sections missing')
    check(len(parser.tables) == 2 and len(parser.tables[0]) == len(groups)+1 and len(parser.tables[1]) == 51, f'{sample}: report tables incomplete')
    for row in parser.tables[0][1:]:
        check(len(row) == 3 and row[0] in groups.index, f'{sample}: report group table IDs invalid')
        check(np.isclose(float(row[1]), groups.loc[row[0], 'p_cauchy'], rtol=6e-5, atol=1e-14), f'{sample}: report group P differs')
        check(np.isclose(float(row[2]), groups.loc[row[0], 'p_median'], rtol=6e-5, atol=1e-14), f'{sample}: report group median differs')
    genes = (report_dir/'GSS_plot/plot_genes.csv').read_text().splitlines()
    check(genes == diagnostic.Gene.head(50).tolist() and parser.options == genes, f'{sample}: report selected genes inconsistent')
    pngs = []
    for gene in genes:
        for kind in ['Expression', 'GSS']:
            path = report_dir / f'GSS_plot/{sample}_{gene}_{kind}_Distribution.png'
            check(path.is_file(), f'{sample}: missing gene plot {path.name}')
            with Image.open(path) as im:
                check(im.width > 200 and im.height > 200, f'{sample}: plot too small {path.name}')
                check(np.asarray(im.convert('RGB').resize((64,64))).std() > 1, f'{sample}: blank image {path.name}')
                im.verify() if im.fp is not None else None
            pngs.append(path)
    external = []
    for tag, asset in parser.assets:
        if urlparse(asset).scheme in ['http', 'https']:
            external.append(asset)
        elif not asset.startswith('data:'):
            check((report_dir/unquote(asset.split('#')[0].split('?')[0])).is_file(), f'{sample}: broken local report asset {asset}')
    plot_csv = report_dir / f'gsMap_plot/{sample}_{trait}_gsMap_plot.csv'
    plot = pd.read_csv(plot_csv, index_col=0, dtype={'annotation': str})
    check(set(plot.index) == set(original.obs_names), f'{sample}: spatial plot misses spots')
    plot = plot.loc[original.obs_names]
    check(np.allclose(plot[['sx','sy']], original.obsm['spatial']) and np.allclose(plot.p, ldsc.p), f'{sample}: spatial plot does not match source/results')
    check(np.array_equal(plot.annotation.astype(str), labels), f'{sample}: spatial plot groups differ')
    files = required + pngs + [plot_csv]
    result = dict(sample=sample, status='passed', n_spots=original.n_obs, n_genes=original.n_vars, n_marker_genes=len(marker), n_groups=len(groups), ldsc_spot_coverage='100%', min_spot_p=float(ldsc.p.min()), max_spot_z=float(ldsc.z.max()), nominal_significant_spots=int(ldsc.p.lt(0.05).sum()), bh_significant_spots=int(ldsc.q_bh_within_sample.lt(0.05).sum()), nominal_significant_groups=int(grouped.p_cauchy.lt(0.05).sum()), bh_significant_groups=int(grouped.q_bh_within_sample.lt(0.05).sum()), diagnostic_genes=len(diagnostic), diagnostic_pcc_max_error=float(np.max(np.abs(correlation-diagnostic.PCC.to_numpy()))), report=str(report_path.relative_to(root)), gene_plot_count=len(pngs), report_external_assets=external, group_statistics=rows, files=[dict(path=str(p.relative_to(root)), bytes=p.stat().st_size, sha256=digest(p)) for p in files])
    print(json.dumps({k:v for k,v in result.items() if k not in ['files','group_statistics']}, ensure_ascii=False), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    audit_dir = root/'validation/gsmap_real_samples'
    audit_dir.mkdir(parents=True, exist_ok=True)
    results = [validate_sample(root, f'GSE241346_sample{i}', audit_dir) for i in (1,2)]
    report = dict(schema_version='1.0', stage='gsmap_real_sample_result_validation', status='passed', validated_at=datetime.now(timezone.utc).isoformat(), samples=results, statistical_notes=['Spatial LDSC P values are one-sided norm.sf(beta/se).','Cauchy combinations independently recomputed with the official median+3IQR outlier policy.','BH values are added in validation sidecars within each sample, separately for spots and groups.','Spatial annotations are SpaGCN domain IDs, not reviewed histopathology or cell types.'])
    (audit_dir/'result_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('Both real samples passed result and static report validation.', flush=True)


if __name__ == '__main__':
    main()
