# Music Transcription - PDF to MusicXML Comparison

Systematic evaluation of tools and approaches for converting PDF sheet music into editable MusicXML format.

## Test Scores

| File | Description |
|------|-------------|
| `test-scores/mozart-eine-kleine-viola.pdf` | Mozart - Eine Kleine Nachtmusik (Viola part), IMSLP |

## Approaches Under Test

| Tool | Type | Cost | Status |
|------|------|------|--------|
| **Audiveris** | Desktop (Java) | Free/OSS | Testing |
| **HOMR** | Python + GPU | Free/OSS | Baseline (Colab outputs available) |
| **oemer** | Python + GPU | Free/OSS | Testing |
| **LLM Vision** | Claude API | API cost | Testing |
| **Web APIs** | Various cloud | Free tier / Paid | Testing |

## Reference Outputs

Existing HOMR outputs from Colab are in `reference-outputs/` as a baseline for comparison.

## Evaluation

Each tool's output is scored on:
- Note accuracy (pitch + duration)
- Rhythm accuracy
- Key/time signature detection
- Dynamics/articulation preservation
- Processing time
- Ease of setup

## Quick Start

```bash
# Install Python dependencies
pip install -r requirements.txt

# Run evaluation on all outputs
python evaluation/compare.py
```
