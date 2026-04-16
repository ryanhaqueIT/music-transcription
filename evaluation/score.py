"""
score.py -- Compute accuracy scores between a reference and candidate MusicXML.

Scores:
  - Note-level accuracy  (pitch match %)
  - Rhythm accuracy      (duration match %)
  - Structure accuracy   (measure count, key/time sig match)
  - Overall weighted score

Usage:
    python score.py <reference.musicxml> <candidate.musicxml>
"""

import sys
import argparse
from pathlib import Path

import music21
from music21 import converter, stream

from compare import load_score, extract_metrics


# ---------------------------------------------------------------------------
# Alignment helpers
# ---------------------------------------------------------------------------

def align_note_lists(ref_notes: list, cand_notes: list) -> dict:
    """
    Align two ordered note lists by position and compute match stats.

    Each entry is a dict with keys: pitch, midi, duration_type, duration_ql.
    We do a simple positional alignment (index-by-index) since both should
    represent the same sequential piece.
    """
    n = min(len(ref_notes), len(cand_notes))
    pitch_matches = 0
    duration_matches = 0
    duration_ql_matches = 0

    pitch_diffs = []  # list of (index, ref_pitch, cand_pitch)
    duration_diffs = []

    for i in range(n):
        r, c = ref_notes[i], cand_notes[i]

        if r["midi"] == c["midi"]:
            pitch_matches += 1
        else:
            pitch_diffs.append((i, r["pitch"], c["pitch"]))

        if r["duration_type"] == c["duration_type"]:
            duration_matches += 1
        else:
            duration_diffs.append((i, r["duration_type"], c["duration_type"]))

        if abs(r["duration_ql"] - c["duration_ql"]) < 0.01:
            duration_ql_matches += 1

    total_ref = len(ref_notes)
    total_cand = len(cand_notes)

    return {
        "aligned_count": n,
        "ref_total": total_ref,
        "cand_total": total_cand,
        "extra_in_ref": total_ref - n,
        "extra_in_cand": total_cand - n,
        "pitch_matches": pitch_matches,
        "duration_matches": duration_matches,
        "duration_ql_matches": duration_ql_matches,
        "pitch_diffs_sample": pitch_diffs[:20],
        "duration_diffs_sample": duration_diffs[:20],
    }


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def compute_scores(ref_metrics: dict, cand_metrics: dict) -> dict:
    """Compute accuracy scores."""
    alignment = align_note_lists(ref_metrics["note_list"], cand_metrics["note_list"])

    n = alignment["aligned_count"]

    # Note-level pitch accuracy
    pitch_acc = alignment["pitch_matches"] / n * 100 if n else 0.0

    # Rhythm accuracy
    rhythm_acc = alignment["duration_matches"] / n * 100 if n else 0.0

    # Structure accuracy (out of 100)
    struct_points = 0
    struct_max = 0

    # Measure count
    struct_max += 30
    ref_m = ref_metrics["num_measures"]
    cand_m = cand_metrics["num_measures"]
    if ref_m == cand_m:
        struct_points += 30
    elif ref_m > 0:
        struct_points += max(0, 30 * (1 - abs(ref_m - cand_m) / ref_m))

    # Key signature match
    struct_max += 20
    if ref_metrics["key_signatures"] == cand_metrics["key_signatures"]:
        struct_points += 20
    elif ref_metrics["key_signatures"] and cand_metrics["key_signatures"]:
        # Partial credit if at least the first key sig matches
        if ref_metrics["key_signatures"][0] == cand_metrics["key_signatures"][0]:
            struct_points += 15

    # Time signature match
    struct_max += 20
    if ref_metrics["time_signatures"] == cand_metrics["time_signatures"]:
        struct_points += 20
    elif ref_metrics["time_signatures"] and cand_metrics["time_signatures"]:
        if ref_metrics["time_signatures"][0] == cand_metrics["time_signatures"][0]:
            struct_points += 15

    # Note count closeness
    struct_max += 15
    ref_n = ref_metrics["num_notes"]
    cand_n = cand_metrics["num_notes"]
    if ref_n == cand_n:
        struct_points += 15
    elif ref_n > 0:
        struct_points += max(0, 15 * (1 - abs(ref_n - cand_n) / ref_n))

    # Part count
    struct_max += 15
    if ref_metrics["num_parts"] == cand_metrics["num_parts"]:
        struct_points += 15

    struct_acc = struct_points / struct_max * 100 if struct_max else 0.0

    # Overall weighted score
    overall = 0.40 * pitch_acc + 0.30 * rhythm_acc + 0.30 * struct_acc

    return {
        "pitch_accuracy": round(pitch_acc, 2),
        "rhythm_accuracy": round(rhythm_acc, 2),
        "structure_accuracy": round(struct_acc, 2),
        "overall_score": round(overall, 2),
        "alignment": alignment,
        "weights": {"pitch": 0.40, "rhythm": 0.30, "structure": 0.30},
    }


def format_score_report(scores: dict, ref_label: str, cand_label: str) -> str:
    """Format a human-readable scoring report."""
    a = scores["alignment"]
    lines = []
    lines.append("=" * 70)
    lines.append("MusicXML Accuracy Scoring Report")
    lines.append(f"  Reference : {ref_label}")
    lines.append(f"  Candidate : {cand_label}")
    lines.append("=" * 70)
    lines.append("")
    lines.append(f"  Notes aligned : {a['aligned_count']}  "
                 f"(ref={a['ref_total']}, cand={a['cand_total']})")
    if a["extra_in_ref"]:
        lines.append(f"  Extra notes in reference (not in candidate): {a['extra_in_ref']}")
    if a["extra_in_cand"]:
        lines.append(f"  Extra notes in candidate (not in reference): {a['extra_in_cand']}")
    lines.append("")
    lines.append(f"  Pitch accuracy     : {scores['pitch_accuracy']:6.2f}%  "
                 f"({a['pitch_matches']}/{a['aligned_count']} matched)")
    lines.append(f"  Rhythm accuracy    : {scores['rhythm_accuracy']:6.2f}%  "
                 f"({a['duration_matches']}/{a['aligned_count']} matched)")
    lines.append(f"  Structure accuracy : {scores['structure_accuracy']:6.2f}%")
    lines.append(f"  -----------------------------------------")
    lines.append(f"  OVERALL SCORE      : {scores['overall_score']:6.2f}%")
    lines.append(f"    (weights: pitch={scores['weights']['pitch']}, "
                 f"rhythm={scores['weights']['rhythm']}, "
                 f"structure={scores['weights']['structure']})")
    lines.append("")

    # Show sample diffs
    if a["pitch_diffs_sample"]:
        lines.append("  Sample pitch differences (first 20):")
        for idx, rp, cp in a["pitch_diffs_sample"]:
            lines.append(f"    note[{idx}]: ref={rp}  cand={cp}")
    if a["duration_diffs_sample"]:
        lines.append("  Sample duration differences (first 20):")
        for idx, rd, cd in a["duration_diffs_sample"]:
            lines.append(f"    note[{idx}]: ref={rd}  cand={cd}")

    lines.append("=" * 70)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Score MusicXML accuracy")
    parser.add_argument("reference", help="Reference MusicXML file")
    parser.add_argument("candidate", help="Candidate MusicXML file to score")
    parser.add_argument("--label-ref", default=None)
    parser.add_argument("--label-cand", default=None)
    args = parser.parse_args()

    ref_label = args.label_ref or args.reference
    cand_label = args.label_cand or args.candidate

    print(f"Loading reference: {ref_label} ...")
    ref_score = load_score(args.reference)
    ref_metrics = extract_metrics(ref_score)

    print(f"Loading candidate: {cand_label} ...")
    cand_score = load_score(args.candidate)
    cand_metrics = extract_metrics(cand_score)

    scores = compute_scores(ref_metrics, cand_metrics)
    print(format_score_report(scores, ref_label, cand_label))


if __name__ == "__main__":
    main()
