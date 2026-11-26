"""Compare all nine scientific defaults with this iteration's actual pre-change baseline."""

import argparse
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def baseline_metrics(path):
    source = json.loads(path.read_text(encoding="utf-8"))
    if source.get("status") != "pass":
        raise ValueError("baseline SDK evidence must have passed")
    def metrics(run):
        return run["outputs"]["metrics"]

    output = {}
    for transport in ("stdio", "http"):
        report = source[transport]
        output[transport] = {"old_run": metrics(report["run"]), "knee": metrics(report["knee"]["run"]),
                             "forward": metrics(report["forward"]["run"])}
        for version in ("v03", "v04", "v05"):
            output[transport][version] = {name: metrics(record["run"])
                                          for name, record in report[version].items() if "run" in record}
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-e2e", type=Path, default=os.environ.get("HMM_VISUAL_BASELINE_E2E"))
    args = parser.parse_args()
    baseline = (baseline_metrics(args.baseline_e2e) if args.baseline_e2e else
                json.loads((ROOT / "reports/V06_BASELINE_NUMERICS.json").read_text()))
    current = json.loads((ROOT / "reports/e2e.json").read_text())
    cases = {}
    for transport in ("stdio", "http"):
        section = current[transport]
        runs = {
            "old_run": section["run"],
            "knee": section["knee"]["run"],
            "forward": section["forward"]["run"],
        }
        expected = {k: baseline[transport][k] for k in runs}
        for version in ("v03", "v04", "v05"):
            for name, metrics in baseline[transport][version].items():
                key = version + "/" + name
                runs[key] = section[version][name]["run"]
                expected[key] = metrics
        for name, run in runs.items():
            actual = {m["name"]: m for m in run["outputs"]["metrics"]}
            errors = []
            for metric in expected[name]:
                got = actual[metric["name"]]
                assert got["unit"] == metric["unit"]
                error = abs(got["value"] - metric["value"])
                assert error <= 1e-10, (name, metric, got)
                errors.append(error)
            cases[transport + "/" + run["scenario_id"]] = {
                "status": "pass",
                "max_absolute_metric_difference": max(errors),
                "run_id": run["run_id"],
                "units": "each metric's recorded physical unit",
            }
    assert len(cases) == 18
    evidence = {
        "status": "pass",
        **({"baseline_report": args.baseline_e2e.name} if args.baseline_e2e else {
            "baseline_head": "03ad1df34cf7ee95b4cfcef107960f9d5a5e0190",
            "baseline_store": "reports/e2e-model-runs/3bf66c23fc6fe5d0",
        }),
        "absolute_guard": 1e-10,
        "cases": cases,
    }
    (ROOT / "reports/V06_NUMERIC_REGRESSION.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
