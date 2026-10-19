#!/usr/bin/env python
"""Validate prepared inputs against source counts, source GWAS, and 22-chr resources.
Run using the atheromap_gsmap environment; does not run gsMap association analysis.
"""
import argparse
import gzip
import json
from datetime import datetime, timezone
from pathlib import Path

import anndata as ad
import h5py
import numpy as np
import pandas as pd
import pyarrow.feather as feather
import scipy.sparse as sparse
from scipy.io import mmread
from scipy.stats import chi2
from gsMap.utils.regression_read import _read_sumstats


def require(condition, message):
    if not condition:
        raise ValueError(message)


def check_spatial(root, ref_genes):
    rows = []
    raw = root / 'data/spatial/GSE241346/raw'
    for sample, geo in [('sample1', 'GSM7727539'), ('sample2', 'GSM7727540')]:
        prefix = f'GSE241346_{sample}'
        path = root / f'data/spatial/GSE241346/h5ad/{prefix}_gsmap_spagcn.h5ad'
        a = ad.read_h5ad(path)
        require(a.n_obs > 0 and a.n_vars > 0, f'{sample}: empty H5AD')
        require(a.obs_names.is_unique and a.var_names.is_unique, f'{sample}: duplicate IDs')
        require('count' in a.layers and 'annotation' in a.obs and 'spatial' in a.obsm, f'{sample}: required fields missing')
        count = sparse.csr_matrix(a.layers['count'])
        require(np.isfinite(count.data).all() and (count.data >= 0).all() and np.equal(count.data, np.rint(count.data)).all(), f'{sample}: counts invalid')
        require((sparse.csr_matrix(a.X) - count).nnz == 0, f'{sample}: X changed from counts')
        require(a.obs['annotation'].notna().all() and a.obs['annotation'].astype(str).str.len().gt(0).all(), f'{sample}: missing domains')
        require(np.array_equal(a.obs['annotation'].astype(str), a.obs['spagcn_refined'].astype(str)), f'{sample}: domain labels inconsistent')
        require(a.obsm['spatial'].shape == (a.n_obs, 2) and np.isfinite(a.obsm['spatial']).all(), f'{sample}: spatial coordinates invalid')
        def find(suffix):
            paths = list(raw.glob(f'*{geo}*{suffix}'))
            require(len(paths) == 1, f'{sample}: ambiguous source {suffix}')
            return paths[0]
        with gzip.open(find('matrix.mtx.gz'), 'rb') as fh:
            original = mmread(fh).T.tocsr()
        features = pd.read_csv(find('features.tsv.gz'), sep='\t', header=None)
        barcodes = pd.Index(pd.read_csv(find('barcodes.tsv.gz'), sep='\t', header=None)[0].astype(str))
        symbols = pd.Index(features.iloc[:, 1].astype(str))
        unique, codes = np.unique(symbols, return_inverse=True)
        group = sparse.csr_matrix((np.ones(len(codes), dtype=np.int64), (np.arange(len(codes)), codes)), shape=(len(codes), len(unique)))
        collapsed = original @ group
        positions = pd.read_csv(find('tissue_positions_list.csv.gz'), header=None, names=['barcode', 'in_tissue', 'array_row', 'array_col', 'pxl_row_in_fullres', 'pxl_col_in_fullres']).set_index('barcode')
        tissue = positions.reindex(barcodes)['in_tissue'].eq(1).to_numpy()
        good = tissue & (np.asarray(collapsed.sum(axis=1)).ravel() >= 100) & (np.asarray((collapsed > 0).sum(axis=1)).ravel() >= 50)
        expected_barcodes = barcodes[good]
        require(set(a.obs_names) == set(expected_barcodes), f'{sample}: retained spots differ from raw QC')
        good_genes = np.asarray((collapsed[good] > 0).sum(axis=0)).ravel() >= 3
        require(set(a.var_names) == set(unique[good_genes]), f'{sample}: retained genes differ from raw QC')
        expected = collapsed[barcodes.get_indexer(a.obs_names)][:, pd.Index(unique).get_indexer(a.var_names)]
        require((expected - count).nnz == 0, f'{sample}: count values differ from original source')
        aligned_pos = positions.loc[a.obs_names]
        require(aligned_pos.in_tissue.eq(1).all(), f'{sample}: off-tissue spots present')
        require(np.array_equal(a.obsm['spatial'], aligned_pos[['pxl_col_in_fullres', 'pxl_row_in_fullres']].to_numpy()), f'{sample}: coordinates differ from source')
        require(np.array_equal(a.obs.total_counts, np.asarray(count.sum(axis=1)).ravel()), f'{sample}: total counts invalid')
        require(np.array_equal(a.obs.n_genes_by_counts, np.asarray((count > 0).sum(axis=1)).ravel()), f'{sample}: gene counts invalid')
        annotation = pd.read_csv(root / f'data/spatial/GSE241346/metadata/{prefix}_spagcn_annotation.tsv', sep='\t', index_col=0)
        require(annotation.index.equals(a.obs_names) and np.array_equal(annotation.annotation.astype(str), a.obs.annotation.astype(str)), f'{sample}: annotation TSV differs')
        overlap = int(a.var_names.isin(ref_genes).sum())
        require(overlap > 0, f'{sample}: no reference gene overlap')
        record = dict(sample=sample, geo_id=geo, h5ad=str(path.relative_to(root)), raw_spots=original.shape[0], raw_features=original.shape[1], tissue_spots=int(tissue.sum()), retained_spots=a.n_obs, retained_genes=a.n_vars, domains=a.obs.annotation.astype(str).value_counts().sort_index().to_dict(), reference_gene_overlap=overlap, count_sum=int(count.sum()), source_counts_exact=True, source_coordinates_exact=True, qc_membership_exact=True)
        rows.append(record)
        print(json.dumps(record), flush=True)
    return rows


def check_gwas(root, resources):
    path = root / 'data/gwas/GCST007435_gsmap.sumstats.gz'
    out = pd.read_csv(path, sep='\t')
    require(list(out.columns) == ['SNP', 'A1', 'A2', 'Z', 'N', 'Chr', 'Pos'], 'GWAS columns invalid')
    require(out.notna().all().all() and out.SNP.is_unique, 'GWAS missing values or duplicate rsIDs')
    require(out.SNP.str.fullmatch(r'rs[0-9]+').all(), 'GWAS rsIDs invalid')
    require(np.isfinite(out[['Z', 'N', 'Chr', 'Pos']]).all().all(), 'GWAS nonfinite values')
    require(out.N.gt(0).all() and out.N.eq(np.rint(out.N)).all() and out.Pos.gt(0).all(), 'GWAS N or positions invalid')
    require(set(out.Chr) == set(range(1, 23)), 'GWAS chromosomes incomplete')
    valid = {'AC', 'AG', 'CA', 'CT', 'GA', 'GT', 'TC', 'TG'}
    require((out.A1 + out.A2).isin(valid).all(), 'GWAS ambiguous or invalid alleles')
    out = out.set_index('SNP')
    exclusion_file = root / 'preparation/reference_exclusions.json'
    exclusions = json.loads(exclusion_file.read_text()) if exclusion_file.exists() else {}
    excluded = set(exclusions.get('removed_rsids', []))
    require(not out.index.isin(excluded).any(), 'LD-incompatible rsIDs remain in final GWAS')
    matched = np.zeros(len(out), dtype=bool)
    source_rows = 0
    expected_rows = 0
    max_z_error = 0.0
    for src in pd.read_csv(root / 'data/gwas/GCST007435.tsv.gz', sep='\t', chunksize=500000):
        source_rows += len(src)
        # Preserve the formatter's floating point calculation at the 1% boundary.
        freq = src.effect_allele_frequency
        maf = np.minimum(freq, 1 - freq)
        expected = src.notna().all(axis=1) & (src.effect_allele + src.other_allele).str.upper().isin(valid) & freq.between(0, 1) & maf.gt(0.01) & src.p_value.gt(0) & src.p_value.le(1) & src.n.ge(32290) & ~src.rs_id.isin(excluded)
        src = src.loc[expected]
        expected_rows += len(src)
        idx = out.index.get_indexer(src.rs_id)
        require((idx >= 0).all() and not matched[idx].any(), 'GWAS source membership differs or duplicate source SNP')
        matched[idx] = True
        target = out.iloc[idx]
        for original, converted in [('effect_allele', 'A1'), ('other_allele', 'A2'), ('n', 'N'), ('chromosome', 'Chr'), ('base_pair_location', 'Pos')]:
            require(np.array_equal(src[original].to_numpy(), target[converted].to_numpy()), f'GWAS changed source {original}')
        expected_z = np.sqrt(chi2.isf(src.p_value.to_numpy(), 1)) * np.where(src.beta.to_numpy() < 0, -1, 1)
        error = float(np.max(np.abs(target.Z.to_numpy() - expected_z))) if len(src) else 0.0
        max_z_error = max(max_z_error, error)
        require(error <= 0.00050001, 'GWAS signed Z differs from source P/beta beyond formatter rounding')
        print(f'GWAS source rows checked: {source_rows:,}', flush=True)
    require(matched.all() and expected_rows == len(out), f'GWAS membership: expected={expected_rows}, matched={int(matched.sum())}, output={len(out)}')
    parsed = _read_sumstats(str(path), alleles=True, dropna=False)
    require(len(parsed) == len(out) and parsed.notna().all().all(), 'gsMap parser failed round trip')
    del parsed
    baseline = []
    weights = []
    ld_rows = 0
    ld_overlap = 0
    position_mismatches = 0
    allele_mismatches = 0
    mismatch_examples = []
    complement = str.maketrans('ACGT', 'TGCA')
    for chrom in range(1, 23):
        base = resources / f'quick_mode/baseline/baseline.{chrom}.l2.ldscore.feather'
        baseline.extend(feather.read_table(base, columns=['SNP']).column('SNP').to_pylist())
        weight = pd.read_csv(resources / f'LDSC_resource/weights_hm3_no_hla/weights.{chrom}.l2.ldscore.gz', sep=r'\s+', usecols=['SNP'])
        weights.extend(weight.SNP)
        prefix = resources / f'LD_Reference_Panel/1000G_EUR_Phase3_plink/1000G.EUR.QC.{chrom}'
        for suffix in ['.bed', '.bim', '.fam']:
            require(Path(str(prefix) + suffix).stat().st_size > 0, f'Missing LD chr{chrom}{suffix}')
        for suffix in ['.l2.M', '.l2.M_5_50']:
            require((resources / f'quick_mode/baseline/baseline.{chrom}{suffix}').stat().st_size > 0, f'Missing baseline chr{chrom}{suffix}')
        pair = feather.read_table(resources / f'quick_mode/SNP_gene_pair/SNP_gene_pair_chr{chrom}.feather', columns=['CHR'])
        require(pair.num_rows > 0 and np.all(pair.column('CHR').to_numpy() == chrom), f'Invalid SNP-gene chromosome {chrom}')
        bim = pd.read_csv(str(prefix) + '.bim', sep=r'\s+', header=None, names=['Chr', 'SNP', 'CM', 'Pos', 'A1', 'A2'])
        ld_rows += len(bim)
        idx = out.index.get_indexer(bim.SNP)
        keep = idx >= 0
        b = bim.loc[keep].reset_index(drop=True)
        t = out.iloc[idx[keep]].reset_index()
        ld_overlap += len(b)
        bad_pos = b.Chr.ne(t.Chr) | b.Pos.ne(t.Pos)
        position_mismatches += int(bad_pos.sum())
        allele = t.A1 + t.A2
        ref = b.A1 + b.A2
        ok_allele = allele.eq(ref) | allele.eq(ref.str[::-1]) | allele.eq(ref.str.translate(complement)) | allele.eq(ref.str.translate(complement).str[::-1])
        allele_mismatches += int((~ok_allele).sum())
        if len(mismatch_examples) < 10:
            mismatch_examples.extend(t.loc[bad_pos | ~ok_allele, ['SNP', 'Chr', 'Pos', 'A1', 'A2']].head(10-len(mismatch_examples)).to_dict('records'))
    common = out.index.intersection(pd.Index(baseline)).intersection(pd.Index(weights))
    require(len(common) > 0, 'No GWAS/baseline/weight intersection')
    require((resources / 'genome_annotation/gtf/gencode.v46lift37.basic.annotation.gtf').stat().st_size > 0, 'Missing GRCh37 GTF')
    if excluded:
        require(position_mismatches == 0 and allele_mismatches == 0, 'Reference-incompatible GWAS records remain after exclusion')
    result = dict(source_rows=source_rows, retained_snps=len(out), removed_snps=source_rows-len(out), columns=['SNP', 'A1', 'A2', 'Z', 'N', 'Chr', 'Pos'], chromosomes=sorted(out.Chr.unique().tolist()), genome_build='GRCh37', sample_size_source='per-variant source n column', n_min=float(out.N.min()), n_median=float(out.N.median()), n_max=float(out.N.max()), n_unique=int(out.N.nunique()), n_filter_threshold=32290, signed_z_method='sign(beta; beta=0 treated positive) * sqrt(chi2.isf(p_value, df=1)); official formatter, rounded to 3 decimals', max_signed_z_rounding_error=max_z_error, source_fields_exact=True, source_membership_exact=True, gsmap_reader_roundtrip=True, baseline_snps=len(baseline), weight_snps=len(weights), regression_snp_intersection=len(common), ld_reference_rows=ld_rows, ld_reference_overlap=ld_overlap, ld_coordinate_mismatches=position_mismatches, ld_allele_mismatches_including_strand_and_swap=allele_mismatches, mismatch_examples=mismatch_examples, reference_chromosomes_checked=22)
    result['excluded_for_ld_reference_alignment'] = len(excluded)
    result['official_formatter_retained_snps'] = exclusions.get('official_formatter_rows', len(out))
    result['reference_exclusions'] = 'preparation/reference_exclusions.json' if exclusions else None
    print(json.dumps(result), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument('--stage', choices=['spatial', 'gwas', 'all'], default='all')
    args = parser.parse_args()
    root = args.root.resolve()
    resources = root / 'resources/gsMap_resource'
    report = dict(validated_at=datetime.now(timezone.utc).isoformat(), stage=args.stage, status='passed', workspace=str(root))
    if args.stage in ['spatial', 'all']:
        with h5py.File(resources / 'quick_mode/snp_gene_weight_matrix.h5ad') as handle:
            genes = pd.Index(handle['var/Gene'].asstr()[:])
        report['spatial'] = check_spatial(root, genes)
    if args.stage in ['gwas', 'all']:
        report['gwas'] = check_gwas(root, resources)
    output = root / f'preparation/validation_{args.stage}.json'
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    print(f'Validation passed: {output}', flush=True)


if __name__ == '__main__':
    main()
