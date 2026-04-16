"""
validate.py -- Validate MusicXML files for well-formedness and common OMR errors.

Usage:
    python validate.py <musicxml_file> [<musicxml_file2> ...]
"""

import sys
import os
from pathlib import Path
from collections import defaultdict

try:
    from lxml import etree
except ImportError:
    etree = None

import music21
from music21 import converter, meter, key, clef, note, stream


def validate_xml_wellformed(filepath: str) -> dict:
    """Check that the file is well-formed XML."""
    result = {"well_formed": False, "errors": []}
    try:
        if etree is not None:
            etree.parse(filepath)
        else:
            import xml.etree.ElementTree as ET
            ET.parse(filepath)
        result["well_formed"] = True
    except Exception as e:
        result["errors"].append(str(e))
    return result


def parse_with_music21(filepath: str) -> dict:
    """Parse the file with music21 and extract basic stats."""
    result = {
        "parseable": False,
        "errors": [],
        "stats": {},
    }
    try:
        score = converter.parse(filepath)
        result["parseable"] = True

        parts = score.parts
        all_notes = score.flatten().notes  # notes + chords (not rests)
        all_rests = [el for el in score.flatten().notesAndRests if isinstance(el, note.Rest)]
        measures = score.parts[0].getElementsByClass(stream.Measure) if parts else []

        # Key signatures
        key_sigs = score.flatten().getElementsByClass(key.KeySignature)
        key_list = [str(k) for k in key_sigs]

        # Time signatures
        time_sigs = score.flatten().getElementsByClass(meter.TimeSignature)
        time_list = [str(t) for t in time_sigs]

        # Clefs
        clefs = score.flatten().getElementsByClass(clef.Clef)
        clef_list = [str(c) for c in clefs]

        result["stats"] = {
            "num_parts": len(parts),
            "num_measures": len(measures),
            "num_notes": len(all_notes),
            "num_rests": len(all_rests),
            "key_signatures": key_list,
            "time_signatures": time_list,
            "clefs": clef_list,
            "total_duration_ql": float(score.duration.quarterLength),
        }
        result["score"] = score  # pass along for further analysis
    except Exception as e:
        result["errors"].append(str(e))
    return result


def check_beat_counts(score) -> list:
    """Flag measures where note/rest durations don't sum to the expected beats."""
    issues = []
    for part in score.parts:
        current_ts = meter.TimeSignature("4/4")  # default
        for m in part.getElementsByClass(stream.Measure):
            # Update time signature if one is defined in this measure
            ts_in_measure = m.getElementsByClass(meter.TimeSignature)
            if ts_in_measure:
                current_ts = ts_in_measure[0]

            expected_ql = current_ts.barDuration.quarterLength
            actual_ql = sum(
                el.duration.quarterLength
                for el in m.notesAndRests
            )

            # Allow small floating-point tolerance
            if abs(actual_ql - expected_ql) > 0.01:
                issues.append({
                    "measure": m.number,
                    "expected_ql": expected_ql,
                    "actual_ql": round(actual_ql, 4),
                    "diff": round(actual_ql - expected_ql, 4),
                })
    return issues


def check_common_omr_errors(score) -> list:
    """Flag common OMR problems."""
    flags = []

    # 1. Missing key signature (fifths=0 or no key sig at all)
    key_sigs = score.flatten().getElementsByClass(key.KeySignature)
    if not key_sigs:
        flags.append("WARNING: No key signature found -- possible OMR miss.")

    # 2. Missing time signature
    time_sigs = score.flatten().getElementsByClass(meter.TimeSignature)
    if not time_sigs:
        flags.append("WARNING: No time signature found -- possible OMR miss.")

    # 3. Missing clef
    clefs_found = score.flatten().getElementsByClass(clef.Clef)
    if not clefs_found:
        flags.append("WARNING: No clef found -- possible OMR miss.")

    # 4. Check for instrument mismatch (Viola should be alto clef)
    for c in clefs_found:
        if isinstance(c, clef.AltoClef):
            break
    else:
        if clefs_found:
            flags.append(
                f"NOTE: Expected Alto clef for Viola part, found: "
                f"{[str(c) for c in clefs_found]}"
            )

    # 5. Beat-count issues
    beat_issues = check_beat_counts(score)
    if beat_issues:
        flags.append(
            f"WARNING: {len(beat_issues)} measure(s) have incorrect beat counts."
        )
        for bi in beat_issues[:10]:  # show first 10
            flags.append(
                f"  Measure {bi['measure']}: expected {bi['expected_ql']}ql, "
                f"got {bi['actual_ql']}ql (diff {bi['diff']})"
            )
        if len(beat_issues) > 10:
            flags.append(f"  ... and {len(beat_issues) - 10} more.")

    return flags


def validate_file(filepath: str) -> dict:
    """Run full validation on a single MusicXML file."""
    report = {"file": filepath}

    # Step 1: XML well-formedness
    xml_result = validate_xml_wellformed(filepath)
    report["xml"] = xml_result

    if not xml_result["well_formed"]:
        report["music21"] = {"parseable": False, "errors": ["Skipped (XML not well-formed)"]}
        report["omr_flags"] = []
        return report

    # Step 2: music21 parsing
    m21_result = parse_with_music21(filepath)
    report["music21"] = {k: v for k, v in m21_result.items() if k != "score"}

    if not m21_result["parseable"]:
        report["omr_flags"] = []
        return report

    # Step 3: OMR error checks
    report["omr_flags"] = check_common_omr_errors(m21_result["score"])

    return report


def format_report(report: dict) -> str:
    """Format a validation report as readable text."""
    lines = []
    lines.append(f"=== Validation: {os.path.basename(report['file'])} ===")
    lines.append(f"  XML well-formed: {report['xml']['well_formed']}")
    if report["xml"]["errors"]:
        for e in report["xml"]["errors"]:
            lines.append(f"    XML Error: {e}")

    m21 = report.get("music21", {})
    lines.append(f"  music21 parseable: {m21.get('parseable', False)}")
    if m21.get("errors"):
        for e in m21["errors"]:
            lines.append(f"    Parse Error: {e}")

    stats = m21.get("stats", {})
    if stats:
        lines.append(f"  Parts: {stats['num_parts']}")
        lines.append(f"  Measures: {stats['num_measures']}")
        lines.append(f"  Notes (non-rest): {stats['num_notes']}")
        lines.append(f"  Rests: {stats['num_rests']}")
        lines.append(f"  Total duration (ql): {stats['total_duration_ql']}")
        lines.append(f"  Key sigs: {stats['key_signatures']}")
        lines.append(f"  Time sigs: {stats['time_signatures']}")
        lines.append(f"  Clefs: {stats['clefs']}")

    flags = report.get("omr_flags", [])
    if flags:
        lines.append("  OMR checks:")
        for f in flags:
            lines.append(f"    {f}")
    else:
        lines.append("  OMR checks: All passed.")

    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python validate.py <file.musicxml> [<file2.musicxml> ...]")
        sys.exit(1)

    for fpath in sys.argv[1:]:
        report = validate_file(fpath)
        print(format_report(report))
        print()
