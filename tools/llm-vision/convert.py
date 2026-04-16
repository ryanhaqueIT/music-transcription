#!/usr/bin/env python3
"""
LLM Vision-based PDF sheet music to MusicXML converter.

Uses PyMuPDF to render PDF pages as images, then sends each page to
an LLM vision API to transcribe the notation into MusicXML.

Supports multiple providers:
  - openrouter: Open-source models via OpenRouter (default)
  - anthropic:  Claude models via Anthropic API

Usage:
    # OpenRouter (default - free/cheap open-source models)
    export OPENROUTER_API_KEY=sk-or-...
    python tools/llm-vision/convert.py --provider openrouter --model qwen/qwen2.5-vl-72b-instruct

    # Anthropic
    export ANTHROPIC_API_KEY=sk-ant-...
    python tools/llm-vision/convert.py --provider anthropic --model claude-sonnet-4-6

Requires:
    pip install openai anthropic pymupdf Pillow
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image

# ---------------------------------------------------------------------------
# Resolve paths so the script works when invoked from any cwd
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
sys.path.insert(0, str(SCRIPT_DIR))

from prompts import (  # noqa: E402
    SYSTEM_PROMPT,
    make_merge_prompt,
    make_page_prompt,
    MERGE_SYSTEM_PROMPT,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("llm-vision")

# ---------------------------------------------------------------------------
# Cost table (per 1M tokens)
# ---------------------------------------------------------------------------
COST_TABLE: dict[str, dict[str, float]] = {
    # Anthropic
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00, "cache_write": 3.75, "cache_read": 0.30},
    "claude-opus-4-6": {"input": 5.00, "output": 25.00, "cache_write": 6.25, "cache_read": 0.50},
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00, "cache_write": 1.25, "cache_read": 0.10},
    # OpenRouter open-source models (approximate, check openrouter.ai/models)
    "qwen/qwen2.5-vl-72b-instruct": {"input": 0.40, "output": 0.40},
    "meta-llama/llama-3.2-90b-vision-instruct": {"input": 0.60, "output": 0.60},
    "mistralai/pixtral-large-2411": {"input": 2.00, "output": 6.00},
    "google/gemini-2.5-flash-preview": {"input": 0.15, "output": 0.60},
    "google/gemini-2.5-pro-preview": {"input": 1.25, "output": 10.00},
}

# Default models per provider
DEFAULT_MODELS = {
    "openrouter": "qwen/qwen2.5-vl-72b-instruct",
    "anthropic": "claude-sonnet-4-6",
}


def estimate_cost(usage: dict, model: str) -> float:
    """Estimate USD cost from token counts."""
    rates = COST_TABLE.get(model, {"input": 1.0, "output": 1.0})
    cost = 0.0
    cost += usage.get("input_tokens", 0) * rates.get("input", 0) / 1_000_000
    cost += usage.get("output_tokens", 0) * rates.get("output", 0) / 1_000_000
    cost += usage.get("cache_write_tokens", 0) * rates.get("cache_write", rates.get("input", 0)) / 1_000_000
    cost += usage.get("cache_read_tokens", 0) * rates.get("cache_read", rates.get("input", 0)) / 1_000_000
    return cost


# ---------------------------------------------------------------------------
# PDF to images
# ---------------------------------------------------------------------------


def pdf_to_images(
    pdf_path: str | Path, dpi: int = 200
) -> list[tuple[bytes, str]]:
    """Convert each page of a PDF to a PNG image.

    Returns a list of (png_bytes, media_type) tuples.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    doc = fitz.open(str(pdf_path))
    images: list[tuple[bytes, str]] = []

    zoom = dpi / 72  # 72 is the default PDF DPI
    matrix = fitz.Matrix(zoom, zoom)

    for page_num in range(len(doc)):
        page = doc[page_num]
        pix = page.get_pixmap(matrix=matrix)

        # Convert to PNG bytes via PIL to control quality/size
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

        # If image is very large, scale down to keep under API limits
        max_dim = 2048
        if max(img.size) > max_dim:
            ratio = max_dim / max(img.size)
            new_size = (int(img.width * ratio), int(img.height * ratio))
            img = img.resize(new_size, Image.LANCZOS)
            log.info(
                "Page %d resized from %dx%d to %dx%d",
                page_num + 1, pix.width, pix.height, *new_size,
            )

        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        images.append((buf.getvalue(), "image/png"))
        log.info(
            "Page %d: %dx%d, %.1f KB",
            page_num + 1, img.width, img.height, len(buf.getvalue()) / 1024,
        )

    doc.close()
    return images


# ---------------------------------------------------------------------------
# Provider abstraction
# ---------------------------------------------------------------------------


def create_client(provider: str):
    """Create an API client based on provider."""
    if provider == "anthropic":
        import anthropic
        return anthropic.Anthropic()
    elif provider == "openrouter":
        from openai import OpenAI
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY environment variable is not set")
        return OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
        )
    else:
        raise ValueError(f"Unknown provider: {provider}. Use 'openrouter' or 'anthropic'.")


# ---------------------------------------------------------------------------
# Transcribe a single page
# ---------------------------------------------------------------------------


def transcribe_page(
    client,
    provider: str,
    image_data: bytes,
    media_type: str,
    page_number: int,
    total_pages: int,
    model: str,
    start_measure: int = 1,
    instrument_name: str = "Viola",
    clef_hint: str | None = None,
    key_hint: str | None = None,
    time_sig_hint: str | None = None,
) -> dict:
    """Send a single page image to an LLM and get MusicXML back.

    Returns a dict with keys: xml, usage, duration_s, cost, stop_reason.
    """
    b64_image = base64.standard_b64encode(image_data).decode("utf-8")

    user_prompt = make_page_prompt(
        page_number=page_number,
        total_pages=total_pages,
        start_measure=start_measure,
        instrument_name=instrument_name,
        clef_hint=clef_hint,
        key_hint=key_hint,
        time_sig_hint=time_sig_hint,
    )

    t0 = time.perf_counter()

    if provider == "anthropic":
        result = _transcribe_anthropic(client, b64_image, media_type, user_prompt, model)
    else:
        result = _transcribe_openai_compat(client, b64_image, media_type, user_prompt, model)

    result["duration_s"] = time.perf_counter() - t0
    result["xml"] = strip_markdown_fences(result["xml"])
    result["cost"] = estimate_cost(result["usage"], model)

    return result


def _transcribe_anthropic(client, b64_image: str, media_type: str, user_prompt: str, model: str) -> dict:
    """Call Anthropic's Messages API with vision."""
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": b64_image,
                    },
                },
                {"type": "text", "text": user_prompt},
            ],
        }
    ]

    system = [
        {
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }
    ]

    response = client.messages.create(
        model=model,
        max_tokens=64000,
        system=system,
        messages=messages,
    )

    xml_text = "".join(b.text for b in response.content if b.type == "text")
    usage = response.usage

    return {
        "xml": xml_text,
        "usage": {
            "input_tokens": getattr(usage, "input_tokens", 0),
            "output_tokens": getattr(usage, "output_tokens", 0),
            "cache_write_tokens": getattr(usage, "cache_creation_input_tokens", 0),
            "cache_read_tokens": getattr(usage, "cache_read_input_tokens", 0),
        },
        "stop_reason": response.stop_reason,
    }


def _transcribe_openai_compat(client, b64_image: str, media_type: str, user_prompt: str, model: str) -> dict:
    """Call OpenAI-compatible API (OpenRouter, Together, etc.) with vision."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{media_type};base64,{b64_image}",
                    },
                },
                {"type": "text", "text": user_prompt},
            ],
        },
    ]

    response = client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=64000,
        temperature=0.1,
    )

    xml_text = response.choices[0].message.content or ""
    usage = response.usage

    return {
        "xml": xml_text,
        "usage": {
            "input_tokens": getattr(usage, "prompt_tokens", 0) if usage else 0,
            "output_tokens": getattr(usage, "completion_tokens", 0) if usage else 0,
            "cache_write_tokens": 0,
            "cache_read_tokens": 0,
        },
        "stop_reason": response.choices[0].finish_reason,
    }


def strip_markdown_fences(text: str) -> str:
    """Remove ```xml ... ``` wrapping if present."""
    text = text.strip()
    # Remove opening fence
    text = re.sub(r"^```(?:xml|musicxml)?\s*\n?", "", text)
    # Remove closing fence
    text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Merge page XMLs into a single MusicXML document
# ---------------------------------------------------------------------------


def merge_pages_programmatic(page_xmls: list[str]) -> str:
    """Merge page MusicXML fragments into one document using string ops.

    Page 1 should be a complete MusicXML document. Subsequent pages
    should be sequences of <measure> elements.
    """
    if not page_xmls:
        return ""

    if len(page_xmls) == 1:
        return page_xmls[0]

    base = page_xmls[0]

    # Find the closing </part> tag and insert subsequent measures before it
    close_part = "</part>"
    close_idx = base.rfind(close_part)
    if close_idx == -1:
        log.warning("Could not find </part> in page 1 output; falling back to concatenation")
        return "\n".join(page_xmls)

    before = base[:close_idx]
    after = base[close_idx:]

    extra_measures = []
    for page_xml in page_xmls[1:]:
        # Extract just the measure elements from continuation pages
        cleaned = page_xml.strip()
        # Remove any XML declaration or wrapper elements that slipped through
        cleaned = re.sub(r"<\?xml[^?]*\?>", "", cleaned)
        cleaned = re.sub(r"<!DOCTYPE[^>]*>", "", cleaned)
        cleaned = re.sub(r"<score-partwise[^>]*>", "", cleaned)
        cleaned = re.sub(r"</score-partwise>", "", cleaned)
        cleaned = re.sub(r"<part-list>.*?</part-list>", "", cleaned, flags=re.DOTALL)
        cleaned = re.sub(r"<part[^>]*>", "", cleaned)
        cleaned = re.sub(r"</part>", "", cleaned)
        cleaned = cleaned.strip()
        if cleaned:
            extra_measures.append(cleaned)

    merged = before + "\n" + "\n".join(extra_measures) + "\n" + after
    return merged


def merge_pages_llm(client, provider: str, page_xmls: list[str], model: str) -> dict:
    """Use an LLM to merge page MusicXML fragments (fallback for complex cases)."""
    prompt = make_merge_prompt(page_xmls)

    t0 = time.perf_counter()

    if provider == "anthropic":
        system = [{"type": "text", "text": MERGE_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]
        response = client.messages.create(model=model, max_tokens=64000, system=system, messages=[{"role": "user", "content": prompt}])
        xml_text = "".join(b.text for b in response.content if b.type == "text")
        usage = {"input_tokens": getattr(response.usage, "input_tokens", 0), "output_tokens": getattr(response.usage, "output_tokens", 0)}
    else:
        messages = [{"role": "system", "content": MERGE_SYSTEM_PROMPT}, {"role": "user", "content": prompt}]
        response = client.chat.completions.create(model=model, messages=messages, max_tokens=64000, temperature=0.1)
        xml_text = response.choices[0].message.content or ""
        u = response.usage
        usage = {"input_tokens": getattr(u, "prompt_tokens", 0) if u else 0, "output_tokens": getattr(u, "completion_tokens", 0) if u else 0}

    duration = time.perf_counter() - t0
    xml_text = strip_markdown_fences(xml_text)

    return {
        "xml": xml_text,
        "usage": usage,
        "duration_s": duration,
        "cost": estimate_cost(usage, model),
    }


# ---------------------------------------------------------------------------
# Count measures in XML (rough heuristic for measure continuity)
# ---------------------------------------------------------------------------


def count_measures(xml_text: str) -> int:
    """Count <measure> elements in an XML string."""
    return len(re.findall(r"<measure\b", xml_text))


def get_last_measure_number(xml_text: str) -> int:
    """Extract the highest measure number from XML."""
    numbers = re.findall(r'<measure[^>]*number="(\d+)"', xml_text)
    if numbers:
        return max(int(n) for n in numbers)
    return 0


# ---------------------------------------------------------------------------
# Main conversion pipeline
# ---------------------------------------------------------------------------


def convert(
    pdf_path: str | Path,
    output_dir: str | Path,
    provider: str = "openrouter",
    model: str | None = None,
    dpi: int = 200,
    instrument_name: str = "Viola",
    use_llm_merge: bool = False,
) -> dict:
    """Run the full PDF-to-MusicXML conversion pipeline.

    Returns a summary dict with timing, cost, and file paths.
    """
    pdf_path = Path(pdf_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if model is None:
        model = DEFAULT_MODELS.get(provider, DEFAULT_MODELS["openrouter"])

    client = create_client(provider)

    log.info("Converting %s using %s/%s at %d DPI", pdf_path.name, provider, model, dpi)

    # Step 1: Convert PDF to images
    t_start = time.perf_counter()
    images = pdf_to_images(pdf_path, dpi=dpi)
    total_pages = len(images)
    log.info("Extracted %d pages from PDF", total_pages)

    # Step 2: Transcribe each page
    page_results = []
    page_xmls = []
    total_cost = 0.0
    total_input_tokens = 0
    total_output_tokens = 0
    total_cache_write = 0
    total_cache_read = 0

    # Carry forward context between pages
    clef_hint = None
    key_hint = None
    time_sig_hint = None
    next_measure = 1

    for i, (img_bytes, media_type) in enumerate(images):
        page_num = i + 1
        log.info("--- Transcribing page %d/%d (start measure %d) ---", page_num, total_pages, next_measure)

        result = transcribe_page(
            client=client,
            provider=provider,
            image_data=img_bytes,
            media_type=media_type,
            page_number=page_num,
            total_pages=total_pages,
            model=model,
            start_measure=next_measure,
            instrument_name=instrument_name,
            clef_hint=clef_hint,
            key_hint=key_hint,
            time_sig_hint=time_sig_hint,
        )

        page_results.append(result)
        page_xmls.append(result["xml"])

        # Update running totals
        usage = result["usage"]
        total_cost += result["cost"]
        total_input_tokens += usage.get("input_tokens", 0)
        total_output_tokens += usage.get("output_tokens", 0)
        total_cache_write += usage.get("cache_write_tokens", 0)
        total_cache_read += usage.get("cache_read_tokens", 0)

        # Update measure counter for next page
        measures_on_page = count_measures(result["xml"])
        last_measure = get_last_measure_number(result["xml"])
        if last_measure > 0:
            next_measure = last_measure + 1
        else:
            next_measure += measures_on_page

        # On page 1, try to extract key/time/clef for continuity hints
        if page_num == 1:
            clef_match = re.search(r"<sign>(\w)</sign>\s*<line>(\d)</line>", result["xml"])
            if clef_match:
                sign, line = clef_match.group(1), clef_match.group(2)
                clef_names = {"C": "alto", "G": "treble", "F": "bass"}
                clef_hint = f"{clef_names.get(sign, sign)} clef ({sign} line {line})"

            key_match = re.search(r"<fifths>(-?\d+)</fifths>", result["xml"])
            if key_match:
                fifths = int(key_match.group(1))
                key_names = {
                    -7: "Cb", -6: "Gb", -5: "Db", -4: "Ab", -3: "Eb",
                    -2: "Bb", -1: "F", 0: "C", 1: "G", 2: "D",
                    3: "A", 4: "E", 5: "B", 6: "F#", 7: "C#",
                }
                key_name = key_names.get(fifths, f"fifths={fifths}")
                key_hint = f"{key_name} major ({fifths} {'sharp' if fifths > 0 else 'flat'}{'s' if abs(fifths) != 1 else ''})"

            time_match = re.search(
                r"<beats>(\d+)</beats>\s*<beat-type>(\d+)</beat-type>",
                result["xml"],
            )
            if time_match:
                time_sig_hint = f"{time_match.group(1)}/{time_match.group(2)}"

        # Save individual page output
        page_file = output_dir / f"page_{page_num}.musicxml"
        page_file.write_text(result["xml"], encoding="utf-8")

        log.info(
            "Page %d: %d measures, %.1fs, %d in/%d out tokens, $%.4f",
            page_num,
            measures_on_page,
            result["duration_s"],
            usage.get("input_tokens", 0),
            usage.get("output_tokens", 0),
            result["cost"],
        )

    # Step 3: Merge pages
    log.info("--- Merging %d pages ---", total_pages)

    if use_llm_merge:
        merge_result = merge_pages_llm(client, provider, page_xmls, model)
        merged_xml = merge_result["xml"]
        total_cost += merge_result["cost"]
        merge_usage = merge_result["usage"]
        total_input_tokens += merge_usage.get("input_tokens", 0)
        total_output_tokens += merge_usage.get("output_tokens", 0)
        log.info(
            "LLM merge: %.1fs, $%.4f", merge_result["duration_s"], merge_result["cost"]
        )
    else:
        merged_xml = merge_pages_programmatic(page_xmls)
        log.info("Programmatic merge complete")

    # Save merged output
    merged_file = output_dir / "output.musicxml"
    merged_file.write_text(merged_xml, encoding="utf-8")

    total_duration = time.perf_counter() - t_start
    total_measures = count_measures(merged_xml)

    # Step 4: Build summary
    summary = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "pdf": str(pdf_path),
        "model": model,
        "dpi": dpi,
        "total_pages": total_pages,
        "total_measures": total_measures,
        "total_duration_s": round(total_duration, 2),
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "total_cache_write_tokens": total_cache_write,
        "total_cache_read_tokens": total_cache_read,
        "total_cost_usd": round(total_cost, 4),
        "output_file": str(merged_file),
        "page_files": [str(output_dir / f"page_{i+1}.musicxml") for i in range(total_pages)],
        "provider": provider,
        "per_page": [
            {
                "page": i + 1,
                "measures": count_measures(r["xml"]),
                "duration_s": round(r["duration_s"], 2),
                "input_tokens": r["usage"].get("input_tokens", 0),
                "output_tokens": r["usage"].get("output_tokens", 0),
                "cache_write_tokens": r["usage"].get("cache_write_tokens", 0),
                "cache_read_tokens": r["usage"].get("cache_read_tokens", 0),
                "cost_usd": round(r["cost"], 4),
                "stop_reason": r["stop_reason"],
            }
            for i, r in enumerate(page_results)
        ],
    }

    # Save summary
    summary_file = output_dir / "run_summary.json"
    summary_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    # Print summary
    log.info("=" * 60)
    log.info("CONVERSION COMPLETE")
    log.info("=" * 60)
    log.info("Pages:      %d", total_pages)
    log.info("Measures:   %d", total_measures)
    log.info("Duration:   %.1fs (avg %.1fs/page)", total_duration, total_duration / total_pages)
    log.info("Tokens:     %d input, %d output", total_input_tokens, total_output_tokens)
    log.info("Cache:      %d write, %d read", total_cache_write, total_cache_read)
    log.info("Cost:       $%.4f", total_cost)
    log.info("Output:     %s", merged_file)
    log.info("Summary:    %s", summary_file)

    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Convert PDF sheet music to MusicXML using LLM Vision"
    )
    parser.add_argument(
        "--pdf",
        default=str(REPO_ROOT / "test-scores" / "mozart-eine-kleine-viola.pdf"),
        help="Path to the PDF file (default: test-scores/mozart-eine-kleine-viola.pdf)",
    )
    parser.add_argument(
        "--output-dir",
        default=str(REPO_ROOT / "results" / "llm-vision"),
        help="Output directory (default: results/llm-vision/)",
    )
    parser.add_argument(
        "--provider",
        default="openrouter",
        choices=["openrouter", "anthropic"],
        help="API provider (default: openrouter for open-source models)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model ID (default: qwen/qwen2.5-vl-72b-instruct for openrouter, "
             "claude-sonnet-4-6 for anthropic)",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=200,
        help="DPI for PDF rendering (default: 200)",
    )
    parser.add_argument(
        "--instrument",
        default="Viola",
        help="Instrument name for the part (default: Viola)",
    )
    parser.add_argument(
        "--llm-merge",
        action="store_true",
        help="Use LLM to merge pages instead of programmatic merge",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Check for API key based on provider
    if args.provider == "anthropic" and not os.environ.get("ANTHROPIC_API_KEY"):
        log.error("ANTHROPIC_API_KEY environment variable is not set.")
        sys.exit(1)
    elif args.provider == "openrouter" and not os.environ.get("OPENROUTER_API_KEY"):
        log.error("OPENROUTER_API_KEY environment variable is not set.")
        sys.exit(1)

    summary = convert(
        pdf_path=args.pdf,
        output_dir=args.output_dir,
        provider=args.provider,
        model=args.model,
        dpi=args.dpi,
        instrument_name=args.instrument,
        use_llm_merge=args.llm_merge,
    )

    # Exit with error if any page was truncated
    truncated = [
        p["page"] for p in summary["per_page"]
        if p["stop_reason"] == "max_tokens"
    ]
    if truncated:
        log.warning(
            "Pages %s were truncated (hit max_tokens). "
            "Consider increasing --dpi or splitting pages.",
            truncated,
        )
        sys.exit(2)


if __name__ == "__main__":
    main()
