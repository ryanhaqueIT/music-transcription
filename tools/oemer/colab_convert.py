"""
oemer Colab-ready script for PDF-to-MusicXML conversion.

Copy this entire file into a Google Colab notebook cell, or upload it.
Works with or without GPU (GPU recommended for speed).

Steps:
  1. Installs dependencies
  2. Uploads your PDF
  3. Converts each page via oemer
  4. Optionally merges into a single MusicXML
  5. Downloads the results
"""

# =============================================================================
# Cell 1: Install dependencies
# =============================================================================
def install_dependencies():
    import subprocess
    import sys

    # Install oemer and PDF handling
    subprocess.check_call([
        sys.executable, "-m", "pip", "install", "-q",
        "oemer", "pymupdf", "music21"
    ])

    # Check runtime
    try:
        import onnxruntime as ort
        providers = ort.get_available_providers()
        print(f"ONNX Runtime providers: {providers}")
        if "CUDAExecutionProvider" in providers:
            print("GPU acceleration available!")
        else:
            print("Running on CPU (still works, just slower)")
    except ImportError:
        print("WARNING: onnxruntime not found")

install_dependencies()


# =============================================================================
# Cell 2: Upload PDF and convert
# =============================================================================
def run_oemer_pipeline(
    pdf_path: str = None,
    dpi: int = 300,
    merge: bool = True,
    use_tf: bool = False,
    without_deskew: bool = False,
):
    """
    Full pipeline: PDF -> images -> oemer -> MusicXML.

    Args:
        pdf_path: Path to PDF. If None, searches /content/ for uploaded PDFs.
        dpi: Resolution for PDF rendering (300 recommended).
        merge: Whether to merge per-page outputs into a single file.
        use_tf: Use TensorFlow backend instead of ONNX Runtime.
        without_deskew: Skip the deskewing step.
    """
    import os
    import glob
    import time
    from argparse import Namespace

    import fitz  # PyMuPDF

    # --- Find PDF ---
    if pdf_path is None:
        pdfs = [f for f in glob.glob("/content/*.pdf") if "sample_data" not in f]
        if not pdfs:
            raise FileNotFoundError(
                "No PDF found! Upload a PDF via the Files panel on the left, "
                "or pass pdf_path= explicitly."
            )
        pdf_path = pdfs[0]

    pdf_name = os.path.splitext(os.path.basename(pdf_path))[0]
    print(f"Processing: {pdf_name} ({os.path.getsize(pdf_path) / 1024:.0f} KB)")

    # --- Setup directories ---
    os.makedirs("/content/oemer_output/pages", exist_ok=True)

    # --- PDF to images ---
    print("\n--- Step 1: Converting PDF to images ---")
    doc = fitz.open(pdf_path)
    num_pages = len(doc)
    print(f"PDF has {num_pages} page(s)")

    page_images = []
    for i in range(num_pages):
        page = doc[i]
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat)
        img_path = f"/content/oemer_output/pages/page_{i + 1}.png"
        pix.save(img_path)
        page_images.append(img_path)
        print(f"  Page {i + 1}: {pix.width}x{pix.height} px")
    doc.close()

    # --- Process each page ---
    print("\n--- Step 2: Running oemer ---")
    print("  (First run downloads model checkpoints ~300MB)")
    from oemer.ete import extract

    results = []
    total_start = time.time()

    for i, img_path in enumerate(page_images):
        print(f"\nProcessing page {i + 1}/{num_pages}...")
        page_start = time.time()

        args = Namespace(
            img_path=img_path,
            output_path="/content/oemer_output/",
            use_tf=use_tf,
            save_cache=False,
            without_deskew=without_deskew,
        )

        try:
            output_path = extract(args)
            elapsed = time.time() - page_start

            if os.path.exists(output_path):
                size = os.path.getsize(output_path)
                results.append({
                    "page": i + 1, "status": "OK",
                    "musicxml": output_path, "size": size,
                    "time": elapsed,
                })
                print(f"  OK: {size / 1024:.0f} KB, {elapsed:.1f}s")
            else:
                results.append({"page": i + 1, "status": "NO_OUTPUT", "time": elapsed})
                print(f"  No output ({elapsed:.1f}s)")

        except Exception as e:
            elapsed = time.time() - page_start
            results.append({"page": i + 1, "status": "ERROR", "error": str(e), "time": elapsed})
            print(f"  ERROR: {e} ({elapsed:.1f}s)")
            import traceback
            traceback.print_exc()

    total_time = time.time() - total_start
    success_count = sum(1 for r in results if r["status"] == "OK")
    print(f"\nDone: {success_count}/{num_pages} pages in {total_time:.1f}s")

    # --- Merge ---
    merged_path = None
    if merge and success_count > 1:
        print("\n--- Step 3: Merging pages ---")
        try:
            from music21 import converter, stream as m21_stream

            scores = []
            for r in [r for r in results if r["status"] == "OK"]:
                try:
                    parsed = converter.parse(r["musicxml"])
                    if isinstance(parsed, m21_stream.Score):
                        scores.append(parsed)
                    elif isinstance(parsed, m21_stream.Opus):
                        scores.extend(parsed.scores)
                    else:
                        sc = m21_stream.Score()
                        sc.append(parsed)
                        scores.append(sc)
                except Exception as e:
                    print(f"  Page {r['page']} parse error: {e}")

            if len(scores) > 1:
                merged = scores[0]
                base_parts = list(merged.parts)
                for s in scores[1:]:
                    s_parts = list(s.parts)
                    for j, bp in enumerate(base_parts):
                        if j < len(s_parts):
                            for m in s_parts[j].getElementsByClass(m21_stream.Measure):
                                bp.append(m)

                merged_path = f"/content/oemer_output/{pdf_name}_oemer.musicxml"
                merged.write("musicxml", fp=merged_path)
                print(f"Merged: {merged_path} ({os.path.getsize(merged_path) / 1024:.0f} KB)")
            elif len(scores) == 1:
                merged_path = results[0]["musicxml"]
                print(f"Single page, no merge needed: {merged_path}")

        except ImportError:
            print("music21 not available -- skipping merge")

    # --- Summary ---
    print(f"\n{'=' * 50}")
    print(f"Results:")
    for r in results:
        if r["status"] == "OK":
            print(f"  Page {r['page']}: {r['size'] / 1024:.0f} KB, {r['time']:.1f}s")
        else:
            print(f"  Page {r['page']}: {r['status']} ({r.get('error', '')})")

    return results, merged_path


# Run the pipeline
results, merged_path = run_oemer_pipeline()


# =============================================================================
# Cell 3: Download results
# =============================================================================
def download_results():
    """Download all output MusicXML files."""
    import glob
    from google.colab import files

    output_files = glob.glob("/content/oemer_output/*.musicxml")
    print(f"Downloading {len(output_files)} file(s):")
    for f in output_files:
        import os
        print(f"  {os.path.basename(f)} ({os.path.getsize(f) / 1024:.0f} KB)")
        files.download(f)

download_results()
