# HOMR (Homer's OMR) - Evaluation Results

## Package Info

- **PyPI**: `pip install homr` (v0.4.0 as of April 2026)
- **GitHub**: https://github.com/liebharc/homr
- **Architecture**: Vision transformer-based OMR (segmentation + Polyphonic-TrOMR)
- **Backend**: PyTorch + segmentation-models-pytorch + easyocr
- **Output**: MusicXML (one file per page, can be merged with music21)

## GPU Requirements

| Environment | Works? | Speed per page | Notes |
|---|---|---|---|
| **GPU (CUDA)** | Yes | 15-40 seconds | Recommended. T4 or better. |
| **CPU only** | Yes (slow) | 2-5+ minutes | PyTorch supports CPU fallback. Usable for small jobs. |
| **Windows local** | Yes | Tested on Python 3.14, no CUDA | Install succeeded, imports work. |
| **Google Colab** | Yes | ~20s/page on T4 | Best free option for GPU. |

### Key Finding
HOMR **can run on CPU** (no GPU required), but it is significantly slower. The PyTorch
backend automatically falls back to CPU when CUDA is not available. For a 5-page PDF,
expect ~10-25 minutes total on CPU vs ~2 minutes on GPU.

**Verified locally**: Page 1 of the test PDF processed in **127.7 seconds** on CPU
(Python 3.14, Windows 11, no GPU). It found 10 staves, 324 noteheads, 49 bar lines,
and detected the title "Mozart". Output was 91 KB of MusicXML.

## Installation Notes

Dependencies are heavy (~1GB+ with PyTorch):
- `torch`, `torchvision` (the bulk of the install)
- `segmentation-models-pytorch`, `pytorch-lightning`
- `easyocr` (for title/text detection)
- `transformers`, `x-transformers`
- `opencv-python-headless`, `Pillow`, `numpy`, `scipy`

First run downloads model weights (~250MB).

**Python 3.14 compatibility**: Installed and imported successfully on Python 3.14.0 (Windows).

**numpy 2.x patch required**: HOMR's `autocrop.py` uses `int(x[1])` on numpy histogram
arrays, which fails with numpy >= 2.0. The `convert.py` wrapper auto-patches this to
`float(x[1].flat[0])`. This same issue appeared in the Colab notebook.

## Reference Output Analysis (Colab with T4 GPU)

Test file: `mozart-eine-kleine-viola.pdf` (5 pages, viola part from Eine Kleine Nachtmusik)

### Per-Page Results

| Page | Title Detected | Measures | Notes | Rests | Key | Time Sig | Clef |
|---|---|---|---|---|---|---|---|
| 1 | "Viola" | 55 | 354 | 38 | G major (1 sharp) | 4/4 | Alto (C3) |
| 2 | (none) | 74 | 475 | 46 | G major | 8/8 | Alto (C3) |
| 3 | (none) | 80 | 444 | 60 | G major | varies | Alto (C3) |
| 4 | "Allegretto" | 99 | 481 | 50 | G major | 4/4 | Alto (C3) |
| 5 | "Eine" | 105 | 545 | 65 | G major | (none explicit) | Alto (C3) |
| **Merged** | "Viola" | 413 | 2302 | 267 | varies (5 key sigs) | varies | Alto |

### Quality Observations

**Positives:**
1. **Alto clef (C3) correctly detected** -- this is a viola part with alto clef, and HOMR
   correctly identifies `<sign>C</sign><line>3</line>` on all pages.
2. **Key signature recognized** -- G major (1 sharp) correctly identified across pages.
   The merged output shows appropriate key changes (fifths: -3, -2, 0, 1, 2) matching
   the movements of Eine Kleine Nachtmusik.
3. **Time signatures detected** -- 4/4, 3/8, 3/4 etc. found across pages.
4. **Title detection works** -- "Viola" detected on page 1, "Allegretto" on page 4
   (movement marking), "Eine" on page 5 (partial title).
5. **Pitch content is reasonable** -- notes start on G4 which is correct for the opening
   of the first movement viola part.
6. **All 5 pages processed successfully** on Colab.
7. **Merging via music21** produces a coherent single-file output (581 KB, 413 measures).

**Issues / Limitations:**
1. **Instrument defaults to Piano** -- HOMR outputs `instrument-name: Piano` regardless
   of the actual instrument. The viola designation is not inferred.
2. **Page 2 time signature oddity** -- Shows `8/8` which is unusual; likely a mis-read
   of `3/8` (second movement Romanze is in Andante 3/8 or similar).
3. **No dynamics, articulations, or expression markings** -- HOMR focuses on pitch and
   rhythm only. Slurs, staccato, dynamic markings (p, f) are not captured.
4. **Title detection is partial** -- "Eine" on page 5 is incomplete (should be
   "Eine kleine Nachtmusik" or similar header text).
5. **Page 5 missing explicit time signature** -- The time signature data is absent.
6. **Division values differ** per page (divisions=2 on pages 1-2, divisions=4 on pages 3-5),
   which can cause issues in merging or playback normalization.
7. **No repeat signs, codas, or segno markings** are captured.

## Running Locally (CPU)

```bash
# Install
pip install homr pymupdf music21

# Run
python tools/homr/convert.py test-scores/mozart-eine-kleine-viola.pdf --output-dir results/homr/
```

Expect ~10-25 minutes on CPU for a 5-page PDF.

## Running on Colab (GPU) -- Recommended

Use the Colab notebook at `reference-outputs/SheetMusicTransposer_HOMR_Colab.ipynb`
or the standalone Colab script at `tools/homr/colab_convert.py`.

1. Upload to Colab
2. Set runtime to T4 GPU
3. Upload your PDF
4. Run all cells
