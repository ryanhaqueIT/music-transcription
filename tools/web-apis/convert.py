"""
Unified PDF-to-MusicXML conversion via web service APIs.

Supports services that expose public APIs:
  - soundslice  : Soundslice Data API (upload notation + export MusicXML)
  - flat         : Flat.io REST API v2 (create score + export MusicXML)
  - klangio      : Klangio Music Analysis API (audio transcription; OMR not yet public)

Services that are web-UI only (no public API):
  - pdftomusicxml.com  -> see manual-test-guide.md
  - ScanScore          -> see manual-test-guide.md
  - Newzik             -> see manual-test-guide.md

Usage:
    python convert.py <pdf_path> <service>
    python convert.py test-scores/mozart-eine-kleine-viola.pdf soundslice

Environment variables (set the ones you need):
    SOUNDSLICE_APP_ID       Soundslice API application ID
    SOUNDSLICE_PASSWORD     Soundslice API password
    FLAT_ACCESS_TOKEN       Flat.io Personal Access Token
    KLANGIO_API_KEY         Klangio API key
"""

from __future__ import annotations

import argparse
import base64
import os
import sys
import time
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RESULTS_DIR = REPO_ROOT / "results" / "web-apis"


def _ensure_output_dir(service: str) -> Path:
    out = RESULTS_DIR / service
    out.mkdir(parents=True, exist_ok=True)
    return out


def _output_path(service: str, pdf_path: Path) -> Path:
    stem = pdf_path.stem
    return _ensure_output_dir(service) / f"{stem}.musicxml"


# ---------------------------------------------------------------------------
# Soundslice
# ---------------------------------------------------------------------------
# API docs:  https://www.soundslice.com/help/data-api/
# Python lib: https://github.com/soundslice/soundsliceapi
#
# IMPORTANT LIMITATION: The Soundslice Data API does NOT support PDF/image
# scanning (OMR).  The upload-notation endpoint only accepts pre-existing
# notation files (MusicXML, Guitar Pro, etc.).  PDF scanning is web-UI only.
#
# The workflow below therefore:
#   1. Creates a slice
#   2. Attempts to upload the PDF as notation (will likely be rejected)
#   3. If accepted, exports MusicXML
#
# In practice you will need to scan PDFs through the web UI, then use the
# API to export MusicXML from the resulting slice.  The export_from_slug()
# helper demonstrates that second step.
# ---------------------------------------------------------------------------

SOUNDSLICE_BASE = "https://www.soundslice.com/api/v1"


def _ss_auth() -> tuple[str, str]:
    app_id = os.environ.get("SOUNDSLICE_APP_ID", "")
    password = os.environ.get("SOUNDSLICE_PASSWORD", "")
    if not app_id or not password:
        raise EnvironmentError(
            "Set SOUNDSLICE_APP_ID and SOUNDSLICE_PASSWORD environment variables."
        )
    return (app_id, password)


def soundslice_convert(pdf_path: Path) -> Path:
    """Upload a notation file to Soundslice, then export MusicXML.

    NOTE: PDF scanning is NOT available via the API.  This function will
    create a slice and attempt the upload, but Soundslice will reject raw
    PDF files through the notation-upload endpoint.  Use the web UI for
    PDF scanning, then call soundslice_export_by_slug() to retrieve MusicXML.
    """
    auth = _ss_auth()
    output = _output_path("soundslice", pdf_path)

    # Step 1 -- create a slice
    print("[soundslice] Creating slice...")
    resp = requests.post(
        f"{SOUNDSLICE_BASE}/slices/",
        auth=auth,
        data={"name": pdf_path.stem, "has_shareable_url": True},
    )
    resp.raise_for_status()
    slug = resp.json()["scorehash"]
    print(f"[soundslice] Created slice: {slug}")

    # Step 2 -- initiate notation upload
    print("[soundslice] Requesting notation upload URL...")
    resp = requests.post(
        f"{SOUNDSLICE_BASE}/slices/{slug}/notation-file/",
        auth=auth,
    )
    resp.raise_for_status()
    upload_url = resp.json()["url"]

    # Step 3 -- PUT the file
    print(f"[soundslice] Uploading {pdf_path.name}...")
    with open(pdf_path, "rb") as f:
        put_resp = requests.put(upload_url, data=f)
    put_resp.raise_for_status()
    print("[soundslice] Upload complete.")

    # Step 4 -- poll until processing finishes (notation uploads are async)
    print("[soundslice] Waiting for processing...")
    for attempt in range(30):
        time.sleep(3)
        resp = requests.get(
            f"{SOUNDSLICE_BASE}/slices/{slug}/",
            auth=auth,
        )
        resp.raise_for_status()
        info = resp.json()
        if info.get("has_notation"):
            break
        print(f"[soundslice]   ... still processing (attempt {attempt + 1})")
    else:
        print("[soundslice] WARNING: timed out waiting for notation processing.")

    # Step 5 -- export MusicXML
    print("[soundslice] Exporting MusicXML...")
    resp = requests.get(
        f"{SOUNDSLICE_BASE}/slices/{slug}/musicxml/",
        auth=auth,
    )
    resp.raise_for_status()
    output.write_text(resp.text, encoding="utf-8")
    print(f"[soundslice] Saved to {output}")
    return output


def soundslice_export_by_slug(slug: str) -> Path:
    """Export MusicXML from an existing Soundslice slice (e.g. after web-UI scan).

    Usage:
        1. Upload your PDF at https://www.soundslice.com/ (web UI)
        2. Note the scorehash/slug from the URL
        3. Call this function with that slug
    """
    auth = _ss_auth()
    out_dir = _ensure_output_dir("soundslice")
    output = out_dir / f"{slug}.musicxml"

    resp = requests.get(
        f"{SOUNDSLICE_BASE}/slices/{slug}/musicxml/",
        auth=auth,
    )
    resp.raise_for_status()
    output.write_text(resp.text, encoding="utf-8")
    print(f"[soundslice] Exported {slug} -> {output}")
    return output


# ---------------------------------------------------------------------------
# Flat.io
# ---------------------------------------------------------------------------
# API docs:   https://flat.io/developers/docs/api/
# Python pkg: pip install flat-api
# OpenAPI:    https://flat.io/developers/api/reference
#
# The REST API supports:
#   - POST /scores  (create score from MusicXML, MIDI, etc.)
#   - GET  /scores/{score}/revisions/{revision}/{format}
#
# PDF import is available in the web UI but is NOT exposed through the REST
# API.  The API only accepts MusicXML, MIDI, Guitar Pro, MuseScore, etc.
# ---------------------------------------------------------------------------

FLAT_BASE = "https://api.flat.io/v2"


def _flat_headers() -> dict[str, str]:
    token = os.environ.get("FLAT_ACCESS_TOKEN", "")
    if not token:
        raise EnvironmentError("Set FLAT_ACCESS_TOKEN environment variable.")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def flat_convert(pdf_path: Path) -> Path:
    """Import a file into Flat.io and export MusicXML.

    NOTE: The Flat.io REST API does NOT accept PDF files.  It accepts
    MusicXML, MIDI, Guitar Pro, MuseScore, and similar notation formats.
    PDF-to-notation conversion is only available through the web UI at
    https://flat.io/pdf-import.

    This function demonstrates the API workflow by uploading the file as
    base64-encoded data.  For PDFs, use the web UI first, then export
    MusicXML via flat_export_by_id().
    """
    headers = _flat_headers()
    output = _output_path("flat-io", pdf_path)

    # Read file and base64-encode
    file_data = pdf_path.read_bytes()
    b64_data = base64.b64encode(file_data).decode("ascii")

    # Step 1 -- create score
    print("[flat] Creating score...")
    payload = {
        "title": pdf_path.stem,
        "privacy": "private",
        "data": b64_data,
        "dataEncoding": "base64",
        "source": {"pdf": True} if pdf_path.suffix.lower() == ".pdf" else {},
    }
    resp = requests.post(f"{FLAT_BASE}/scores", headers=headers, json=payload)
    if resp.status_code == 400:
        error_detail = resp.json().get("message", resp.text)
        print(f"[flat] API rejected the file: {error_detail}")
        print("[flat] The Flat.io API does not support PDF import.")
        print("[flat] Use https://flat.io/pdf-import in a browser instead.")
        raise RuntimeError(f"Flat API rejected file: {error_detail}")

    resp.raise_for_status()
    score_data = resp.json()
    score_id = score_data["id"]
    print(f"[flat] Created score: {score_id}")

    # Step 2 -- get latest revision
    last_revision = score_data.get("lastRevisionId") or "last"

    # Step 3 -- export as MusicXML
    print("[flat] Exporting MusicXML...")
    export_url = f"{FLAT_BASE}/scores/{score_id}/revisions/{last_revision}/xml"
    resp = requests.get(export_url, headers=headers)
    resp.raise_for_status()
    output.write_bytes(resp.content)
    print(f"[flat] Saved to {output}")
    return output


def flat_export_by_id(score_id: str, revision: str = "last") -> Path:
    """Export MusicXML from an existing Flat.io score.

    Usage:
        1. Import your PDF at https://flat.io/pdf-import
        2. Note the score ID from the URL
        3. Call this function with that score ID
    """
    headers = _flat_headers()
    out_dir = _ensure_output_dir("flat-io")
    output = out_dir / f"{score_id}.musicxml"

    export_url = f"{FLAT_BASE}/scores/{score_id}/revisions/{revision}/xml"
    resp = requests.get(export_url, headers=headers)
    resp.raise_for_status()
    output.write_bytes(resp.content)
    print(f"[flat] Exported {score_id} -> {output}")
    return output


# ---------------------------------------------------------------------------
# Klangio
# ---------------------------------------------------------------------------
# API page:  https://klang.io/api/
# Docs:      Access granted after filling out the API request form
#
# The Klangio API is primarily for AUDIO transcription (piano, guitar, drums,
# vocals).  Scan2Notes (their OMR tool) does NOT appear to be part of the
# public API -- it is web-UI only at https://scan2notes.klang.io/
#
# The function below implements the audio-transcription API flow as
# documented.  For sheet-music OMR, use the web UI.
# ---------------------------------------------------------------------------

KLANGIO_BASE = "https://api.klang.io/v1"


def _klangio_headers() -> dict[str, str]:
    key = os.environ.get("KLANGIO_API_KEY", "")
    if not key:
        raise EnvironmentError("Set KLANGIO_API_KEY environment variable.")
    return {
        "Authorization": f"Bearer {key}",
    }


def klangio_convert(pdf_path: Path) -> Path:
    """Submit a file to the Klangio API for transcription.

    WARNING: The Klangio public API is for AUDIO transcription only.
    Scan2Notes (OMR / sheet-music scanning) is web-UI only.
    This function is included for completeness but will fail for PDF inputs.

    For OMR, use https://scan2notes.klang.io/ in a browser.
    """
    headers = _klangio_headers()
    output = _output_path("klangio", pdf_path)

    # Step 1 -- upload file
    print("[klangio] Uploading file...")
    with open(pdf_path, "rb") as f:
        resp = requests.post(
            f"{KLANGIO_BASE}/transcriptions",
            headers=headers,
            files={"file": (pdf_path.name, f, "application/pdf")},
            data={"output_format": "musicxml"},
        )

    if resp.status_code in (400, 415, 422):
        error_detail = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text
        print(f"[klangio] API rejected the file: {error_detail}")
        print("[klangio] The Klangio API does not support PDF/OMR input.")
        print("[klangio] Use https://scan2notes.klang.io/ in a browser instead.")
        raise RuntimeError(f"Klangio API rejected file: {error_detail}")

    resp.raise_for_status()
    job = resp.json()
    job_id = job.get("id") or job.get("transcription_id")
    print(f"[klangio] Transcription started: {job_id}")

    # Step 2 -- poll for completion
    print("[klangio] Waiting for transcription...")
    for attempt in range(60):
        time.sleep(5)
        resp = requests.get(
            f"{KLANGIO_BASE}/transcriptions/{job_id}",
            headers=headers,
        )
        resp.raise_for_status()
        status = resp.json()
        state = status.get("status", "unknown")
        if state == "completed":
            break
        if state == "failed":
            raise RuntimeError(f"Klangio transcription failed: {status}")
        print(f"[klangio]   ... {state} (attempt {attempt + 1})")
    else:
        raise TimeoutError("Klangio transcription timed out after 5 minutes.")

    # Step 3 -- download result
    print("[klangio] Downloading MusicXML...")
    download_url = status.get("download_url") or f"{KLANGIO_BASE}/transcriptions/{job_id}/download"
    resp = requests.get(download_url, headers=headers)
    resp.raise_for_status()
    output.write_bytes(resp.content)
    print(f"[klangio] Saved to {output}")
    return output


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

SERVICES = {
    "soundslice": soundslice_convert,
    "flat": flat_convert,
    "klangio": klangio_convert,
}


def convert(pdf_path: str | Path, service: str) -> Path:
    """Convert a PDF to MusicXML using the specified service.

    Args:
        pdf_path: Path to the input PDF file.
        service:  One of 'soundslice', 'flat', 'klangio'.

    Returns:
        Path to the saved MusicXML file.
    """
    pdf = Path(pdf_path).resolve()
    if not pdf.exists():
        raise FileNotFoundError(f"PDF not found: {pdf}")

    service_lower = service.lower().strip()
    if service_lower not in SERVICES:
        available = ", ".join(sorted(SERVICES.keys()))
        raise ValueError(
            f"Unknown service '{service}'. Available: {available}\n"
            f"For web-only services (pdftomusicxml, scanscore, newzik), "
            f"see manual-test-guide.md"
        )

    func = SERVICES[service_lower]
    return func(pdf)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert PDF sheet music to MusicXML via web service APIs.",
        epilog=(
            "Services without public APIs (pdftomusicxml.com, ScanScore, Newzik) "
            "require manual testing -- see manual-test-guide.md"
        ),
    )
    parser.add_argument("pdf", type=Path, help="Path to the input PDF file")
    parser.add_argument(
        "service",
        choices=sorted(SERVICES.keys()),
        help="Web service to use for conversion",
    )
    parser.add_argument(
        "--slug",
        help="(soundslice only) Export from existing slice by scorehash instead of uploading",
    )
    parser.add_argument(
        "--score-id",
        help="(flat only) Export from existing score by ID instead of uploading",
    )
    args = parser.parse_args()

    # Handle export-from-existing shortcuts
    if args.slug and args.service == "soundslice":
        soundslice_export_by_slug(args.slug)
        return
    if args.score_id and args.service == "flat":
        flat_export_by_id(args.score_id)
        return

    try:
        result = convert(args.pdf, args.service)
        print(f"\nDone. Output: {result}")
    except EnvironmentError as e:
        print(f"\nConfiguration error: {e}", file=sys.stderr)
        sys.exit(1)
    except RuntimeError as e:
        print(f"\nConversion failed: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
