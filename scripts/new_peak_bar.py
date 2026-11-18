"""Register a data-linked FSCV peak-current bar chart in FigLab."""
import argparse
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from figlab import paths, project
from figlab.render.engine import close, prepare
from figlab.spec.merge import build_spec, load_spec, save_spec


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="Source FSCV figure ID")
    parser.add_argument("figure", help="Peak bar chart ID")
    parser.add_argument("--title", default="FSCV · 峰值电流")
    parser.add_argument("--illustrative-error", type=float, default=0.0)
    args = parser.parse_args()
    for value in (args.source, args.figure):
        if not re.fullmatch(r"[\w-]{1,120}", value):
            parser.error("Invalid figure ID")
    if not math.isfinite(args.illustrative_error) or args.illustrative_error < 0:
        parser.error("Illustrative error must be finite and nonnegative")

    source = load_spec(args.source)
    breaks = source["data"].get("break_before_point", [])
    if source["data"].get("spectrum") != "fscv" or not breaks:
        parser.error("The FSCV source needs a recorded forward-sweep boundary")
    concentrations = {}
    for item in source["series"]:
        if item["include"]:
            label = re.search(r"(\d+(?:\.\d+)?)\s*[μµu]M$", item["curve"])
            if label is None:
                parser.error(f"Missing concentration in {item['curve']}")
            concentrations[item["curve"]] = float(label[1])
    if not concentrations:
        parser.error("Source has no included curves")
    levels = sorted(set(concentrations.values()))
    if len(levels) != len(concentrations):
        parser.error("The peak bar template needs one source curve per concentration")
    spacing = min((right - left for left, right in zip(levels, levels[1:])), default=0.25)

    data = project.load()
    entries = {item["id"]: item for item in data["figures"]}
    path = Path(paths.spec_file(args.figure))
    entry = entries.get(args.figure)
    if args.source not in entries:
        parser.error("Source figure is absent from the project")
    if path.exists() and not (entry and (entry["preset"] in {"artwork", "fscv_peak_bar"}
                                        or load_spec(args.figure).get("data", {}).get("fscv_peak_bar"))):
        parser.error("Figure ID already belongs to another chart")
    spec = build_spec(args.figure, source["data"]["dataset"], list(concentrations), spectrum="fscv",
                      note="Each bar is the maximum included current on the forward sweep.")
    spec["series"] = [item for item in source["series"] if item["curve"] in concentrations]
    spec["data"].update(working_csv=source["data"]["working_csv"], break_before_point=breaks,
                        fscv_peak_bar=dict(concentrations=concentrations, width_uM=spacing * .43,
                                           illustrative_error_nA=args.illustrative_error))
    spec["axis"].update(x_title="Concentration (µM)", y_title="Peak current (nA)")
    spec["layer"].update(left=21, top=8, width=69, height=66)
    spec["style"].update(grid=False, equal_aspect=False)
    spec["style"].pop("fscv_peak_table_curve", None)
    spec["export"].update(base="FSCV peak current", auto_name=False)
    built = prepare(spec)
    close(built)
    save_spec(spec, register=False)
    if entry is None:
        project.ensure(args.figure, spec["preset"], args.title, folder=entries[args.source]["folder"])
        return
    entry["preset"] = spec["preset"]
    entry.pop("peak_bar", None)
    project.save(data)


if __name__ == "__main__":
    main()
