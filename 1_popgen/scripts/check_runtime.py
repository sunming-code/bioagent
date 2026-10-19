"""Fail early when reference files or executable environments are incomplete."""
from pathlib import Path
import argparse
import sys
import subprocess
import os

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runtime import environment_prefix, command_env

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--software-only", action="store_true", help="Check environments before reference data are prepared")
args = parser.parse_args()

for name, modules, binaries in [
    ("popgen", ["pandas", "numpy"], ["nextflow", "bcftools", "samtools", "bwa", "plink2", "fastqc"]),
    ("popgen_analysis", ["pysam", "pandas", "numpy", "jsonschema"], ["plink", "plink2", "bcftools", "admixture"]),
    ("popgen_gnn", ["torch", "torch_geometric", "sklearn", "scipy", "fastapi", "uvicorn", "multipart", "jsonschema"], ["bcftools"]),
]:
    prefix = environment_prefix(name)
    subprocess.run([str(prefix / "bin/python"), "-c", "; ".join(f"import {m}" for m in modules)], check=True, env=command_env(name))
    for binary in binaries:
        executable = prefix / "bin" / binary
        assert executable.is_file(), f"Missing {name}/{binary}"
        version_arg = "-version" if binary == "nextflow" else "--version"
        result = subprocess.run([str(executable), version_arg],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                env=command_env(name), check=False)
        # bwa prints its version and exits with status 1 by design.
        if binary != "bwa" and result.returncode != 0:
            raise RuntimeError(f"{name}/{binary} failed its version check: {result.returncode}")
    print(name, prefix, "OK")
if args.software_only:
    raise SystemExit(0)
panel = ROOT / "data/reference/panel_1000g/ref_1000g_pruned"
for suffix in (".bed", ".bim", ".fam", ".pop"):
    assert Path(str(panel) + suffix).is_file(), f"Missing {panel}{suffix}"
vcf_dir = Path(os.environ.get(
    "POPGEN_1000G_VCF_DIR",
    str(ROOT / "data/1000GP/20220422_3202_phased_SNV_INDEL_SV"),
)).expanduser()
for chrom in range(1, 23):
    vcf = vcf_dir / f"1kGP_high_coverage_Illumina.chr{chrom}.filtered.SNV_INDEL_SV_phased_panel.vcf.gz"
    assert vcf.is_file() and Path(str(vcf) + ".tbi").is_file(), f"Missing {vcf} or index"
assert (ROOT / "steps/03_gnn/model.pt").is_file()
print("Reference panel, model, and chr1-chr22 indexed VCFs OK")
