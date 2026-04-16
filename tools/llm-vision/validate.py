#!/usr/bin/env python3
"""
Validate MusicXML output from the LLM Vision converter.

Checks:
  1. Well-formed XML
  2. Basic MusicXML structure (part-list, parts, measures)
  3. Music21 parsing: key, time sig, clef, note count, duration
  4. Optional comparison against reference outputs

Usage:
    python tools/llm-vision/validate.py [--file PATH] [--reference PATH]
                                        [--reference-dir PATH]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("validate")

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent


# ---------------------------------------------------------------------------
# 1. XML well-formedness
# ---------------------------------------------------------------------------


def check_xml_wellformed(xml_path: Path) -> dict:
    """Check if the file is well-formed XML. Returns a result dict."""
    result = {"check": "xml_wellformed", "passed": False, "details": {}}
    try:
        tree = ET.parse(str(xml_path))
        root = tree.getroot()
        result["passed"] = True
        result["details"]["root_tag"] = root.tag
        result["details"]["encoding"] = "utf-8"
    except ET.ParseError as e:
        result["details"]["error"] = str(e)
        # Try to identify the problematic area
        try:
            text = xml_path.read_text(encoding="utf-8")
            line_num = getattr(e, "position", (0, 0))[0] if hasattr(e, "position") else 0
            if line_num > 0:
                lines = text.splitlines()
                start = max(0, line_num - 3)
                end = min(len(lines), line_num + 2)
                result["details"]["context_lines"] = {
                    i + 1: lines[i] for i in range(start, end)
                }
        except Exception:
            pass
    return result


# ---------------------------------------------------------------------------
# 2. MusicXML structure validation
# ---------------------------------------------------------------------------


def check_musicxml_structure(xml_path: Path) -> dict:
    """Check basic MusicXML structural elements."""
    result = {
        "check": "musicxml_structure",
        "passed": False,
        "details": {},
        "warnings": [],
    }

    try:
        tree = ET.parse(str(xml_path))
        root = tree.getroot()
    except ET.ParseError:
        result["details"]["error"] = "Cannot parse XML (see xml_wellformed check)"
        return result

    # Check root element
    if root.tag != "score-partwise":
        result["warnings"].append(
            f"Root element is '{root.tag}', expected 'score-partwise'"
        )

    # Check part-list
    part_list = root.find("part-list")
    if part_list is None:
        result["warnings"].append("Missing <part-list>")
    else:
        score_parts = part_list.findall("score-part")
        result["details"]["num_parts_declared"] = len(score_parts)
        part_ids = [sp.get("id") for sp in score_parts]
        result["details"]["part_ids"] = part_ids

    # Check parts
    parts = root.findall("part")
    result["details"]["num_parts"] = len(parts)

    if not parts:
        result["warnings"].append("No <part> elements found")
        return result

    # Analyze the first (and likely only) part
    part = parts[0]
    measures = part.findall("measure")
    result["details"]["num_measures"] = len(measures)

    if not measures:
        result["warnings"].append("No <measure> elements found")
        return result

    # Check measure numbering
    measure_numbers = []
    for m in measures:
        num = m.get("number")
        if num:
            try:
                measure_numbers.append(int(num))
            except ValueError:
                measure_numbers.append(num)
    result["details"]["measure_numbers"] = (
        f"{measure_numbers[0]}-{measure_numbers[-1]}"
        if measure_numbers
        else "none"
    )

    # Check for gaps in measure numbering
    if measure_numbers and all(isinstance(n, int) for n in measure_numbers):
        expected = list(range(measure_numbers[0], measure_numbers[-1] + 1))
        missing = set(expected) - set(measure_numbers)
        if missing:
            result["warnings"].append(f"Missing measure numbers: {sorted(missing)}")

    # Check first measure for key elements
    first_measure = measures[0]
    attrs = first_measure.find("attributes")
    if attrs is not None:
        key = attrs.find("key")
        time = attrs.find("time")
        clef = attrs.find("clef")
        divisions = attrs.find("divisions")

        result["details"]["has_key"] = key is not None
        result["details"]["has_time"] = time is not None
        result["details"]["has_clef"] = clef is not None
        result["details"]["has_divisions"] = divisions is not None

        if key is not None:
            fifths = key.findtext("fifths")
            result["details"]["key_fifths"] = fifths

        if time is not None:
            beats = time.findtext("beats")
            beat_type = time.findtext("beat-type")
            result["details"]["time_signature"] = f"{beats}/{beat_type}"

        if clef is not None:
            sign = clef.findtext("sign")
            line = clef.findtext("line")
            result["details"]["clef"] = f"{sign}/{line}"

        if divisions is not None:
            result["details"]["divisions"] = divisions.text
    else:
        result["warnings"].append("First measure has no <attributes>")

    # Count notes and rests
    total_notes = 0
    total_rests = 0
    for m in measures:
        for note in m.findall("note"):
            if note.find("rest") is not None:
                total_rests += 1
            else:
                total_notes += 1

    result["details"]["total_notes"] = total_notes
    result["details"]["total_rests"] = total_rests

    result["passed"] = len(result["warnings"]) == 0
    return result


# ---------------------------------------------------------------------------
# 3. Music21 parsing validation
# ---------------------------------------------------------------------------


def check_music21(xml_path: Path) -> dict:
    """Use music21 to parse and validate the MusicXML."""
    result = {
        "check": "music21_parse",
        "passed": False,
        "details": {},
        "warnings": [],
    }

    try:
        import music21
    except ImportError:
        result["details"]["error"] = "music21 not installed (pip install music21)"
        return result

    try:
        score = music21.converter.parse(str(xml_path))
    except Exception as e:
        result["details"]["error"] = f"music21 parse failed: {e}"
        return result

    result["passed"] = True

    # Extract basic properties
    parts = list(score.parts)
    result["details"]["num_parts"] = len(parts)

    if not parts:
        result["warnings"].append("music21 found no parts")
        return result

    part = parts[0]
    result["details"]["part_name"] = part.partName or "(unnamed)"

    # Key signatures
    keys = list(part.flatten().getElementsByClass("KeySignature"))
    if keys:
        result["details"]["key_signatures"] = [
            {"measure": k.measureNumber, "sharps": k.sharps, "name": str(k)}
            for k in keys[:5]  # limit output
        ]
    else:
        result["warnings"].append("No key signatures found by music21")

    # Time signatures
    time_sigs = list(part.flatten().getElementsByClass("TimeSignature"))
    if time_sigs:
        result["details"]["time_signatures"] = [
            {"measure": ts.measureNumber, "value": ts.ratioString}
            for ts in time_sigs[:5]
        ]
    else:
        result["warnings"].append("No time signatures found by music21")

    # Clefs
    clefs = list(part.flatten().getElementsByClass("Clef"))
    if clefs:
        result["details"]["clefs"] = [
            {"measure": c.measureNumber, "name": c.name, "sign": c.sign, "line": c.line}
            for c in clefs[:5]
        ]

    # Note count
    notes = list(part.flatten().notes)
    result["details"]["total_note_events"] = len(notes)

    pitches = [n for n in notes if n.isNote]
    chords = [n for n in notes if n.isChord]
    rests = list(part.flatten().getElementsByClass("Rest"))

    result["details"]["pitched_notes"] = len(pitches)
    result["details"]["chords"] = len(chords)
    result["details"]["rests"] = len(rests)

    # Measure count
    all_measures = list(part.getElementsByClass("Measure"))
    result["details"]["num_measures"] = len(all_measures)

    # Total duration in quarter notes
    result["details"]["total_duration_quarters"] = float(part.duration.quarterLength)

    # Pitch range
    if pitches:
        pitch_values = [n.pitch.midi for n in pitches]
        low = music21.pitch.Pitch(midi=min(pitch_values))
        high = music21.pitch.Pitch(midi=max(pitch_values))
        result["details"]["pitch_range"] = f"{low.nameWithOctave} - {high.nameWithOctave}"
        result["details"]["pitch_range_midi"] = f"{min(pitch_values)}-{max(pitch_values)}"

    # Check for common issues
    # Viola typical range: C3 to E6 (MIDI 48 to 76, but can go higher)
    if pitches:
        low_midi = min(n.pitch.midi for n in pitches)
        high_midi = max(n.pitch.midi for n in pitches)
        if low_midi < 36:  # Below C2 -- unlikely for viola
            result["warnings"].append(
                f"Suspiciously low note: MIDI {low_midi} "
                f"({music21.pitch.Pitch(midi=low_midi).nameWithOctave})"
            )
        if high_midi > 88:  # Above E6 -- very unusual for viola
            result["warnings"].append(
                f"Suspiciously high note: MIDI {high_midi} "
                f"({music21.pitch.Pitch(midi=high_midi).nameWithOctave})"
            )

    return result


# ---------------------------------------------------------------------------
# 4. Comparison with reference
# ---------------------------------------------------------------------------


def compare_with_reference(test_path: Path, ref_path: Path) -> dict:
    """Compare a MusicXML output against a reference file."""
    result = {
        "check": "reference_comparison",
        "passed": False,
        "details": {},
        "warnings": [],
    }

    try:
        import music21
    except ImportError:
        result["details"]["error"] = "music21 not installed"
        return result

    try:
        test_score = music21.converter.parse(str(test_path))
        ref_score = music21.converter.parse(str(ref_path))
    except Exception as e:
        result["details"]["error"] = f"Parse error: {e}"
        return result

    test_part = list(test_score.parts)[0] if test_score.parts else None
    ref_part = list(ref_score.parts)[0] if ref_score.parts else None

    if not test_part or not ref_part:
        result["details"]["error"] = "Could not extract parts"
        return result

    # Compare measure count
    test_measures = len(list(test_part.getElementsByClass("Measure")))
    ref_measures = len(list(ref_part.getElementsByClass("Measure")))
    result["details"]["measures"] = {
        "test": test_measures,
        "reference": ref_measures,
        "match": test_measures == ref_measures,
    }

    # Compare note count
    test_notes = len(list(test_part.flatten().notes))
    ref_notes = len(list(ref_part.flatten().notes))
    result["details"]["note_events"] = {
        "test": test_notes,
        "reference": ref_notes,
        "match": test_notes == ref_notes,
        "difference": test_notes - ref_notes,
    }

    # Compare total duration
    test_dur = float(test_part.duration.quarterLength)
    ref_dur = float(ref_part.duration.quarterLength)
    result["details"]["total_duration_quarters"] = {
        "test": test_dur,
        "reference": ref_dur,
        "match": abs(test_dur - ref_dur) < 0.5,
        "difference": round(test_dur - ref_dur, 2),
    }

    # Compare key signatures
    test_keys = list(test_part.flatten().getElementsByClass("KeySignature"))
    ref_keys = list(ref_part.flatten().getElementsByClass("KeySignature"))
    if test_keys and ref_keys:
        result["details"]["first_key"] = {
            "test": test_keys[0].sharps,
            "reference": ref_keys[0].sharps,
            "match": test_keys[0].sharps == ref_keys[0].sharps,
        }

    # Compare time signatures
    test_ts = list(test_part.flatten().getElementsByClass("TimeSignature"))
    ref_ts = list(ref_part.flatten().getElementsByClass("TimeSignature"))
    if test_ts and ref_ts:
        result["details"]["first_time_sig"] = {
            "test": test_ts[0].ratioString,
            "reference": ref_ts[0].ratioString,
            "match": test_ts[0].ratioString == ref_ts[0].ratioString,
        }

    # Per-measure pitch comparison (first N measures)
    max_compare = min(10, test_measures, ref_measures)
    measure_matches = 0
    measure_details = []

    test_measures_list = list(test_part.getElementsByClass("Measure"))[:max_compare]
    ref_measures_list = list(ref_part.getElementsByClass("Measure"))[:max_compare]

    for i, (tm, rm) in enumerate(zip(test_measures_list, ref_measures_list)):
        test_pitches = [
            n.pitch.nameWithOctave for n in tm.flatten().notes if n.isNote
        ]
        ref_pitches = [
            n.pitch.nameWithOctave for n in rm.flatten().notes if n.isNote
        ]

        match = test_pitches == ref_pitches
        if match:
            measure_matches += 1

        measure_details.append({
            "measure": i + 1,
            "test_pitches": test_pitches[:10],  # limit for readability
            "ref_pitches": ref_pitches[:10],
            "pitch_match": match,
        })

    result["details"]["measure_comparison"] = {
        "compared": max_compare,
        "matching": measure_matches,
        "accuracy": round(measure_matches / max_compare * 100, 1) if max_compare > 0 else 0,
        "per_measure": measure_details,
    }

    # Overall pass: basic structure matches
    all_match = all([
        result["details"]["measures"]["match"],
        abs(result["details"]["note_events"]["difference"]) < ref_notes * 0.2,  # within 20%
        result["details"]["total_duration_quarters"]["match"],
    ])
    result["passed"] = all_match

    if not result["details"]["measures"]["match"]:
        result["warnings"].append(
            f"Measure count mismatch: {test_measures} vs {ref_measures}"
        )

    note_diff_pct = (
        abs(result["details"]["note_events"]["difference"]) / ref_notes * 100
        if ref_notes > 0 else 0
    )
    if note_diff_pct > 10:
        result["warnings"].append(
            f"Note count differs by {note_diff_pct:.0f}% "
            f"({test_notes} vs {ref_notes})"
        )

    return result


# ---------------------------------------------------------------------------
# Run all checks
# ---------------------------------------------------------------------------


def validate(
    xml_path: str | Path,
    reference_path: str | Path | None = None,
) -> dict:
    """Run all validation checks on a MusicXML file."""
    xml_path = Path(xml_path)

    if not xml_path.exists():
        return {"error": f"File not found: {xml_path}", "checks": []}

    log.info("Validating: %s", xml_path)
    checks = []

    # 1. XML well-formedness
    r = check_xml_wellformed(xml_path)
    checks.append(r)
    log.info(
        "  XML well-formed: %s%s",
        "PASS" if r["passed"] else "FAIL",
        f" ({r['details'].get('error', '')})" if not r["passed"] else "",
    )

    # 2. MusicXML structure
    r = check_musicxml_structure(xml_path)
    checks.append(r)
    log.info(
        "  MusicXML structure: %s (%d measures, %d notes, %d rests)",
        "PASS" if r["passed"] else "WARN",
        r["details"].get("num_measures", 0),
        r["details"].get("total_notes", 0),
        r["details"].get("total_rests", 0),
    )
    for w in r.get("warnings", []):
        log.warning("    %s", w)

    # 3. Music21 parsing
    r = check_music21(xml_path)
    checks.append(r)
    if r["passed"]:
        log.info(
            "  Music21 parse: PASS (%d notes, %d measures, range %s)",
            r["details"].get("pitched_notes", 0),
            r["details"].get("num_measures", 0),
            r["details"].get("pitch_range", "?"),
        )
    else:
        log.info(
            "  Music21 parse: %s",
            "FAIL" if r["details"].get("error") else "WARN",
        )
    for w in r.get("warnings", []):
        log.warning("    %s", w)

    # 4. Reference comparison
    if reference_path:
        reference_path = Path(reference_path)
        if reference_path.exists():
            r = compare_with_reference(xml_path, reference_path)
            checks.append(r)
            mc = r["details"].get("measure_comparison", {})
            log.info(
                "  Reference comparison: %s (measures: %s, notes: %s, "
                "pitch accuracy: %s%%)",
                "PASS" if r["passed"] else "FAIL",
                "match" if r["details"].get("measures", {}).get("match") else "MISMATCH",
                "match" if r["details"].get("note_events", {}).get("match") else "MISMATCH",
                mc.get("accuracy", "?"),
            )
            for w in r.get("warnings", []):
                log.warning("    %s", w)
        else:
            log.warning("  Reference file not found: %s", reference_path)

    # Overall summary
    passed = sum(1 for c in checks if c["passed"])
    total = len(checks)

    summary = {
        "file": str(xml_path),
        "reference": str(reference_path) if reference_path else None,
        "checks_passed": passed,
        "checks_total": total,
        "all_passed": passed == total,
        "checks": checks,
    }

    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Validate MusicXML output from LLM Vision converter"
    )
    parser.add_argument(
        "--file",
        default=str(REPO_ROOT / "results" / "llm-vision" / "output.musicxml"),
        help="MusicXML file to validate",
    )
    parser.add_argument(
        "--reference",
        default=None,
        help="Reference MusicXML file for comparison",
    )
    parser.add_argument(
        "--reference-dir",
        default=str(REPO_ROOT / "reference-outputs"),
        help="Directory with reference page outputs (page_1.musicxml, etc.)",
    )
    parser.add_argument(
        "--output-json",
        default=None,
        help="Save validation results to JSON file",
    )
    parser.add_argument(
        "--validate-pages",
        action="store_true",
        help="Also validate individual page outputs",
    )

    args = parser.parse_args()

    # Determine reference
    ref = args.reference
    if ref is None:
        # Try the full HOMR output as default reference
        default_ref = REPO_ROOT / "reference-outputs" / "homr-full-output.musicxml"
        if default_ref.exists():
            ref = str(default_ref)
            log.info("Using default reference: %s", ref)

    # Validate main output
    results = [validate(args.file, reference_path=ref)]

    # Optionally validate individual pages
    if args.validate_pages:
        results_dir = Path(args.file).parent
        ref_dir = Path(args.reference_dir)
        for i in range(1, 20):  # up to 20 pages
            page_file = results_dir / f"page_{i}.musicxml"
            if not page_file.exists():
                break
            page_ref = ref_dir / f"page_{i}.musicxml"
            page_ref_path = str(page_ref) if page_ref.exists() else None
            log.info("")
            r = validate(page_file, reference_path=page_ref_path)
            results.append(r)

    # Save results
    if args.output_json:
        output = Path(args.output_json)
        output.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
        log.info("\nResults saved to: %s", output)

    # Exit code
    all_passed = all(r.get("all_passed", False) for r in results)
    if not all_passed:
        log.info("\nSome checks failed or had warnings. See details above.")
        sys.exit(1)
    else:
        log.info("\nAll checks passed.")


if __name__ == "__main__":
    main()
