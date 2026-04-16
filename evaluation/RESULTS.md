# HOMR Baseline Evaluation Results

**Test piece**: Mozart - Eine Kleine Nachtmusik, K.525 (Viola part, 5 pages)
**Tool evaluated**: HOMR (via Google Colab)
**Date**: 2026-04-16

## Summary

HOMR successfully produced well-formed MusicXML that parses correctly in music21. The output captures the structural essentials (key, time signature, clef, part count) and contains a plausible note count. However, significant rhythmic errors exist across all pages, particularly in the later movements.

## Key Findings

### What HOMR got right
- **XML validity**: All 6 files (5 pages + 1 combined) are well-formed XML and parse without errors in music21.
- **Key signature**: Correctly identified G major (1 sharp) as the primary key.
- **Time signatures**: Correctly detected 4/4, 3/4 (as 8/8), and 2/2 where movements change.
- **Clef**: Correctly identified Alto clef (C3), appropriate for Viola.
- **Part count**: Single part, as expected.
- **Self-consistency**: The merged page files and the combined file are 100% consistent on pitch and rhythm for the 2040 aligned notes, confirming HOMR's merge step is faithful.
- **Total measures**: 413 measures across all 5 pages.
- **Total notes**: 1951 sounding notes, 280 rests.

### What HOMR got wrong
- **Beat-count errors in 71 of 413 measures (17.2%)**: Many measures have durations that don't sum to the expected beat count for the active time signature. This is the biggest quality issue.
  - **Page 1**: 2 measures with errors (minor -- +0.5ql and -0.5ql)
  - **Page 2**: 1 measure with error (-0.5ql)
  - **Page 3**: 15 measures with errors (most are -2.0ql, suggesting half-measures or misread repeat/volta structure)
  - **Page 4**: 46 measures with errors (severe -- nearly half the page; most -1.0ql to -3.0ql)
  - **Page 5**: 8 measures with errors (includes 6 empty measures at 0ql and one double-length at 8.0ql)
- **Missing time signature on page 5**: The time signature was not detected at all on the final page, likely because it carries over from the previous system and HOMR treats each page independently.
- **Instrument labeling**: The instrument is labeled "Piano" rather than "Viola" in the MusicXML metadata (cosmetic, not structural).
- **Empty measures**: Page 5 has 6 measures with 0 quarter-length content, suggesting HOMR produced placeholder measures with no notes or rests.

### Distribution analysis
- **Pitch distribution** is dominated by G, D, A, B -- consistent with G major tonality. Presence of E-flat, B-flat, C-sharp, and other accidentals matches the key changes in the middle movements (Minuet in C major, movement in E-flat, etc.).
- **Duration distribution**: Mostly eighth notes (1412), quarters (431), 16ths (200), halves (172), wholes (16). Plausible for a Classical-era viola part.

## Scores (self-consistency, pages vs full)

| Metric               | Score    |
|----------------------|----------|
| Pitch accuracy       | 100.00%  |
| Rhythm accuracy      | 100.00%  |
| Structure accuracy   | 100.00%  |
| Overall              | 100.00%  |

These are self-consistency scores (pages merged vs. the combined file HOMR produced). They confirm HOMR's internal merge is correct, but do NOT reflect accuracy against ground truth -- that requires a verified reference score.

## Recommendations for the comparison framework

1. **Ground truth needed**: To compute true accuracy, we need a verified/edited MusicXML of the same Viola part. The HOMR output serves as a baseline to compare other tools against, but not as ground truth.
2. **Beat-count errors are the primary differentiator**: Any tool that produces fewer beat-count violations on this piece is doing meaningfully better.
3. **Page-boundary handling matters**: HOMR's per-page processing loses carry-over information (time signatures, potentially key signatures). Tools that process the full score or stitch pages properly should score higher.
4. **The scoring framework is ready**: `score.py` can compare any candidate MusicXML against either the HOMR output or a ground-truth reference once one is available.

## Files produced

- `evaluation/validate.py` -- MusicXML validation and OMR error detection
- `evaluation/compare.py` -- Side-by-side comparison of two MusicXML files
- `evaluation/score.py` -- Accuracy scoring (pitch, rhythm, structure, overall)
- `evaluation/run_baseline.py` -- Baseline evaluation runner
- `evaluation/baseline-report.md` -- Full baseline report (detailed output)
- `evaluation/comparison-report.html` -- HTML comparison table (pages vs full)
