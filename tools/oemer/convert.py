"""
oemer wrapper script for PDF-to-MusicXML conversion.

Converts a PDF of sheet music into MusicXML files using the oemer library.
oemer is an end-to-end OMR system using deep learning (segmentation + classification).

Requirements:
    pip install oemer pymupdf

    For GPU acceleration (optional but recommended):
        pip install onnxruntime-gpu   (replaces onnxruntime)
    For TensorFlow backend (alternative):
        pip install oemer[tf]

GPU Notes:
    - oemer defaults to ONNX Runtime for inference, which works on CPU.
    - CPU inference: ~5-15 minutes per page (usable but slow).
    - GPU inference: ~3-5 minutes per page.
    - First run downloads model checkpoints automatically (~300MB).
    - Unlike HOMR, oemer can run reasonably on CPU via onnxruntime.

Usage:
    python convert.py <input.pdf> [--output-dir ./output] [--use-tf] [--without-deskew]

Example:
    python convert.py ../../test-scores/mozart-eine-kleine-viola.pdf --output-dir ./output
"""

import argparse
import os
import shutil
import sys
import time
from pathlib import Path


def check_runtime():
    """Check which inference runtime is available."""
    gpu_available = False

    # Check ONNX Runtime GPU
    try:
        import onnxruntime as ort
        providers = ort.get_available_providers()
        if "CUDAExecutionProvider" in providers:
            print(f"[GPU] ONNX Runtime with CUDA support")
            gpu_available = True
        else:
            print(f"[CPU] ONNX Runtime (CPU only). Providers: {providers}")
    except ImportError:
        print("[WARN] onnxruntime not installed")

    # Check TensorFlow
    try:
        import tensorflow as tf
        gpus = tf.config.list_physical_devices("GPU")
        if gpus:
            print(f"[GPU] TensorFlow with {len(gpus)} GPU(s)")
            gpu_available = True
        else:
            print(f"[INFO] TensorFlow available (CPU only)")
    except ImportError:
        pass  # TF is optional

    return gpu_available


def pdf_to_images(pdf_path: str, output_dir: str, dpi: int = 300) -> list[str]:
    """Convert each page of a PDF to a PNG image at the specified DPI."""
    import fitz  # PyMuPDF

    doc = fitz.open(pdf_path)
    num_pages = len(doc)
    print(f"PDF has {num_pages} page(s)")

    image_paths = []
    for i in range(num_pages):
        page = doc[i]
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat)
        img_path = os.path.join(output_dir, f"page_{i + 1}.png")
        pix.save(img_path)
        image_paths.append(img_path)
        print(f"  Page {i + 1}: {pix.width}x{pix.height} px")

    doc.close()
    return image_paths


def process_single_page(
    img_path: str,
    output_dir: str,
    use_tf: bool = False,
    without_deskew: bool = False,
    save_cache: bool = False,
) -> dict:
    """Run oemer on a single page image. Returns a result dict."""
    from argparse import Namespace

    page_num = int(Path(img_path).stem.split("_")[-1])
    print(f"\n{'=' * 50}")
    print(f"Processing page {page_num}...")

    # Build args namespace that oemer.ete.extract() expects
    args = Namespace(
        img_path=img_path,
        output_path=output_dir,
        use_tf=use_tf,
        save_cache=save_cache,
        without_deskew=without_deskew,
    )

    start = time.time()
    try:
        from oemer.ete import extract
        output_path = extract(args)
        elapsed = time.time() - start

        if os.path.exists(output_path):
            size = os.path.getsize(output_path)
            print(f"  OK: {size / 1024:.0f} KB, {elapsed:.1f}s")
            return {
                "page": page_num,
                "status": "OK",
                "musicxml": output_path,
                "size": size,
                "time": elapsed,
            }
        else:
            print(f"  WARNING: No MusicXML output produced ({elapsed:.1f}s)")
            return {"page": page_num, "status": "NO_OUTPUT", "time": elapsed}

    except Exception as e:
        elapsed = time.time() - start
        print(f"  ERROR: {e} ({elapsed:.1f}s)")
        import traceback
        traceback.print_exc()
        return {"page": page_num, "status": "ERROR", "error": str(e), "time": elapsed}


def merge_pages(results: list[dict], output_path: str, pdf_name: str) -> str | None:
    """Merge per-page MusicXML files into a single score using music21."""
    try:
        from music21 import converter, stream as m21_stream
    except ImportError:
        print("  music21 not installed -- skipping merge. Install with: pip install music21")
        return None

    successful = [r for r in results if r["status"] == "OK"]
    if not successful:
        print("No pages were successfully processed -- nothing to merge.")
        return None

    scores = []
    for r in successful:
        try:
            parsed = converter.parse(r["musicxml"])
            if isinstance(parsed, m21_stream.Score):
                scores.append(parsed)
            elif isinstance(parsed, m21_stream.Opus):
                for s in parsed.scores:
                    scores.append(s)
            else:
                sc = m21_stream.Score()
                sc.append(parsed)
                scores.append(sc)
            print(f"  Page {r['page']}: loaded for merge")
        except Exception as e:
            print(f"  Page {r['page']}: parse error during merge - {e}")

    if not scores:
        return None

    if len(scores) == 1:
        merged = scores[0]
    else:
        merged = scores[0]
        base_parts = list(merged.parts)
        for subsequent in scores[1:]:
            subsequent_parts = list(subsequent.parts)
            for i, bp in enumerate(base_parts):
                if i < len(subsequent_parts):
                    for m in subsequent_parts[i].getElementsByClass(m21_stream.Measure):
                        bp.append(m)
        print(f"Merged {len(scores)} page(s) into single score")

    merged_path = os.path.join(output_path, f"{pdf_name}_oemer.musicxml")
    merged.write("musicxml", fp=merged_path)
    size = os.path.getsize(merged_path)
    print(f"Merged output: {merged_path} ({size / 1024:.0f} KB)")

    return merged_path


def main():
    parser = argparse.ArgumentParser(
        description="Convert PDF sheet music to MusicXML using oemer (end-to-end OMR)"
    )
    parser.add_argument("pdf_path", help="Path to the input PDF file")
    parser.add_argument(
        "--output-dir",
        default="./output",
        help="Directory for output files (default: ./output)",
    )
    parser.add_argument(
        "--use-tf",
        action="store_true",
        help="Use TensorFlow instead of ONNX Runtime for inference",
    )
    parser.add_argument(
        "--without-deskew",
        action="store_true",
        help="Skip the deskewing/dewarping step",
    )
    parser.add_argument(
        "--save-cache",
        action="store_true",
        help="Cache model predictions for faster re-runs",
    )
    parser.add_argument(
        "--merge",
        action="store_true",
        default=True,
        help="Merge per-page outputs into a single MusicXML (default: True)",
    )
    parser.add_argument(
        "--no-merge",
        action="store_true",
        help="Skip merging -- only produce per-page MusicXML files",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=300,
        help="DPI for PDF-to-image conversion (default: 300)",
    )

    args = parser.parse_args()

    # Validate input
    if not os.path.isfile(args.pdf_path):
        print(f"ERROR: PDF not found: {args.pdf_path}")
        sys.exit(1)

    pdf_name = Path(args.pdf_path).stem

    # Create output directories
    output_dir = os.path.abspath(args.output_dir)
    pages_dir = os.path.join(output_dir, "pages")
    os.makedirs(pages_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    print(f"oemer PDF-to-MusicXML Converter")
    print(f"{'=' * 50}")
    print(f"Input:  {args.pdf_path}")
    print(f"Output: {output_dir}")
    print()

    # Check runtime
    has_gpu = check_runtime()
    if not has_gpu:
        print("  Note: CPU inference will be slower. Consider using Colab with GPU.")
    print()

    # Step 1: Convert PDF to images
    print("Step 1: Converting PDF to images...")
    image_paths = pdf_to_images(args.pdf_path, pages_dir, dpi=args.dpi)

    # Step 2: Process each page with oemer
    print("\nStep 2: Running oemer on each page...")
    print("  (First run will download model checkpoints ~300MB)")
    total_start = time.time()
    results = []
    for img_path in image_paths:
        result = process_single_page(
            img_path,
            output_dir,
            use_tf=args.use_tf,
            without_deskew=args.without_deskew,
            save_cache=args.save_cache,
        )
        results.append(result)

    total_time = time.time() - total_start
    success_count = sum(1 for r in results if r["status"] == "OK")

    print(f"\n{'=' * 50}")
    print(f"DONE: {success_count}/{len(image_paths)} pages in {total_time:.1f}s")

    # Step 3: Optionally merge
    if not args.no_merge and success_count > 1:
        print(f"\nStep 3: Merging pages...")
        merge_pages(results, output_dir, pdf_name)

    # Summary
    print(f"\nResults summary:")
    for r in results:
        if r["status"] == "OK":
            print(f"  Page {r['page']}: {r['size'] / 1024:.0f} KB, {r['time']:.1f}s")
        else:
            print(f"  Page {r['page']}: {r['status']} "
                  f"({r.get('error', 'no output')})")

    print(f"\nOutput directory: {output_dir}")
    return 0 if success_count > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
