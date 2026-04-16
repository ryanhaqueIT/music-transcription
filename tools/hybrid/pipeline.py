#!/usr/bin/env python3
"""
Hybrid PDF-to-MusicXML pipeline (the @Ranats85 approach).

1. Split PDF into individual pages
2. Run Audiveris on each page separately (avoids multi-sheet zip bug)
3. Combine per-page MusicXML drafts into one file
4. Send to LLM (via OpenRouter) for correction/refinement
5. Output final MusicXML

This is the only approach verified end-to-end with proof on X.
Reference: https://x.com/Ranats85/status/2042843901632090328

Usage:
    export OPENROUTER_API_KEY=sk-or-...
    python tools/hybrid/pipeline.py test-scores/mozart-eine-kleine-viola.pdf
"""

import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("hybrid")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "tools" / "llm-vision"))


# ---------------------------------------------------------------------------
# Step 1: Split PDF into individual pages
# ---------------------------------------------------------------------------

def split_pdf(pdf_path: Path, output_dir: Path) -> list[Path]:
    """Split a multi-page PDF into individual single-page PDFs."""
    import fitz  # PyMuPDF

    doc = fitz.open(str(pdf_path))
    pages = []

    for i in range(len(doc)):
        page_pdf = output_dir / f"page_{i+1}.pdf"
        single = fitz.open()
        single.insert_pdf(doc, from_page=i, to_page=i)
        single.save(str(page_pdf))
        single.close()
        pages.append(page_pdf)
        log.info("Split page %d -> %s (%.1f KB)", i + 1, page_pdf.name, page_pdf.stat().st_size / 1024)

    doc.close()
    return pages


# ---------------------------------------------------------------------------
# Step 2: Run Audiveris on each page (avoids multi-sheet zip bug)
# ---------------------------------------------------------------------------

def find_audiveris() -> str | None:
    """Find the Audiveris executable."""
    candidates = [
        os.environ.get("AUDIVERIS_EXE", ""),
        "/opt/audiveris/bin/Audiveris",
        shutil.which("audiveris") or "",
        shutil.which("Audiveris") or "",
    ]
    for c in candidates:
        if c and Path(c).is_file():
            return c
    # Search common paths
    for search_dir in ["/opt", "/usr"]:
        if Path(search_dir).exists():
            for p in Path(search_dir).rglob("Audiveris"):
                if p.is_file():
                    return str(p)
    return None


def run_audiveris_page(page_pdf: Path, output_dir: Path, audiveris_exe: str) -> Path | None:
    """Run Audiveris on a single page PDF. Returns path to .mxl if successful."""
    stem = page_pdf.stem
    page_out = output_dir / stem
    page_out.mkdir(parents=True, exist_ok=True)

    # Clean prior .omr
    omr_file = page_out / f"{stem}.omr"
    if omr_file.exists():
        omr_file.unlink()

    cmd = [audiveris_exe, "-batch", "-export", "-output", str(page_out), "--", str(page_pdf)]

    env = os.environ.copy()
    java_home = os.environ.get("JAVA_HOME", "")
    if java_home and Path(java_home).is_dir():
        env["JAVA_HOME"] = java_home
        env["PATH"] = str(Path(java_home) / "bin") + os.pathsep + env.get("PATH", "")

    log.info("Audiveris on %s ...", page_pdf.name)
    t0 = time.monotonic()

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=180)
        elapsed = time.monotonic() - t0
        log.info("  Finished in %.1fs (rc=%d)", elapsed, proc.returncode)

        # Save log
        log_file = page_out / f"{stem}.log"
        log_file.write_text(proc.stdout + "\n" + proc.stderr, encoding="utf-8")

        # Find .mxl output
        mxl_files = list(page_out.glob("*.mxl"))
        if mxl_files:
            log.info("  -> %s", mxl_files[0].name)
            return mxl_files[0]
        else:
            log.warning("  No .mxl produced for %s", page_pdf.name)
            return None

    except subprocess.TimeoutExpired:
        log.error("  Timeout on %s", page_pdf.name)
        return None
    except Exception as e:
        log.error("  Error on %s: %s", page_pdf.name, e)
        return None


# ---------------------------------------------------------------------------
# Step 3: Combine per-page MusicXML into one draft
# ---------------------------------------------------------------------------

def combine_mxl_pages(mxl_files: list[Path], output_path: Path) -> str:
    """Combine per-page .mxl files into a single MusicXML string."""
    import zipfile
    from lxml import etree

    musicxml_parts = []

    for mxl in mxl_files:
        # .mxl is a zip containing a .xml file
        with zipfile.ZipFile(str(mxl), "r") as z:
            xml_names = [n for n in z.namelist() if n.endswith(".xml") and not n.startswith("META-INF")]
            if xml_names:
                xml_content = z.read(xml_names[0])
                musicxml_parts.append(xml_content)

    if not musicxml_parts:
        return ""

    # Parse first page as base document
    base_tree = etree.fromstring(musicxml_parts[0])
    base_part = base_tree.find(".//part")

    # Append measures from subsequent pages
    for i, xml_bytes in enumerate(musicxml_parts[1:], start=2):
        tree = etree.fromstring(xml_bytes)
        part = tree.find(".//part")
        if part is not None:
            for measure in part.findall("measure"):
                # Renumber measures
                existing_measures = base_part.findall("measure")
                next_num = len(existing_measures) + 1
                measure.set("number", str(next_num))
                base_part.append(measure)

    combined_xml = etree.tostring(base_tree, pretty_print=True, xml_declaration=True, encoding="UTF-8").decode("utf-8")

    output_path.write_text(combined_xml, encoding="utf-8")
    log.info("Combined %d pages -> %s (%d measures)", len(mxl_files), output_path.name,
             len(base_part.findall("measure")))

    return combined_xml


# ---------------------------------------------------------------------------
# Step 4: LLM correction pass via OpenRouter
# ---------------------------------------------------------------------------

def llm_correct(draft_xml: str, pdf_path: Path, output_path: Path, model: str) -> dict:
    """Send draft MusicXML + page images to LLM for correction."""
    from openai import OpenAI
    import fitz
    import base64

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        log.error("OPENROUTER_API_KEY not set, skipping LLM correction")
        return {"skipped": True}

    client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)

    # Render first page as reference image
    doc = fitz.open(str(pdf_path))
    page = doc[0]
    pix = page.get_pixmap(matrix=fitz.Matrix(200 / 72, 200 / 72))
    from PIL import Image
    import io
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    b64_image = base64.standard_b64encode(buf.getvalue()).decode("utf-8")
    doc.close()

    # Truncate draft if too long (keep first 8000 chars + last 2000)
    if len(draft_xml) > 12000:
        draft_snippet = draft_xml[:8000] + "\n<!-- ... truncated ... -->\n" + draft_xml[-2000:]
    else:
        draft_snippet = draft_xml

    system_prompt = """You are an expert music engraver. You receive a draft MusicXML file produced by Audiveris OMR \
and an image of the first page of the original score. Your job is to correct errors in the MusicXML.

Common OMR errors to fix:
- Wrong beat counts per measure (notes don't add up to the time signature)
- Missing or wrong key/time signatures on continuation pages
- Wrong note durations or pitches
- Missing rests
- Instrument labeled as "Piano" when it should match the actual instrument

Rules:
1. Output ONLY corrected MusicXML. No explanation.
2. Keep the overall structure intact - just fix errors.
3. If the draft looks mostly correct, return it with minimal changes.
4. Ensure every measure's note/rest durations sum to the correct beats.
5. Start with <?xml and end with </score-partwise>."""

    user_prompt = f"""Here is a draft MusicXML produced by Audiveris OMR. Please correct any errors.
The piece is for Viola (alto clef, C line 3).

DRAFT MUSICXML:
```xml
{draft_snippet}
```

Look at the attached image of the first page for reference. Fix rhythm errors, wrong pitches, \
missing time signatures, and ensure beat counts are correct in every measure."""

    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_image}"}},
                {"type": "text", "text": user_prompt},
            ],
        },
    ]

    log.info("Sending to %s for correction...", model)
    t0 = time.monotonic()

    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=64000,
            temperature=0.1,
        )

        elapsed = time.monotonic() - t0
        corrected = response.choices[0].message.content or ""

        # Strip markdown fences
        corrected = re.sub(r"^```(?:xml|musicxml)?\s*\n?", "", corrected.strip())
        corrected = re.sub(r"\n?```\s*$", "", corrected).strip()

        usage = response.usage
        input_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
        output_tokens = getattr(usage, "completion_tokens", 0) if usage else 0

        output_path.write_text(corrected, encoding="utf-8")
        log.info("LLM correction done: %.1fs, %d in / %d out tokens", elapsed, input_tokens, output_tokens)

        return {
            "model": model,
            "elapsed_s": round(elapsed, 1),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "output_file": str(output_path),
            "skipped": False,
        }

    except Exception as e:
        log.error("LLM correction failed: %s", e)
        return {"skipped": True, "error": str(e)}


# ---------------------------------------------------------------------------
# Step 5: Full pipeline
# ---------------------------------------------------------------------------

def run_pipeline(
    pdf_path: Path,
    output_dir: Path,
    model: str = "qwen/qwen2.5-vl-72b-instruct",
    skip_llm: bool = False,
    dpi: int = 400,
) -> dict:
    """Run the full hybrid pipeline."""

    output_dir.mkdir(parents=True, exist_ok=True)
    pages_dir = output_dir / "pages"
    pages_dir.mkdir(exist_ok=True)
    audiveris_dir = output_dir / "audiveris_pages"
    audiveris_dir.mkdir(exist_ok=True)

    results = {
        "pipeline": "hybrid",
        "input_pdf": str(pdf_path),
        "model": model,
        "steps": {},
    }

    t_start = time.monotonic()

    # Step 1: Split PDF
    log.info("=== STEP 1: Split PDF into pages ===")
    page_pdfs = split_pdf(pdf_path, pages_dir)
    results["steps"]["split"] = {"pages": len(page_pdfs)}

    # Step 2: Audiveris page-by-page
    log.info("=== STEP 2: Audiveris OMR (page-by-page) ===")
    audiveris_exe = find_audiveris()

    if audiveris_exe:
        log.info("Found Audiveris at: %s", audiveris_exe)
        mxl_files = []
        for page_pdf in page_pdfs:
            mxl = run_audiveris_page(page_pdf, audiveris_dir, audiveris_exe)
            if mxl:
                mxl_files.append(mxl)

        results["steps"]["audiveris"] = {
            "exe": audiveris_exe,
            "pages_processed": len(page_pdfs),
            "mxl_produced": len(mxl_files),
            "mxl_files": [str(f) for f in mxl_files],
        }

        # Step 3: Combine
        if mxl_files:
            log.info("=== STEP 3: Combine page MusicXML ===")
            draft_path = output_dir / "draft.musicxml"
            draft_xml = combine_mxl_pages(mxl_files, draft_path)
            results["steps"]["combine"] = {"output": str(draft_path), "xml_length": len(draft_xml)}
        else:
            log.warning("No MusicXML produced by Audiveris, falling back to LLM-only")
            draft_xml = ""
            draft_path = None
    else:
        log.warning("Audiveris not found, using LLM-only mode")
        draft_xml = ""
        draft_path = None
        mxl_files = []
        results["steps"]["audiveris"] = {"exe": None, "skipped": True}

    # Step 4: LLM correction (or LLM-only if no Audiveris)
    if not skip_llm:
        log.info("=== STEP 4: LLM correction/transcription ===")

        if draft_xml:
            # Correction mode: fix Audiveris draft
            corrected_path = output_dir / "output.musicxml"
            llm_result = llm_correct(draft_xml, pdf_path, corrected_path, model)
            results["steps"]["llm_correction"] = llm_result
        else:
            # LLM-only mode: transcribe from images directly
            log.info("No Audiveris draft available, running LLM-only transcription")
            from convert import convert as llm_convert
            llm_summary = llm_convert(
                pdf_path=pdf_path,
                output_dir=output_dir,
                provider="openrouter",
                model=model,
                dpi=dpi,
            )
            results["steps"]["llm_only"] = llm_summary
    else:
        log.info("Skipping LLM step (--skip-llm)")
        # Use draft as final output
        if draft_path:
            shutil.copy(draft_path, output_dir / "output.musicxml")

    total_elapsed = time.monotonic() - t_start
    results["total_elapsed_s"] = round(total_elapsed, 1)

    # Save results
    results_file = output_dir / "pipeline_results.json"
    results_file.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    log.info("=== PIPELINE COMPLETE (%.1fs) ===", total_elapsed)
    log.info("Results: %s", results_file)

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Hybrid PDF-to-MusicXML pipeline (Audiveris + LLM)")
    parser.add_argument("pdf_path", help="Path to input PDF")
    parser.add_argument("--output-dir", default=str(REPO_ROOT / "results" / "hybrid"), help="Output directory")
    parser.add_argument("--model", default="qwen/qwen2.5-vl-72b-instruct", help="OpenRouter model for LLM step")
    parser.add_argument("--skip-llm", action="store_true", help="Skip LLM correction (Audiveris only)")
    parser.add_argument("--dpi", type=int, default=400, help="DPI for page rendering")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    run_pipeline(
        pdf_path=Path(args.pdf_path),
        output_dir=Path(args.output_dir),
        model=args.model,
        skip_llm=args.skip_llm,
        dpi=args.dpi,
    )


if __name__ == "__main__":
    main()
