"""Run-time controls shared by the PopGen CLI, platform CLI and submission form."""
import math

DEFAULTS = {"popgen_af_percent": 1.0, "popgen_min_dp": None, "popgen_min_gq": None,
            "popgen_keep_missing_quality": False, "popgen_cv_max_k": 10}


def add_arguments(parser):
    parser.add_argument("--popgen-af-percent", type=float, help="复核清单的匹配人群 ALT 频率上限（百分比，严格小于）")
    parser.add_argument("--popgen-min-dp", type=int, help="复核清单的最低样本深度")
    parser.add_argument("--popgen-min-gq", type=int, help="复核清单的最低基因型质量")
    parser.add_argument("--popgen-keep-missing-quality", action="store_true", default=None,
                        help="设置 DP/GQ 下限时，仍保留相应质量值缺失的记录")
    parser.add_argument("--popgen-cv-max-k", type=int, help="无监督 ADMIXTURE 从 K=2 开始搜索的上限（2–10）")


def validated(values):
    result = {key: values[key] if values.get(key) is not None else default for key, default in DEFAULTS.items()}
    af = result["popgen_af_percent"]
    if type(af) not in (int, float) or not 0 <= af <= 100 or not math.isfinite(af):
        raise ValueError("PopGen 复核频率阈值必须是 0–100 的百分比")
    for key in ("popgen_min_dp", "popgen_min_gq"):
        n = result[key]
        if n is not None and (type(n) is not int or n < 0):
            raise ValueError(f"{key} 必须是非负整数或留空")
    if type(result["popgen_keep_missing_quality"]) is not bool:
        raise ValueError("保留缺失质量必须为布尔值")
    k = result["popgen_cv_max_k"]
    if type(k) is not int or not 2 <= k <= 10:
        raise ValueError("PopGen 无监督 CV 的最大 K 必须是 2–10 的整数")
    if values.get("skip_cv") and k != DEFAULTS["popgen_cv_max_k"]:
        raise ValueError("已跳过无监督 CV，无法应用自定义 K 上限")
    return result


def cli_options(values):
    options = []
    for key in DEFAULTS:
        if key == "popgen_cv_max_k" and values.get("skip_cv"):
            continue
        value = values.get(key)
        if value is not None and value is not False:
            options.append("--" + key.replace("_", "-"))
            if value is not True:
                options.append(str(value))
    return options
