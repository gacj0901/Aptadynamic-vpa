"""
scripts/data_acquisition/convert_bpa_to_csv.py
================================================

Converts Dobson's outagesBPA.txt (Mathematica Association format) to CSV.

Format: each outage is a Mathematica Association <| ... |> with named fields:
  <| "OutDatetime" -> DateObject[{...}],
     "Name" -> "Reedsport-Fairview No 1 115kV line",
     "OutageType" -> "Auto",
     ... |>

The file is ~46 MB; we load it fully into memory and scan linearly.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from pathlib import Path
from typing import Iterator, List


EXPECTED_FIELDS = [
    "OutDatetime", "InDatetime", "Name", "Voltage", "LineType", "GenFlag",
    "Length", "Duration", "OutageType", "DispatcherCause", "FieldCause",
    "District", "OutageID", "InputCategory", "InputYear", "InputFilename",
    "NameClean", "BusNames", "UnitNumber", "LineName", "OutAbstime",
    "InAbstime", "TimeZone", "Reactance",
]


def find_associations(text: str) -> List[tuple]:
    """Find all top-level <|...|> association blocks. Returns list of (start, end) offsets.
    
    Single linear pass with proper string and depth tracking.
    """
    boundaries = []
    n = len(text)
    i = 0
    in_string = False
    escape = False
    depth = 0
    assoc_start = -1
    
    while i < n:
        c = text[i]
        
        # Handle string state
        if in_string:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_string = False
            i += 1
            continue
        
        if c == '"':
            in_string = True
            i += 1
            continue
        
        # Look for <| and |>
        if c == "<" and i + 1 < n and text[i + 1] == "|":
            if depth == 0:
                assoc_start = i
            depth += 1
            i += 2
            continue
        
        if c == "|" and i + 1 < n and text[i + 1] == ">":
            depth -= 1
            i += 2
            if depth == 0 and assoc_start >= 0:
                boundaries.append((assoc_start, i))
                assoc_start = -1
            continue
        
        i += 1
    
    return boundaries


def parse_value(s: str) -> str:
    """Convert a Mathematica value to a CSV-safe string."""
    s = s.strip()
    
    # DateObject[{Y, M, D, H, M, S}, ...]
    m = re.match(r"DateObject\[\s*\{(\d+),\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)\}", s)
    if m:
        y, mo, d, h, mi, se = [int(x) for x in m.groups()]
        return f"{y:04d}-{mo:02d}-{d:02d} {h:02d}:{mi:02d}:{se:02d}"
    
    # "string"
    if len(s) >= 2 and s.startswith('"') and s.endswith('"'):
        return s[1:-1]
    
    # {list, items}
    if s.startswith("{") and s.endswith("}"):
        items = split_top_level(s[1:-1])
        cleaned = []
        for it in items:
            it = it.strip()
            if len(it) >= 2 and it.startswith('"') and it.endswith('"'):
                cleaned.append(it[1:-1])
            else:
                cleaned.append(it)
        return "; ".join(cleaned)
    
    # Missing["..."]
    if re.match(r"Missing\[", s):
        return ""
    
    return s


def split_top_level(s: str) -> List[str]:
    """Split a string on top-level commas, respecting nesting and strings."""
    parts = []
    current = []
    depth = 0
    in_string = False
    escape = False
    
    for c in s:
        if in_string:
            current.append(c)
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_string = False
        elif c == '"':
            in_string = True
            current.append(c)
        elif c in "{[":
            depth += 1
            current.append(c)
        elif c in "}]":
            depth -= 1
            current.append(c)
        elif c == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(c)
    
    if current:
        parts.append("".join(current))
    
    return parts


def parse_association(text: str) -> dict:
    """Parse a single <| ... |> block into a Python dict."""
    s = text.strip()
    if s.startswith("<|"):
        s = s[2:]
    if s.endswith("|>"):
        s = s[:-2]
    s = s.strip()
    
    pairs = split_top_level(s)
    
    result = {}
    for pair in pairs:
        if "->" not in pair:
            continue
        key_part, _, value_part = pair.partition("->")
        key = key_part.strip().strip('"')
        value = parse_value(value_part)
        result[key] = value
    
    return result


def convert_to_csv(
    input_path: Path,
    output_path: Path,
    automatic_only: bool = True,
) -> dict:
    """Convert outagesBPA.txt to CSV."""
    print(f"Reading file: {input_path}")
    t0 = time.time()
    
    with open(input_path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    
    print(f"  Loaded {len(text) / 1e6:.1f} MB in {time.time() - t0:.1f}s")
    
    print(f"Scanning for Association blocks...")
    t1 = time.time()
    boundaries = find_associations(text)
    print(f"  Found {len(boundaries):,} association blocks in {time.time() - t1:.1f}s")
    
    if not boundaries:
        print("ERROR: no <|...|> blocks found in file.")
        return {"n_total": 0, "n_kept": 0}
    
    print(f"Parsing records...")
    t2 = time.time()
    
    rows = []
    n_total = 0
    type_counts = {"Auto": 0, "Plan": 0, "Other": 0}
    
    for start, end in boundaries:
        try:
            record = parse_association(text[start:end])
        except Exception as exc:
            print(f"  Warning: parse error at offset {start}: {exc}")
            continue
        
        n_total += 1
        outage_type = record.get("OutageType", "")
        if outage_type == "Auto":
            type_counts["Auto"] += 1
        elif outage_type == "Plan":
            type_counts["Plan"] += 1
        else:
            type_counts["Other"] += 1
        
        if automatic_only and outage_type != "Auto":
            continue
        
        rows.append(record)
        
        if n_total % 5000 == 0:
            print(f"  Processed {n_total:,} / {len(boundaries):,} records "
                  f"({n_total / len(boundaries) * 100:.0f}%)")
    
    print(f"  Parsing done in {time.time() - t2:.1f}s")
    
    print(f"\nResults:")
    print(f"  Total records:              {n_total:,}")
    print(f"  Automatic (Auto):           {type_counts['Auto']:,}")
    print(f"  Scheduled (Plan):           {type_counts['Plan']:,}")
    print(f"  Other / missing type:       {type_counts['Other']:,}")
    print(f"  Kept for output:            {len(rows):,}")
    
    if not rows:
        print("ERROR: no rows kept after filtering.")
        return {"n_total": n_total, "n_kept": 0}
    
    observed = set()
    for r in rows:
        observed.update(r.keys())
    extras = sorted(observed - set(EXPECTED_FIELDS))
    columns = [c for c in EXPECTED_FIELDS if c in observed] + extras
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=columns, quoting=csv.QUOTE_MINIMAL,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)
    
    size_mb = output_path.stat().st_size / 1e6
    print(f"\nWrote CSV: {output_path}")
    print(f"  Rows: {len(rows):,}")
    print(f"  Columns: {len(columns)}")
    print(f"  Size: {size_mb:.2f} MB")
    print(f"  Total elapsed: {time.time() - t0:.1f}s")
    
    return {
        "n_total": n_total,
        "n_kept": len(rows),
        "type_counts": type_counts,
        "size_mb": size_mb,
        "columns": columns,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("data/dobson_bpa/outagesBPA.txt"))
    parser.add_argument("--output", type=Path, default=Path("data/dobson_bpa/outagesBPA.csv"))
    parser.add_argument("--all-types", action="store_true",
                        help="Include scheduled outages (default: only automatic)")
    args = parser.parse_args()
    
    if not args.input.exists():
        print(f"ERROR: file not found: {args.input}")
        return 1
    
    stats = convert_to_csv(args.input, args.output, automatic_only=not args.all_types)
    
    if stats.get("n_kept", 0) > 0:
        print("\n[OK] Conversion complete.")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())