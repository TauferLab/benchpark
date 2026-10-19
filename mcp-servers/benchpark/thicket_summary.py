# Copyright 2023 Lawrence Livermore National Security, LLC and other
# Benchpark Project Developers. See the top-level COPYRIGHT file for details.
#
# SPDX-License-Identifier: Apache-2.0
"""Print a JSON summary of Caliper profiles. Used by server.py's profile_summary.

usage: thicket_summary.py <path> <metric> <top_n> [region_regex]
"""

import json
import re
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")


def main():
    path, metric, top_n = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3])
    region_rx = re.compile(sys.argv[4]) if len(sys.argv) > 4 and sys.argv[4] else None

    files = (
        [str(path)] if path.is_file() else sorted(str(p) for p in path.rglob("*.cali"))
    )
    if not files:
        sys.exit(f"No .cali files under {path}")

    import thicket as tt

    tk = tt.Thicket.from_caliperreader(files, disable_tqdm=True)
    df = tk.dataframe.reset_index()
    if metric not in df.columns:
        numeric = [c for c in df.columns if df[c].dtype.kind in "fi"]
        sys.exit(f"Metric '{metric}' not found. Available metrics: {numeric}")

    df["region"] = df["node"].apply(lambda n: n.frame.get("name"))
    if region_rx:
        df = df[df["region"].astype(str).str.contains(region_rx)]
    stats = df.groupby("region")[metric].agg(["mean", "min", "max", "count"])
    stats = stats.sort_values("mean", ascending=False).head(top_n)

    md = tk.metadata
    varying, constant = {}, {}
    for col in md.columns:
        try:
            uniq = md[col].dropna().astype(str).unique()
        except TypeError:
            continue
        if len(uniq) == 1:
            constant[col] = uniq[0][:120]
        elif 1 < len(uniq) <= 50:
            varying[col] = sorted(uniq.tolist())[:20]

    print(
        json.dumps(
            {
                "files": len(files),
                "profiles": len(tk.profile),
                "regions": len(tk.graph),
                "metric": metric,
                "top_regions": [
                    {
                        "region": r,
                        **{
                            k: (round(float(v), 6) if k != "count" else int(v))
                            for k, v in row.items()
                        },
                    }
                    for r, row in stats.iterrows()
                ],
                "metadata_varying": varying,
                "metadata_constant": {k: constant[k] for k in list(constant)[:40]},
            }
        )
    )


if __name__ == "__main__":
    main()
