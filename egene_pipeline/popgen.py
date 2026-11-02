"""Include original PopGen evidence and an offline report in integrated delivery."""
from html import escape
from importlib import import_module
from pathlib import Path
import shutil

from .common import digest, read_json


def deliver_popgen(delivery, stages, egene_files, sample_id):
    folder = delivery / "popgen"
    folder.mkdir()
    record = stages.get("popgen")
    pack_path = None
    if record:
        spec = record["artifact"]
        pack_path = Path(spec["path"])
    else:
        # Reports resumed at e-Gene still carry the verified original input spec.
        provenance = egene_files.get("provenance/prepared_manifest.source.json")
        spec = (read_json(provenance).get("inputs", {}).get("evidence_pack") if provenance else None)
        if spec and Path(spec["path"]).is_file():
            pack_path = Path(spec["path"])
    if pack_path is None:
        (folder / "report.html").write_text(
            '<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>PopGen 报告未提供</title><h1>PopGen 报告未提供</h1>'
            f'<p>样本：{escape(sample_id)}</p><p>本次从下游结果开始，未找到可验证的原始 PopGen 证据包。'
            '无法展示本次 PopGen 祖源、频率和 GNN 结论。</p></html>', encoding="utf-8")
        return "unavailable"
    if pack_path.stat().st_size != spec["bytes"] or digest(pack_path) != spec["sha256"]:
        raise ValueError("最终交付的 PopGen 证据包完整性校验失败")
    pack = read_json(pack_path)
    if pack["metadata"]["sample_id"] != sample_id or pack["metadata"].get("genome_build") != "GRCh38":
        raise ValueError("PopGen 与 e-Gene/GDgpt 的样本或基因组版本不一致")
    reporter = import_module("1_popgen.reporting")
    for relative in {"evidence_pack.json", "INTERFACE.md", "allele_freq.tsv", "../patient.vcf.gz",
                     *[rel for key, rel in pack.get("files", {}).items() if rel and key != "report"]}:
        source = (pack_path.parent / relative).resolve(strict=True)
        target = (folder / relative).resolve()
        # Keep original ../patient.vcf.gz and analysis references working after unzip.
        if Path(relative).is_absolute() or not target.is_relative_to(delivery.resolve()) or (
                target.parent != delivery.resolve() and not target.is_relative_to(folder.resolve())):
            raise ValueError(f"PopGen 交付路径越界: {relative}")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and digest(target) != digest(source):
            raise ValueError(f"PopGen 交付路径冲突: {relative}")
        shutil.copyfile(source, target)
    reporter.generate_report(folder / "evidence_pack.json", folder / "report.html")
    # Preserve the pack's report reference as well as the integrated report URL.
    if pack.get("files", {}).get("report") == "popgen_report.html":
        shutil.copyfile(folder / "report.html", folder / "popgen_report.html")
    return "complete"
