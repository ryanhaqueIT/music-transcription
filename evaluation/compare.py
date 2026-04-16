"""
compare.py -- Compare two MusicXML files and report differences.

Handles both single-file and multi-page (split) inputs.

Usage:
    python compare.py <file_a.musicxml> <file_b.musicxml>
    python compare.py --pages <dir_a_page1,page2,...> <file_b.musicxml>
"""

import sys
import os
import argparse
from pathlib import Path
from collections import Counter

import music21
from music21 import converter, meter, key, clef, note, chord, stream, pitch


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------

def load_score(filepath_or_list):
    """Load a score from a single file or merge a list of page files."""
    if isinstance(filepath_or_list, (list, tuple)):
        scores = [converter.parse(f) for f in filepath_or_list]
        combined = scores[0]
        for s in scores[1:]:
            for i, part in enumerate(s.parts):
                for m in part.getElementsByClass(stream.Measure):
                    combined.parts[i].append(m)
        return combined
    return converter.parse(filepath_or_list)


def extract_metrics(score) -> dict:
    """Extract comparison metrics from a music21 score."""
    parts = score.parts
    flat = score.flatten()
    notes_and_rests = list(flat.notesAndRests)
    sounding_notes = [n for n in notes_and_rests if not isinstance(n, note.Rest)]
    rests = [n for n in notes_and_rests if isinstance(n, note.Rest)]

    measures = parts[0].getElementsByClass(stream.Measure) if parts else []

    # Key signatures
    key_sigs = flat.getElementsByClass(key.KeySignature)
    key_list = [str(k) for k in key_sigs]

    # Time signatures
    time_sigs = flat.getElementsByClass(meter.TimeSignature)
    time_list = [str(t) for t in time_sigs]

    # Clefs
    clefs_found = flat.getElementsByClass(clef.Clef)
    clef_list = [str(c) for c in clefs_found]

    # Pitch distribution
    pitch_counter = Counter()
    for n in sounding_notes:
        if isinstance(n, chord.Chord):
            for p in n.pitches:
                pitch_counter[str(p)] += 1
        else:
            pitch_counter[str(n.pitch)] += 1

    # Duration distribution
    dur_counter = Counter()
    for n in notes_and_rests:
        dur_counter[n.duration.type] += 1

    # Pitch-class distribution (just note name, no octave)
    pitch_class_counter = Counter()
    for n in sounding_notes:
        if isinstance(n, chord.Chord):
            for p in n.pitches:
                pitch_class_counter[p.name] += 1
        else:
            pitch_class_counter[n.pitch.name] += 1

    # Build ordered note list for alignment comparisons
    note_list = []
    for n in sounding_notes:
        if isinstance(n, chord.Chord):
            for p in n.pitches:
                note_list.append({
                    "pitch": str(p),
                    "midi": p.midi,
                    "duration_type": n.duration.type,
                    "duration_ql": float(n.duration.quarterLength),
                })
        else:
            note_list.append({
                "pitch": str(n.pitch),
                "midi": n.pitch.midi,
                "duration_type": n.duration.type,
                "duration_ql": float(n.duration.quarterLength),
            })

    return {
        "num_parts": len(parts),
        "num_measures": len(measures),
        "num_notes": len(sounding_notes),
        "num_rests": len(rests),
        "total_duration_ql": float(score.duration.quarterLength),
        "key_signatures": key_list,
        "time_signatures": time_list,
        "clefs": clef_list,
        "pitch_distribution": dict(pitch_counter.most_common()),
        "pitch_class_distribution": dict(pitch_class_counter.most_common()),
        "duration_distribution": dict(dur_counter.most_common()),
        "note_list": note_list,
    }


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------

def compare_metrics(metrics_a: dict, metrics_b: dict, label_a="File A", label_b="File B") -> dict:
    """Compare two metric dicts and produce a diff report."""
    diffs = {}

    # Scalar comparisons
    for field in ["num_parts", "num_measures", "num_notes", "num_rests", "total_duration_ql"]:
        va, vb = metrics_a[field], metrics_b[field]
        diffs[field] = {
            label_a: va,
            label_b: vb,
            "match": va == vb,
            "diff": vb - va if isinstance(va, (int, float)) else None,
        }

    # List comparisons
    for field in ["key_signatures", "time_signatures", "clefs"]:
        la, lb = metrics_a[field], metrics_b[field]
        diffs[field] = {
            label_a: la,
            label_b: lb,
            "match": la == lb,
        }

    # Distribution comparisons (Jaccard-style overlap)
    for field in ["pitch_distribution", "pitch_class_distribution", "duration_distribution"]:
        da, db = metrics_a[field], metrics_b[field]
        all_keys = set(da.keys()) | set(db.keys())
        common = 0
        total = 0
        for k in all_keys:
            ca, cb = da.get(k, 0), db.get(k, 0)
            common += min(ca, cb)
            total += max(ca, cb)
        overlap = common / total if total else 1.0
        diffs[field] = {
            label_a: da,
            label_b: db,
            "overlap_pct": round(overlap * 100, 2),
        }

    return diffs


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

def format_text_report(diffs: dict, label_a: str, label_b: str) -> str:
    """Generate a human-readable text comparison report."""
    lines = []
    lines.append(f"{'='*70}")
    lines.append(f"MusicXML Comparison Report")
    lines.append(f"  {label_a}  vs  {label_b}")
    lines.append(f"{'='*70}")

    for field in ["num_parts", "num_measures", "num_notes", "num_rests", "total_duration_ql"]:
        d = diffs[field]
        status = "MATCH" if d["match"] else f"DIFF ({d['diff']:+})" if d["diff"] is not None else "DIFF"
        lines.append(f"  {field:25s}  {str(d[label_a]):>10s}  {str(d[label_b]):>10s}  [{status}]")

    for field in ["key_signatures", "time_signatures", "clefs"]:
        d = diffs[field]
        status = "MATCH" if d["match"] else "DIFF"
        lines.append(f"  {field:25s}  [{status}]")
        if not d["match"]:
            lines.append(f"    {label_a}: {d[label_a]}")
            lines.append(f"    {label_b}: {d[label_b]}")

    for field in ["pitch_distribution", "pitch_class_distribution", "duration_distribution"]:
        d = diffs[field]
        lines.append(f"  {field:25s}  overlap: {d['overlap_pct']}%")

    lines.append(f"{'='*70}")
    return "\n".join(lines)


def format_html_report(diffs: dict, label_a: str, label_b: str) -> str:
    """Generate an HTML comparison table."""
    rows = []

    for field in ["num_parts", "num_measures", "num_notes", "num_rests", "total_duration_ql"]:
        d = diffs[field]
        match_cls = "match" if d["match"] else "diff"
        status = "MATCH" if d["match"] else f"DIFF ({d['diff']:+})" if d["diff"] is not None else "DIFF"
        rows.append(
            f'<tr class="{match_cls}"><td>{field}</td>'
            f'<td>{d[label_a]}</td><td>{d[label_b]}</td><td>{status}</td></tr>'
        )

    for field in ["key_signatures", "time_signatures", "clefs"]:
        d = diffs[field]
        match_cls = "match" if d["match"] else "diff"
        status = "MATCH" if d["match"] else "DIFF"
        rows.append(
            f'<tr class="{match_cls}"><td>{field}</td>'
            f'<td>{", ".join(d[label_a]) if d[label_a] else "(none)"}</td>'
            f'<td>{", ".join(d[label_b]) if d[label_b] else "(none)"}</td>'
            f'<td>{status}</td></tr>'
        )

    for field in ["pitch_distribution", "pitch_class_distribution", "duration_distribution"]:
        d = diffs[field]
        pct = d["overlap_pct"]
        match_cls = "match" if pct > 95 else "partial" if pct > 80 else "diff"
        rows.append(
            f'<tr class="{match_cls}"><td>{field}</td>'
            f'<td colspan="2">(see detail)</td><td>{pct}%</td></tr>'
        )

    table_rows = "\n    ".join(rows)

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<title>MusicXML Comparison</title>
<style>
  body {{ font-family: sans-serif; margin: 2em; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ border: 1px solid #ccc; padding: 6px 12px; text-align: left; }}
  th {{ background: #f0f0f0; }}
  tr.match td {{ background: #e6ffe6; }}
  tr.diff td {{ background: #ffe6e6; }}
  tr.partial td {{ background: #fff8e6; }}
</style>
</head>
<body>
<h1>MusicXML Comparison Report</h1>
<p><strong>A:</strong> {label_a}<br/><strong>B:</strong> {label_b}</p>
<table>
  <tr><th>Metric</th><th>{label_a}</th><th>{label_b}</th><th>Status</th></tr>
    {table_rows}
</table>
</body>
</html>"""
    return html


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Compare MusicXML files")
    parser.add_argument("file_a", help="First MusicXML file (or comma-separated page list)")
    parser.add_argument("file_b", help="Second MusicXML file (or comma-separated page list)")
    parser.add_argument("--html", help="Output HTML report to this path")
    parser.add_argument("--label-a", default=None)
    parser.add_argument("--label-b", default=None)
    args = parser.parse_args()

    def resolve_input(val):
        if "," in val:
            return [f.strip() for f in val.split(",")]
        return val

    input_a = resolve_input(args.file_a)
    input_b = resolve_input(args.file_b)

    label_a = args.label_a or (args.file_a if isinstance(input_a, str) else "Pages A")
    label_b = args.label_b or (args.file_b if isinstance(input_b, str) else "Pages B")

    print(f"Loading {label_a} ...")
    score_a = load_score(input_a)
    metrics_a = extract_metrics(score_a)

    print(f"Loading {label_b} ...")
    score_b = load_score(input_b)
    metrics_b = extract_metrics(score_b)

    diffs = compare_metrics(metrics_a, metrics_b, label_a, label_b)
    print(format_text_report(diffs, label_a, label_b))

    if args.html:
        html = format_html_report(diffs, label_a, label_b)
        Path(args.html).write_text(html, encoding="utf-8")
        print(f"\nHTML report written to {args.html}")


if __name__ == "__main__":
    main()
