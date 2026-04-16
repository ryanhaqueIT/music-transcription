"""
run_baseline.py -- Run baseline evaluation on HOMR reference outputs.

Validates all page files and the full output, compares pages vs full,
computes self-consistency scores, and writes a baseline report.
"""

import sys
import os
import json
from pathlib import Path
from datetime import datetime

# Ensure we can import sibling modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from validate import validate_file, format_report as format_validation_report
from compare import load_score, extract_metrics, compare_metrics, format_text_report, format_html_report
from score import compute_scores, format_score_report

REF_DIR = Path(__file__).resolve().parent.parent / "reference-outputs"
EVAL_DIR = Path(__file__).resolve().parent

PAGE_FILES = [REF_DIR / f"page_{i}.musicxml" for i in range(1, 6)]
FULL_FILE = REF_DIR / "homr-full-output.musicxml"


def section(title: str) -> str:
    return f"\n{'#' * 70}\n# {title}\n{'#' * 70}\n"


def run():
    report_lines = []
    report_lines.append(f"HOMR Baseline Evaluation Report")
    report_lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    report_lines.append(f"Test piece: Mozart - Eine Kleine Nachtmusik (Viola part)")
    report_lines.append(f"Tool: HOMR (via Colab)")
    report_lines.append("")

    # ------------------------------------------------------------------
    # 1. Validate each page file
    # ------------------------------------------------------------------
    report_lines.append(section("1. VALIDATION -- Individual Page Files"))

    page_stats = {}
    for pf in PAGE_FILES:
        print(f"Validating {pf.name} ...")
        vr = validate_file(str(pf))
        report_lines.append(format_validation_report(vr))
        report_lines.append("")
        if vr["music21"].get("stats"):
            page_stats[pf.name] = vr["music21"]["stats"]

    # ------------------------------------------------------------------
    # 2. Validate the full combined file
    # ------------------------------------------------------------------
    report_lines.append(section("2. VALIDATION -- Full Combined File"))
    print(f"Validating {FULL_FILE.name} ...")
    full_vr = validate_file(str(FULL_FILE))
    report_lines.append(format_validation_report(full_vr))
    report_lines.append("")
    full_stats = full_vr["music21"].get("stats", {})

    # ------------------------------------------------------------------
    # 3. Summary stats table
    # ------------------------------------------------------------------
    report_lines.append(section("3. SUMMARY STATISTICS"))

    # Aggregate page stats
    total_notes_pages = sum(s.get("num_notes", 0) for s in page_stats.values())
    total_rests_pages = sum(s.get("num_rests", 0) for s in page_stats.values())
    total_measures_pages = sum(s.get("num_measures", 0) for s in page_stats.values())
    total_dur_pages = sum(s.get("total_duration_ql", 0) for s in page_stats.values())

    report_lines.append(f"{'Metric':<30s} {'Pages (sum)':<15s} {'Full file':<15s}")
    report_lines.append(f"{'-'*60}")
    report_lines.append(f"{'Parts':<30s} {'1':<15s} {str(full_stats.get('num_parts','?')):<15s}")
    report_lines.append(f"{'Total measures':<30s} {str(total_measures_pages):<15s} {str(full_stats.get('num_measures','?')):<15s}")
    report_lines.append(f"{'Total notes (non-rest)':<30s} {str(total_notes_pages):<15s} {str(full_stats.get('num_notes','?')):<15s}")
    report_lines.append(f"{'Total rests':<30s} {str(total_rests_pages):<15s} {str(full_stats.get('num_rests','?')):<15s}")
    report_lines.append(f"{'Total duration (ql)':<30s} {str(total_dur_pages):<15s} {str(full_stats.get('total_duration_ql','?')):<15s}")
    report_lines.append("")

    # Per-page breakdown
    report_lines.append("Per-page breakdown:")
    report_lines.append(f"  {'Page':<12s} {'Measures':>10s} {'Notes':>10s} {'Rests':>10s} {'Duration(ql)':>14s}")
    for name, s in page_stats.items():
        report_lines.append(
            f"  {name:<12s} {s['num_measures']:>10d} {s['num_notes']:>10d} "
            f"{s['num_rests']:>10d} {s['total_duration_ql']:>14.1f}"
        )
    report_lines.append("")

    # ------------------------------------------------------------------
    # 4. Compare pages (merged) vs full file
    # ------------------------------------------------------------------
    report_lines.append(section("4. COMPARISON -- Merged Pages vs Full File"))
    print("Loading and comparing merged pages vs full file ...")

    try:
        score_pages = load_score([str(p) for p in PAGE_FILES])
        metrics_pages = extract_metrics(score_pages)

        score_full = load_score(str(FULL_FILE))
        metrics_full = extract_metrics(score_full)

        diffs = compare_metrics(metrics_pages, metrics_full, "Merged Pages", "Full File")
        report_lines.append(format_text_report(diffs, "Merged Pages", "Full File"))
        report_lines.append("")

        # Also write HTML
        html = format_html_report(diffs, "Merged Pages", "Full File")
        html_path = EVAL_DIR / "comparison-report.html"
        html_path.write_text(html, encoding="utf-8")
        report_lines.append(f"(HTML report saved to {html_path.name})")
        report_lines.append("")
    except Exception as e:
        report_lines.append(f"ERROR during comparison: {e}")
        report_lines.append("")

    # ------------------------------------------------------------------
    # 5. Self-consistency score (pages vs full)
    # ------------------------------------------------------------------
    report_lines.append(section("5. SELF-CONSISTENCY SCORE -- Pages vs Full"))
    try:
        scores = compute_scores(metrics_pages, metrics_full)
        report_lines.append(format_score_report(scores, "Merged Pages", "Full File"))
        report_lines.append("")
    except Exception as e:
        report_lines.append(f"ERROR during scoring: {e}")
        report_lines.append("")

    # ------------------------------------------------------------------
    # 6. Pitch and rhythm distributions (full file)
    # ------------------------------------------------------------------
    report_lines.append(section("6. DETAILED DISTRIBUTIONS (Full File)"))

    if "pitch_class_distribution" in metrics_full:
        report_lines.append("Pitch-class distribution (note name -> count):")
        for p, c in sorted(metrics_full["pitch_class_distribution"].items(),
                           key=lambda x: -x[1]):
            report_lines.append(f"  {p:<5s} : {c}")
        report_lines.append("")

    if "duration_distribution" in metrics_full:
        report_lines.append("Duration distribution (type -> count):")
        for d, c in sorted(metrics_full["duration_distribution"].items(),
                           key=lambda x: -x[1]):
            report_lines.append(f"  {d:<12s} : {c}")
        report_lines.append("")

    if "pitch_distribution" in metrics_full:
        report_lines.append("Full pitch distribution (top 30):")
        items = sorted(metrics_full["pitch_distribution"].items(), key=lambda x: -x[1])
        for p, c in items[:30]:
            report_lines.append(f"  {p:<10s} : {c}")
        report_lines.append("")

    # ------------------------------------------------------------------
    # 7. OMR quality assessment
    # ------------------------------------------------------------------
    report_lines.append(section("7. OMR QUALITY ASSESSMENT"))

    # Check the known facts about Eine Kleine Nachtmusik Viola part
    findings = []

    # Key: G major (1 sharp)
    if full_stats.get("key_signatures"):
        ks = full_stats["key_signatures"]
        if any("sharp" in k.lower() or "1" in k for k in ks):
            findings.append("Key signature: CORRECT -- G major detected (1 sharp / fifths=1)")
        else:
            findings.append(f"Key signature: CHECK -- found {ks}, expected G major")
    else:
        findings.append("Key signature: MISSING")

    # Time: 4/4
    if full_stats.get("time_signatures"):
        ts = full_stats["time_signatures"]
        if any("4/4" in t for t in ts):
            findings.append("Time signature: CORRECT -- 4/4 detected")
        else:
            findings.append(f"Time signature: CHECK -- found {ts}")
    else:
        findings.append("Time signature: MISSING")

    # Clef: Alto (C3)
    if full_stats.get("clefs"):
        cl = full_stats["clefs"]
        has_alto = any("alto" in c.lower() or "AltoClef" in c for c in cl)
        if has_alto:
            findings.append("Clef: CORRECT -- Alto clef detected (appropriate for Viola)")
        else:
            findings.append(f"Clef: CHECK -- found {cl}, expected Alto clef for Viola")
    else:
        findings.append("Clef: MISSING")

    # Instrument labeling
    findings.append(f"Parts: {full_stats.get('num_parts', '?')} (expected 1 for single Viola part)")
    findings.append(f"Measures: {full_stats.get('num_measures', '?')}")
    findings.append(f"Notes: {full_stats.get('num_notes', '?')}")

    for f in findings:
        report_lines.append(f"  {f}")
    report_lines.append("")

    # ------------------------------------------------------------------
    # Write report
    # ------------------------------------------------------------------
    report_text = "\n".join(report_lines)
    report_path = EVAL_DIR / "baseline-report.md"
    report_path.write_text(report_text, encoding="utf-8")
    print(f"\nBaseline report written to: {report_path}")
    print(report_text)

    return report_text


if __name__ == "__main__":
    run()
