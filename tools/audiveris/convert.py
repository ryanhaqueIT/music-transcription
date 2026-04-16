#!/usr/bin/env python3
"""
Audiveris OMR: PDF to MusicXML conversion wrapper.

Uses the locally installed Audiveris (5.10.x) or falls back to Docker
(nirmata1/audiforge:latest) for headless/CI environments.

Usage:
    python convert.py <input.pdf>
    python convert.py <input.pdf> --output-dir ./results
    python convert.py <input.pdf> --docker           # force Docker mode
    python convert.py <input.pdf> --sheets 1-3       # process specific sheets only
"""

import argparse
import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Default paths -- override with env vars or CLI flags
AUDIVERIS_EXE = os.environ.get(
    "AUDIVERIS_EXE",
    r"C:\Program Files\Audiveris\Audiveris.exe"
    if platform.system() == "Windows"
    else "audiveris",
)

JAVA_HOME = os.environ.get(
    "JAVA_HOME",
    r"C:\Program Files\Microsoft\jdk-17.0.18.8-hotspot"
    if platform.system() == "Windows"
    else "",
)

DOCKER_IMAGE = os.environ.get("AUDIFORGE_IMAGE", "nirmata1/audiforge:latest")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_OUTPUT_DIR = REPO_ROOT / "results" / "audiveris"

LOG_FORMAT = "%(asctime)s %(levelname)-5s %(message)s"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
log = logging.getLogger("audiveris-convert")


def find_audiveris_exe() -> Path | None:
    """Locate the Audiveris executable on this machine."""
    # 1. Explicit env / default
    p = Path(AUDIVERIS_EXE)
    if p.is_file():
        return p

    # 2. On PATH
    which = shutil.which("Audiveris") or shutil.which("audiveris")
    if which:
        return Path(which)

    # 3. Common Windows install paths
    if platform.system() == "Windows":
        for candidate in [
            Path(r"C:\Program Files\Audiveris\Audiveris.exe"),
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Audiveris" / "Audiveris.exe",
        ]:
            if candidate.is_file():
                return candidate

    # 4. Linux: check /usr/bin, /opt, snap
    if platform.system() == "Linux":
        for candidate in [
            Path("/usr/bin/audiveris"),
            Path("/opt/audiveris/bin/audiveris"),
            Path("/snap/audiveris/current/bin/audiveris"),
        ]:
            if candidate.is_file():
                return candidate

    return None


def docker_available() -> bool:
    """Return True if docker CLI is reachable."""
    try:
        subprocess.run(
            ["docker", "version"],
            capture_output=True,
            timeout=10,
        )
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def run_audiveris_native(
    pdf_path: Path,
    output_dir: Path,
    exe: Path,
    sheets: str | None = None,
    force: bool = False,
    save_omr: bool = True,
) -> dict:
    """Run Audiveris natively and return a results dict."""

    output_dir.mkdir(parents=True, exist_ok=True)

    # Clean any prior .omr for this file to avoid the FileSystemAlreadyExistsException
    stem = pdf_path.stem
    prior_omr = output_dir / f"{stem}.omr"
    if prior_omr.exists():
        log.info("Removing prior .omr file to avoid zip collision: %s", prior_omr)
        prior_omr.unlink()

    cmd = [str(exe), "-batch", "-export"]
    if save_omr:
        cmd.append("-save")
    if force:
        cmd.append("-force")
    if sheets:
        cmd.extend(["-sheets", sheets])
    cmd.extend(["-output", str(output_dir), "--", str(pdf_path)])

    env = os.environ.copy()
    if JAVA_HOME and Path(JAVA_HOME).is_dir():
        env["JAVA_HOME"] = JAVA_HOME
        java_bin = str(Path(JAVA_HOME) / "bin")
        env["PATH"] = java_bin + os.pathsep + env.get("PATH", "")

    log.info("Running: %s", " ".join(cmd))
    t0 = time.monotonic()

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env,
        timeout=600,  # 10-min timeout
    )

    elapsed = time.monotonic() - t0

    # Save the raw log
    log_file = output_dir / f"{stem}-convert.log"
    with open(log_file, "w", encoding="utf-8") as f:
        f.write(f"=== STDOUT ===\n{proc.stdout}\n")
        f.write(f"=== STDERR ===\n{proc.stderr}\n")
        f.write(f"=== Return code: {proc.returncode} ===\n")

    # Combine stdout+stderr for analysis (Audiveris logs to both)
    full_output = proc.stdout + "\n" + proc.stderr

    # Find output .mxl files
    mxl_files = sorted(output_dir.glob(f"{stem}*.mxl"))

    result = {
        "tool": "audiveris",
        "version": _extract_version(full_output),
        "input_pdf": str(pdf_path),
        "output_dir": str(output_dir),
        "mxl_files": [str(f) for f in mxl_files],
        "omr_file": str(prior_omr) if (output_dir / f"{stem}.omr").exists() else None,
        "log_file": str(log_file),
        "return_code": proc.returncode,
        "elapsed_seconds": round(elapsed, 1),
        "success": proc.returncode == 0 and len(mxl_files) > 0,
        "errors": _extract_errors(full_output),
        "warnings": _extract_warnings(full_output),
        "sheets_processed": _count_sheets(full_output),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    return result


def run_audiveris_docker(
    pdf_path: Path,
    output_dir: Path,
    sheets: str | None = None,
) -> dict:
    """Run Audiveris via the Audiforge Docker image."""

    output_dir.mkdir(parents=True, exist_ok=True)

    # Clean any prior .omr for this file
    stem = pdf_path.stem
    prior_omr = output_dir / f"{stem}.omr"
    if prior_omr.exists():
        prior_omr.unlink()

    # Map host paths into the container
    pdf_host_dir = pdf_path.parent.resolve()
    out_host_dir = output_dir.resolve()

    cmd = [
        "docker", "run", "--rm",
        "-v", f"{pdf_host_dir}:/input:ro",
        "-v", f"{out_host_dir}:/output",
        DOCKER_IMAGE,
        "-batch", "-export",
        "-output", "/output",
        "--", f"/input/{pdf_path.name}",
    ]

    if sheets:
        # Insert before the -- separator
        idx = cmd.index("--")
        cmd.insert(idx, sheets)
        cmd.insert(idx, "-sheets")

    log.info("Running Docker: %s", " ".join(cmd))
    t0 = time.monotonic()

    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)

    elapsed = time.monotonic() - t0

    log_file = output_dir / f"{stem}-convert-docker.log"
    with open(log_file, "w", encoding="utf-8") as f:
        f.write(f"=== STDOUT ===\n{proc.stdout}\n")
        f.write(f"=== STDERR ===\n{proc.stderr}\n")
        f.write(f"=== Return code: {proc.returncode} ===\n")

    full_output = proc.stdout + "\n" + proc.stderr
    mxl_files = sorted(output_dir.glob(f"{stem}*.mxl"))

    return {
        "tool": "audiveris-docker",
        "version": _extract_version(full_output) or f"docker:{DOCKER_IMAGE}",
        "input_pdf": str(pdf_path),
        "output_dir": str(output_dir),
        "mxl_files": [str(f) for f in mxl_files],
        "omr_file": str(prior_omr) if prior_omr.exists() else None,
        "log_file": str(log_file),
        "return_code": proc.returncode,
        "elapsed_seconds": round(elapsed, 1),
        "success": proc.returncode == 0 and len(mxl_files) > 0,
        "errors": _extract_errors(full_output),
        "warnings": _extract_warnings(full_output),
        "sheets_processed": _count_sheets(full_output),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Log parsing helpers
# ---------------------------------------------------------------------------

def _extract_version(output: str) -> str | None:
    for line in output.splitlines():
        if "Version:" in line:
            return line.split("Version:")[-1].strip()
    return None


def _extract_errors(output: str) -> list[str]:
    errors = []
    for line in output.splitlines():
        low = line.lower()
        if "error" in low or "exception" in low:
            # Skip stack trace continuation lines
            if line.strip().startswith("at "):
                continue
            errors.append(line.strip())
    return errors


def _extract_warnings(output: str) -> list[str]:
    warnings = []
    for line in output.splitlines():
        if line.startswith("WARN"):
            warnings.append(line.strip())
    return warnings


def _count_sheets(output: str) -> int:
    """Count how many sheets were loaded."""
    count = 0
    for line in output.splitlines():
        if "StepMonitoring" in line and "| LOAD" in line:
            count += 1
    return count


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def convert(
    pdf_path: str | Path,
    output_dir: str | Path | None = None,
    use_docker: bool = False,
    sheets: str | None = None,
    force: bool = False,
) -> dict:
    """
    High-level conversion entry point.

    Returns a dict with results metadata (paths, timing, errors).
    """
    pdf_path = Path(pdf_path).resolve()
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    output_dir = Path(output_dir).resolve() if output_dir else DEFAULT_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    # Choose execution method
    if use_docker:
        if not docker_available():
            raise RuntimeError("Docker requested but not available on this system.")
        log.info("Using Docker mode: %s", DOCKER_IMAGE)
        result = run_audiveris_docker(pdf_path, output_dir, sheets)
    else:
        exe = find_audiveris_exe()
        if exe:
            log.info("Found Audiveris at: %s", exe)
            result = run_audiveris_native(pdf_path, output_dir, exe, sheets, force)
        elif docker_available():
            log.warning("Audiveris not installed locally, falling back to Docker.")
            result = run_audiveris_docker(pdf_path, output_dir, sheets)
        else:
            raise RuntimeError(
                "Neither Audiveris nor Docker is available. "
                "Install Audiveris (winget install Audiveris) or Docker."
            )

    # Save result metadata as JSON
    meta_file = output_dir / f"{pdf_path.stem}-meta.json"
    with open(meta_file, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    log.info("Metadata saved to: %s", meta_file)

    # Summary
    if result["success"]:
        log.info(
            "SUCCESS: %d MusicXML file(s) in %.1fs",
            len(result["mxl_files"]),
            result["elapsed_seconds"],
        )
        for mxl in result["mxl_files"]:
            log.info("  -> %s", mxl)
    else:
        log.error(
            "FAILED (exit=%d, %.1fs). %d error(s). See: %s",
            result["return_code"],
            result["elapsed_seconds"],
            len(result["errors"]),
            result["log_file"],
        )

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Convert PDF sheet music to MusicXML using Audiveris OMR.",
    )
    parser.add_argument("pdf", help="Path to the input PDF file.")
    parser.add_argument(
        "--output-dir", "-o",
        default=None,
        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--docker", "-d",
        action="store_true",
        help="Force Docker mode (Audiforge image).",
    )
    parser.add_argument(
        "--sheets", "-s",
        default=None,
        help="Sheet range to process, e.g. '1-3' or '1 3 5'.",
    )
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Force reprocessing from scratch.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print result metadata as JSON to stdout.",
    )

    args = parser.parse_args()

    try:
        result = convert(
            pdf_path=args.pdf,
            output_dir=args.output_dir,
            use_docker=args.docker,
            sheets=args.sheets,
            force=args.force,
        )
    except Exception as exc:
        log.exception("Conversion failed: %s", exc)
        sys.exit(1)

    if args.json:
        print(json.dumps(result, indent=2))

    sys.exit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()
