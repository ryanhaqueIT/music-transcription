# Audiveris OMR -- Evaluation Results

## Tool Information

| Field | Value |
|-------|-------|
| Tool | Audiveris |
| Version tested | 5.10.0 (installed via MSI on Windows) |
| Latest release | 5.10.2 |
| License | AGPL v3 (free, open source) |
| Repository | https://github.com/Audiveris/audiveris |
| Install method | winget, MSI, .deb, .dmg, or build from source |
| Java requirement | Java 17+ (bundled JRE in installer) |

## Test Run: Mozart Eine Kleine Nachtmusik (Viola part)

**Input**: `test-scores/mozart-eine-kleine-viola.pdf` (5 pages, 115 KB, from IMSLP)

### Execution Summary

| Metric | Value |
|--------|-------|
| Processing time | ~5 minutes (local, Windows 11) |
| Sheets processed | 5 (all pages loaded) |
| .omr file created | Yes (824 KB) |
| MusicXML export | **FAILED** |
| Exit code | 1 |

### What Worked

1. **Installation**: Simple via `winget install Audiveris`. Also available via MSI and Scoop. Installer is ~70 MB and bundles a JRE so it does not depend on system Java.
2. **PDF loading**: Audiveris read all 5 PDF pages without issue, rendering each at 2479x3299 resolution.
3. **Staff detection**: Correctly identified staff lines, systems, and parts across all sheets. Example: Sheet #1 found 10 systems with 1 part each (correct for a solo viola part).
4. **Scale detection**: Accurately computed interline spacing (18-20 pixels), line thickness (2-4 pixels), and beam dimensions.
5. **Multi-page/movement detection**: Correctly split the PDF into multiple movements (Scores 1-9), detected page breaks within sheets, and identified system indentations as movement boundaries.
6. **Note detection**: Most note heads, stems, beams, and slurs were identified. Sheet #1 detected 56 raw measures, Sheet #5 detected 103 raw measures.
7. **Key signatures**: Detected key changes (e.g., flats) though some adjustments were needed (pitch corrections logged).
8. **Batch CLI**: The `-batch -export` flags work correctly for headless operation.

### What Failed

1. **MusicXML export -- `FileSystemAlreadyExistsException`**:
   The export to `.mxl` failed with a `java.nio.file.FileSystemAlreadyExistsException` during the zip filesystem operations when processing later sheets (Sheet #4-5). This appears to be a **known Audiveris bug** related to concurrent access to the .omr zip file during multi-sheet books. The .omr project file was created but the MusicXML could not be written.

2. **Tesseract OCR language data missing**:
   ```
   WARN  Languages 142 | *** No installed OCR languages ***
   WARN  TesseractOCR 335 | The collection of supported languages is empty
   ```
   Audiveris bundles the Tesseract engine but does NOT bundle trained language data. Text items (dynamics labels like "sf", "f", tempo markings, rehearsal letters) could not be OCR'd. The `setup.sh` script downloads `eng.traineddata` to fix this.

3. **Rhythm errors on several measures**:
   - Measure #20: "No timeOffset for HeadChordInter" -- note not assigned a rhythmic position.
   - Measure #30: Rest chord left unplaced.
   - Measure #41: "Voice too long" (excess 1/8) -- Audiveris computed more beats than the time signature allows.
   - Measure #44: Multiple chords without time offsets.

4. **Sheet #2 -- Chords outside measures**:
   Seven `HeadChordInter` objects were detected but could not be assigned to any measure. This happens when barline detection fails at page boundaries or in systems with unusual layout. The CURVES step also errored out on this sheet.

5. **Sheet #5 -- Processing error**:
   Encountered an `Error processing stub` during the LINKS step, preventing the sheet from completing transcription.

### Key Observations

- **Accuracy (what we could observe from logs)**: Audiveris successfully identified the structural elements of the score -- staves, systems, measures, note heads. The rhythm analysis is where errors accumulate, especially at page boundaries and in faster passages with beams.
- **Multi-movement handling**: Audiveris correctly detected 9 separate movements/scores within the PDF. This is important for Eine Kleine Nachtmusik which has 4 movements.
- **Performance**: ~5 minutes for a 5-page part is acceptable but not fast. On GitHub Actions (2-core runner) expect 5-10 minutes.
- **Headless reliability**: The batch mode works but the zip filesystem bug makes it unreliable for multi-page scores. A workaround would be to process one sheet at a time with `--sheets N`.

### Workarounds

1. **Zip bug**: Remove any existing `.omr` file before running (the wrapper script does this automatically).
2. **Missing OCR data**: Run `setup.sh` first, or manually download `eng.traineddata` to the Audiveris config tessdata directory.
3. **Per-sheet processing**: If the multi-sheet export fails, try `--sheets 1`, `--sheets 2`, etc. to process one page at a time.
4. **Force flag**: Use `--force` to reprocess from scratch if a prior `.omr` file exists with partial results.

### Comparison Notes (vs other tools)

| Criterion | Audiveris | Notes |
|-----------|-----------|-------|
| Cost | Free | AGPL v3 |
| Setup difficulty | Medium | Requires installer + tessdata; no pip install |
| PDF support | Native | Built-in PDF rendering via PDFBox |
| Batch/CLI | Yes | `-batch -export` flags |
| GPU required | No | CPU only (Java) |
| Docker available | Yes | Audiforge image (community) |
| MusicXML output | .mxl (compressed) | MusicXML 3.0 format |
| Multi-page | Yes | But buggy with zip export |
| Accuracy | Medium-High | Good structural detection, rhythm errors |
| Active maintenance | Yes | Regular releases (5.10.2 latest) |

### Files Produced

```
results/audiveris/
  mozart-eine-kleine-viola.omr              # Audiveris project file (824 KB)
  mozart-eine-kleine-viola-*.log            # Raw Audiveris output log
  mozart-eine-kleine-viola-meta.json        # Structured result metadata (from convert.py)
```

### Recommendations

1. **Upgrade to 5.10.2** which may fix the FileSystemAlreadyExistsException bug.
2. **Install tessdata** before running -- this is essential for dynamics/text recognition.
3. **Use the wrapper script** (`convert.py`) which handles cleanup, error collection, and metadata.
4. **For CI**: Use the GitHub Actions workflow (`.github/workflows/audiveris.yml`) which installs the Ubuntu .deb and runs the conversion headless.
5. **For best results**: Consider running Audiveris in GUI mode for manual correction of rhythm errors, then re-exporting.
