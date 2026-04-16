"""
HOMR (Homer's OMR) wrapper script for PDF-to-MusicXML conversion.

Converts a PDF of sheet music into MusicXML files using the HOMR library.
Processes each page individually, then optionally merges into a single output.

Requirements:
    pip install homr pymupdf music21

GPU Notes:
    - HOMR uses PyTorch and can run on CPU, but is MUCH faster with CUDA GPU.
    - On CPU: expect 2-5 minutes per page (model download on first run ~250MB).
    - On GPU (e.g. T4): expect 15-40 seconds per page.
    - For GPU acceleration, install: pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121

Usage:
    python convert.py <input.pdf> [--output-dir ./output] [--merge] [--no-merge]

Example:
    python convert.py ../../test-scores/mozart-eine-kleine-viola.pdf --output-dir ./output --merge
"""

import argparse
import os
import shutil
import sys
import time
from pathlib import Path


def patch_homr_numpy_compat():
    """
    Patch HOMR's autocrop module for numpy 2.x compatibility.

    HOMR's autocrop.py uses `int(x[1])` on numpy arrays, which fails with
    numpy >= 2.0 because only 0-dimensional arrays can be converted to scalars.
    This patches it to use `float(x[1].flat[0])` instead.
    """
    try:
        import homr.autocrop as ac
        import inspect
        src = inspect.getsource(ac.autocrop)
        if "int(x[1])" in src:
            filepath = inspect.getfile(ac)
            with open(filepath, "r") as f:
                content = f.read()
            content = content.replace("int(x[1])", "float(x[1].flat[0])")
            with open(filepath, "w") as f:
                f.write(content)
            import importlib
            importlib.reload(ac)
            print("[PATCH] Fixed HOMR autocrop for numpy 2.x compatibility")
    except Exception as e:
        print(f"[PATCH] Could not patch autocrop (may already be fixed): {e}")


def check_gpu():
    """Check if CUDA GPU is available for acceleration."""
    try:
        import torch
        if torch.cuda.is_available():
            name = torch.cuda.get_device_name(0)
            vram = torch.cuda.get_device_properties(0).total_mem / 1e9
            print(f"[GPU] Using: {name} ({vram:.1f} GB VRAM)")
            return True
        else:
            print("[CPU] No CUDA GPU detected. Running on CPU (slower).")
            return False
    except ImportError:
        print("[CPU] PyTorch not found with CUDA support. Running on CPU.")
        return False


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


def process_single_page(img_path: str, work_dir: str, config, xml_args) -> dict:
    """Run HOMR on a single page image. Returns a result dict."""
    from homr.main import process_image

    page_num = int(Path(img_path).stem.split("_")[-1])
    print(f"\n{'=' * 50}")
    print(f"Processing page {page_num}...")

    # HOMR writes output next to the input file, so copy to work dir
    work_img = os.path.join(work_dir, os.path.basename(img_path))
    shutil.copy2(img_path, work_img)

    start = time.time()
    try:
        result_staffs = process_image(work_img, config, xml_args)
        elapsed = time.time() - start

        musicxml_path = work_img.replace(".png", ".musicxml")
        if os.path.exists(musicxml_path):
            size = os.path.getsize(musicxml_path)
            print(f"  OK: {len(result_staffs)} staff(s), {size / 1024:.0f} KB, {elapsed:.1f}s")
            return {
                "page": page_num,
                "status": "OK",
                "staffs": len(result_staffs),
                "musicxml": musicxml_path,
                "size": size,
                "time": elapsed,
            }
        else:
            print(f"  WARNING: No MusicXML output produced ({elapsed:.1f}s)")
            return {"page": page_num, "status": "NO_OUTPUT", "time": elapsed}

    except Exception as e:
        elapsed = time.time() - start
        print(f"  ERROR: {e} ({elapsed:.1f}s)")
        return {"page": page_num, "status": "ERROR", "error": str(e), "time": elapsed}


def merge_pages(results: list[dict], output_path: str, pdf_name: str) -> str | None:
    """Merge per-page MusicXML files into a single score using music21."""
    from music21 import converter, stream as m21_stream

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
        # Merge: append measures from subsequent pages to the first score's parts
        merged = scores[0]
        base_parts = list(merged.parts)
        for subsequent in scores[1:]:
            subsequent_parts = list(subsequent.parts)
            for i, bp in enumerate(base_parts):
                if i < len(subsequent_parts):
                    for m in subsequent_parts[i].getElementsByClass(m21_stream.Measure):
                        bp.append(m)
        print(f"Merged {len(scores)} page(s) into single score")

    merged_path = os.path.join(output_path, f"{pdf_name}_homr.musicxml")
    merged.write("musicxml", fp=merged_path)
    size = os.path.getsize(merged_path)
    print(f"Merged output: {merged_path} ({size / 1024:.0f} KB)")

    # Print score analysis
    print(f"\nScore Analysis:")
    print(f"  Parts: {len(merged.parts)}")
    for i, part in enumerate(merged.parts):
        measures = list(part.getElementsByClass(m21_stream.Measure))
        print(f"    [{i}] {part.partName or 'Unnamed'}: {len(measures)} measures")

    return merged_path


def main():
    parser = argparse.ArgumentParser(
        description="Convert PDF sheet music to MusicXML using HOMR (Homer's OMR)"
    )
    parser.add_argument("pdf_path", help="Path to the input PDF file")
    parser.add_argument(
        "--output-dir",
        default="./output",
        help="Directory for output files (default: ./output)",
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
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable HOMR debug output",
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
    work_dir = os.path.join(output_dir, "work")
    os.makedirs(pages_dir, exist_ok=True)
    os.makedirs(work_dir, exist_ok=True)

    print(f"HOMR PDF-to-MusicXML Converter")
    print(f"{'=' * 50}")
    print(f"Input:  {args.pdf_path}")
    print(f"Output: {output_dir}")
    print()

    # Apply numpy compatibility patch
    patch_homr_numpy_compat()

    # Check GPU
    has_gpu = check_gpu()
    print()

    # Step 1: Convert PDF to images
    print("Step 1: Converting PDF to images...")
    image_paths = pdf_to_images(args.pdf_path, pages_dir, dpi=args.dpi)

    # Step 2: Download models (first run only)
    print("\nStep 2: Loading HOMR models...")
    from homr.main import download_weights, ProcessingConfig
    from homr.xml_generator import XmlGeneratorArguments

    download_weights()

    config = ProcessingConfig(
        enable_debug=args.debug,
        enable_cache=False,
        write_staff_positions=False,
        read_staff_positions=False,
        selected_staff=-1,  # all staves
    )
    xml_args = XmlGeneratorArguments(large_page=None, metronome=None, tempo=None)

    # Step 3: Process each page
    print("\nStep 3: Running HOMR on each page...")
    total_start = time.time()
    results = []
    for img_path in image_paths:
        page_work_dir = os.path.join(work_dir, Path(img_path).stem)
        os.makedirs(page_work_dir, exist_ok=True)
        result = process_single_page(img_path, page_work_dir, config, xml_args)
        results.append(result)

        # Copy successful output to main output dir
        if result["status"] == "OK":
            dest = os.path.join(output_dir, os.path.basename(result["musicxml"]))
            shutil.copy2(result["musicxml"], dest)

    total_time = time.time() - total_start
    success_count = sum(1 for r in results if r["status"] == "OK")

    print(f"\n{'=' * 50}")
    print(f"DONE: {success_count}/{len(image_paths)} pages in {total_time:.1f}s")

    # Step 4: Optionally merge
    if not args.no_merge and success_count > 0:
        print(f"\nStep 4: Merging pages...")
        merge_pages(results, output_dir, pdf_name)

    # Summary
    print(f"\nResults summary:")
    for r in results:
        if r["status"] == "OK":
            print(f"  Page {r['page']}: {r['staffs']} staff(s), "
                  f"{r['size'] / 1024:.0f} KB, {r['time']:.1f}s")
        else:
            print(f"  Page {r['page']}: {r['status']} "
                  f"({r.get('error', 'no output')})")

    print(f"\nOutput directory: {output_dir}")
    return 0 if success_count > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
