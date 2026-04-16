# oemer - Evaluation Results

## Package Info

- **PyPI**: `pip install oemer` (v0.1.8 as of April 2026)
- **GitHub**: https://github.com/BreezeWhite/oemer
- **Architecture**: End-to-end deep learning OMR (segmentation models + classical CV)
- **Backend**: ONNX Runtime (default) or TensorFlow (optional)
- **Output**: MusicXML (one file per image input)

## GPU Requirements

| Environment | Works? | Speed per page | Notes |
|---|---|---|---|
| **GPU (CUDA)** | Yes | 3-5 minutes | Uses `onnxruntime-gpu` |
| **CPU only** | Yes | 5-15 minutes | Uses `onnxruntime` (CPU). Viable for small jobs. |
| **Windows local** | Yes | Tested on Python 3.14 | Install succeeded, imports work. |
| **Google Colab** | Yes | ~3 min/page on T4 | Official Colab notebook available. |

### Key Finding
oemer **runs on CPU by default** via ONNX Runtime. Unlike HOMR (which uses PyTorch),
oemer's default backend is `onnxruntime` which is lightweight and CPU-friendly. This
makes it the **better candidate for CPU-only local execution**.

To use GPU acceleration, install `onnxruntime-gpu` instead of `onnxruntime`.
Alternatively, pass `--use-tf` to use TensorFlow as the backend.

## Installation Notes

Dependencies are lighter than HOMR:
- `onnxruntime-gpu` (or `onnxruntime` for CPU-only) -- ~200MB
- `opencv-python-headless`, `matplotlib`, `Pillow`
- `scipy`, `scikit-learn`
- No PyTorch dependency (unless you want HOMR)

First run downloads model checkpoints automatically (~300MB).

**Python 3.14 compatibility**: Installed and imported successfully on Python 3.14.0 (Windows).

## Comparison: oemer vs HOMR

| Feature | oemer | HOMR |
|---|---|---|
| **Default backend** | ONNX Runtime | PyTorch |
| **CPU friendliness** | Better (onnxruntime is lighter) | Heavier (full PyTorch) |
| **Install size** | ~500MB total | ~1.5GB+ total |
| **Speed (GPU)** | 3-5 min/page | 15-40 sec/page |
| **Speed (CPU)** | 5-15 min/page | 2-5+ min/page |
| **Title detection** | No | Yes (via easyocr) |
| **Deskewing** | Yes (built-in) | No |
| **Output quality** | Good for clean scans | Better overall (transformer) |
| **Active maintenance** | Less active | More active (v0.4.0) |
| **API style** | CLI/argparse | Programmatic |
| **Clef support** | Treble, Bass, Alto | Treble, Bass, Alto |
| **Multi-page merge** | Manual (via music21) | Manual (via music21) |

### Advantages of oemer over HOMR
1. **Lighter install** -- no PyTorch dependency, uses ONNX Runtime
2. **CPU-viable** -- ONNX Runtime is optimized for CPU inference
3. **Built-in deskewing** -- handles skewed/phone-camera images
4. **TensorFlow option** -- can use TF backend if already installed
5. **Caching** -- `--save-cache` avoids re-running models on same image

### Advantages of HOMR over oemer
1. **Faster with GPU** -- 10-20x faster per page on GPU
2. **Better accuracy** -- transformer-based recognition is state-of-the-art
3. **Title detection** -- extracts title text from sheet music
4. **More active development** -- v0.4.0 vs v0.1.8
5. **Richer MusicXML** -- includes beams, stems, more detailed notation

## Expected Output Quality

Based on the oemer architecture (segmentation + classification):
- **Pitch recognition**: Good for clean, printed sheet music
- **Rhythm recognition**: Reasonable; may struggle with complex rhythms
- **Clef detection**: Supports treble, bass, and alto clefs
- **Key signatures**: Detected via symbol extraction
- **Dynamics/articulations**: Not supported (same limitation as HOMR)
- **Best for**: Clean, single-staff printed sheet music at reasonable resolution

## Running Locally (CPU)

```bash
# Install (CPU only -- lighter)
pip install oemer pymupdf
pip install onnxruntime  # if onnxruntime-gpu pulls in CUDA deps you don't need

# Run
python tools/oemer/convert.py test-scores/mozart-eine-kleine-viola.pdf --output-dir results/oemer/
```

Expect ~25-75 minutes on CPU for a 5-page PDF (slower than HOMR per-page).

## Running on Colab (GPU)

Use the Colab script at `tools/oemer/colab_convert.py`.

1. Upload to Colab
2. Set runtime to T4 GPU (optional, also works on CPU runtime)
3. Upload your PDF
4. Run all cells

## Known Issues

1. **onnxruntime-gpu vs onnxruntime conflict** -- The pip package `oemer` depends on
   `onnxruntime-gpu`. On machines without NVIDIA GPU, you may want to manually install
   `onnxruntime` (CPU) instead and ignore the GPU dependency.
2. **No multi-page merging built-in** -- Each image produces one MusicXML; merging
   requires music21 or manual work.
3. **Less active maintenance** -- Last update was v0.1.8; HOMR is more actively developed.
