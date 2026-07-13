#!/usr/bin/env python
"""Audit G2 cascades at the frozen calibration/evaluation boundary."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from aptadynamic_eg import automatic_only_with_audit, cascades, load_bpa
from aptadynamic_eg.h4 import cascade_boundary_audit


CALIBRATION_END = pd.Timestamp("2011-01-01T00:00:00Z")


def build_audit(outages: Path) -> dict:
    loaded = load_bpa(outages)
    filtered, filter_record = automatic_only_with_audit(
        loaded, require_column=True
    )
    events = cascades(filtered)
    payload = cascade_boundary_audit(
        events, int(CALIBRATION_END.timestamp())
    )
    payload["calibration_end_exclusive_utc"] = CALIBRATION_END.isoformat()
    payload["outage_filter"] = filter_record
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("outages", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = build_audit(args.outages)
    rendered = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
        print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
