"""
HOMR Colab-ready script for PDF-to-MusicXML conversion.

Copy this entire file into a Google Colab notebook cell, or upload it.
Requires: Runtime > Change runtime type > T4 GPU

Steps:
  1. Installs dependencies
  2. Uploads your PDF
  3. Converts each page via HOMR
  4. Merges into a single MusicXML
  5. Downloads the results
"""

# =============================================================================
# Cell 1: Install dependencies
# =============================================================================
def install_dependencies():
    import subprocess
    import sys

    subprocess.check_call([
        sys.executable, "-m", "pip", "install", "-q",
        "homr", "pymupdf", "music21"
    ])

    # Verify GPU
    import torch
    if torch.cuda.is_available():
        print(f"GPU: {torch.cuda.get_device_name(0)}")
        print(f"VRAM: {torch.cuda.get_device_properties(0).total_mem / 1e9:.1f} GB")
    else:
        print("WARNING: No GPU detected! Go to Runtime > Change runtime type > T4 GPU")
        print("HOMR will still run on CPU but much slower.")

install_dependencies()


# =============================================================================
# Cell 1b: Patch numpy compatibility (needed for numpy >= 2.0)
# =============================================================================
def patch_homr():
    """Fix HOMR autocrop for numpy 2.x compatibility."""
    import importlib
    import inspect
    import homr.autocrop as ac

    src = inspect.getsource(ac.autocrop)
    if "int(x[1])" in src:
        filepath = inspect.getfile(ac)
        with open(filepath, "r") as f:
            content = f.read()
        content = content.replace("int(x[1])", "float(x[1].flat[0])")
        with open(filepath, "w") as f:
            f.write(content)
        importlib.reload(ac)
        print("Patched HOMR autocrop for numpy 2.x compatibility")
    else:
        print("HOMR autocrop already compatible")

patch_homr()


# =============================================================================
# Cell 2: Upload PDF and convert
# =============================================================================
def run_homr_pipeline(pdf_path: str = None, dpi: int = 300, merge: bool = True):
    """
    Full pipeline: PDF -> images -> HOMR -> MusicXML.

    Args:
        pdf_path: Path to PDF. If None, searches /content/ for uploaded PDFs.
        dpi: Resolution for PDF rendering (300 recommended).
        merge: Whether to merge per-page outputs into a single file.
    """
    import os
    import glob
    import shutil
    import time

    import fitz  # PyMuPDF
    from homr.main import process_image, download_weights, ProcessingConfig
    from homr.xml_generator import XmlGeneratorArguments

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
    os.makedirs("/content/omr_output/pages", exist_ok=True)
    os.makedirs("/content/omr_output/work", exist_ok=True)

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
        img_path = f"/content/omr_output/pages/page_{i + 1}.png"
        pix.save(img_path)
        page_images.append(img_path)
        print(f"  Page {i + 1}: {pix.width}x{pix.height} px")
    doc.close()

    # --- Download models ---
    print("\n--- Step 2: Downloading HOMR models ---")
    download_weights()
    print("Models ready!")

    # --- Process each page ---
    print("\n--- Step 3: Running HOMR ---")
    config = ProcessingConfig(
        enable_debug=False,
        enable_cache=False,
        write_staff_positions=False,
        read_staff_positions=False,
        selected_staff=-1,
    )
    xml_args = XmlGeneratorArguments(large_page=None, metronome=None, tempo=None)

    results = []
    total_start = time.time()

    for i, img_path in enumerate(page_images):
        print(f"\nProcessing page {i + 1}/{num_pages}...")
        work_dir = f"/content/omr_output/work/page_{i + 1}"
        os.makedirs(work_dir, exist_ok=True)
        work_img = f"{work_dir}/page_{i + 1}.png"
        shutil.copy2(img_path, work_img)

        page_start = time.time()
        try:
            result_staffs = process_image(work_img, config, xml_args)
            elapsed = time.time() - page_start
            musicxml_path = work_img.replace(".png", ".musicxml")

            if os.path.exists(musicxml_path):
                size = os.path.getsize(musicxml_path)
                results.append({
                    "page": i + 1, "status": "OK",
                    "staffs": len(result_staffs),
                    "musicxml": musicxml_path, "size": size,
                    "time": elapsed,
                })
                # Copy to output dir
                shutil.copy2(musicxml_path, f"/content/omr_output/page_{i + 1}.musicxml")
                print(f"  OK: {len(result_staffs)} staff(s), {size / 1024:.0f} KB, {elapsed:.1f}s")
            else:
                results.append({"page": i + 1, "status": "NO_OUTPUT", "time": elapsed})
                print(f"  No output ({elapsed:.1f}s)")
        except Exception as e:
            elapsed = time.time() - page_start
            results.append({"page": i + 1, "status": "ERROR", "error": str(e), "time": elapsed})
            print(f"  ERROR: {e} ({elapsed:.1f}s)")

    total_time = time.time() - total_start
    success_count = sum(1 for r in results if r["status"] == "OK")
    print(f"\nDone: {success_count}/{num_pages} pages in {total_time:.1f}s")

    # --- Merge ---
    merged_path = None
    if merge and success_count > 0:
        print("\n--- Step 4: Merging pages ---")
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

        if scores:
            if len(scores) == 1:
                merged = scores[0]
            else:
                merged = scores[0]
                base_parts = list(merged.parts)
                for s in scores[1:]:
                    s_parts = list(s.parts)
                    for j, bp in enumerate(base_parts):
                        if j < len(s_parts):
                            for m in s_parts[j].getElementsByClass(m21_stream.Measure):
                                bp.append(m)

            merged_path = f"/content/omr_output/{pdf_name}_homr.musicxml"
            merged.write("musicxml", fp=merged_path)
            print(f"Merged: {merged_path} ({os.path.getsize(merged_path) / 1024:.0f} KB)")

    # --- Summary ---
    print(f"\n{'=' * 50}")
    print(f"Results:")
    for r in results:
        if r["status"] == "OK":
            print(f"  Page {r['page']}: {r['staffs']} staff(s), {r['size'] / 1024:.0f} KB, {r['time']:.1f}s")
        else:
            print(f"  Page {r['page']}: {r['status']} ({r.get('error', '')})")

    return results, merged_path


# Run the pipeline
results, merged_path = run_homr_pipeline()


# =============================================================================
# Cell 3: Download results
# =============================================================================
def download_results():
    """Download all output MusicXML files."""
    import glob
    from google.colab import files

    output_files = glob.glob("/content/omr_output/*.musicxml")
    print(f"Downloading {len(output_files)} file(s):")
    for f in output_files:
        import os
        print(f"  {os.path.basename(f)} ({os.path.getsize(f) / 1024:.0f} KB)")
        files.download(f)

download_results()
