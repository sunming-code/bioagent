"""Run the pinned InterVar with an isolated scalar-type compatibility adapter."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys


def install_scalar_adapter(module):
    """Upstream assign() stores BA1/PVS1 overrides as str; classfy() compares ints.

    Cast only at the classifier boundary. The pinned vendor source, evidence
    selection and ACMG2015 combination rules are otherwise unchanged.
    """
    original = module.classfy
    counter = {"BA1": 0, "PVS1": 0}

    def classify(pvs1, ps, pm, pp, ba1, bs, bp, allele_flags, columns):
        for code, value in (("PVS1", pvs1), ("BA1", ba1)):
            if type(value) is not int:
                counter[code] += 1
            if str(value) not in {"0", "1"}:
                raise ValueError(f"Invalid {code} scalar from InterVar: {value!r}")
        return original(int(pvs1), ps, pm, pp, int(ba1), bs, bp, allele_flags, columns)

    module.classfy = classify
    return counter


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--script", required=True, type=Path)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("pinned_intervar", args.script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    counter = install_scalar_adapter(module)
    sys.argv = [str(args.script), "--config", "config.ini", "--input", "input.avinput",
                "--input_type", "AVinput", "--output", "patient", "--skip_annovar"]
    try:
        module.main()
    except SystemExit as error:
        # Upstream sometimes exits with code 0 on missing files; this worker has
        # no informational command, so any premature exit is an execution failure.
        raise RuntimeError(f"InterVar exited before completing: {error.code}") from error
    if not Path("patient.hg38_multianno.txt.intervar").is_file():
        raise RuntimeError("InterVar did not produce its output")
    Path("worker_status.json").write_text(json.dumps({"status": "complete", "scalar_coercions": counter}) + "\n")


if __name__ == "__main__":
    main()
