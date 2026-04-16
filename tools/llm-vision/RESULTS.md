# LLM Vision Approach: PDF Sheet Music to MusicXML

## Approach

Use Claude's vision capabilities to read sheet music PDF pages as images and
output MusicXML notation directly, without any traditional OMR (Optical Music
Recognition) pipeline.

### Pipeline

```
PDF (5 pages)
  |  PyMuPDF renders each page at 200 DPI
  v
PNG images (one per page)
  |  Each sent to Claude Sonnet 4.6 with vision
  |  System prompt cached across pages
  v
Per-page MusicXML fragments
  |  Programmatic merge (or LLM-assisted)
  v
Combined output.musicxml
  |  Validation via music21
  v
Scored against HOMR reference
```

### Model Choice

**Claude Sonnet 4.6** (`claude-sonnet-4-6`) selected for:
- Vision capability with good spatial reasoning
- 64K max output tokens (MusicXML is verbose -- a full page may need 5K-15K tokens)
- $3/M input, $15/M output -- reasonable for a 5-page test
- Prompt caching available (system prompt is ~2K tokens, cached across all 5 pages)

### Cost Estimate

For the 5-page Mozart viola part:
- Input: ~2K system prompt + ~1-2K user prompt + image tokens per page
- Image tokens: roughly 1K-3K tokens per page at 200 DPI
- Output: ~5K-15K tokens per page of MusicXML
- Estimated total: ~50K-100K input tokens, ~50K-75K output tokens
- Estimated cost: **$0.90 - $1.50** for a single run

### Prompt Engineering Strategy

1. **System prompt** (cached): Detailed MusicXML format specification, encoding
   rules for divisions/durations, clef/key/time handling, and strict output
   format constraints.

2. **Page prompt** (per-image): Contextual hints carried from previous pages
   (active clef, key signature, time signature, starting measure number) to
   maintain continuity across page boundaries.

3. **Direct MusicXML output**: We ask for MusicXML directly rather than an
   intermediate notation format. Rationale: MusicXML is well-documented, Claude
   has extensive training data for it, and any intermediate format would require
   a separate conversion step with its own error surface.

4. **Page-by-page processing**: Rather than sending all pages at once (which
   would consume a very large context window and reduce accuracy), we process
   one page at a time and carry forward state.

## Expected Limitations

### Likely Strengths
- **Key/time/clef detection**: LLMs are very good at recognizing these standard
  symbols and encoding them correctly.
- **Simple rhythms**: Quarter, half, whole notes and basic eighth-note patterns
  should be transcribed accurately.
- **Single-voice parts**: A viola part (single melodic line) is the best case
  for this approach.

### Likely Weaknesses
- **Pitch accuracy in dense passages**: Fast sixteenth-note runs with ledger
  lines are hard to read precisely from images. Octave errors are the most
  common failure mode.
- **Alto clef reading**: The viola's alto clef (C3 clef) is less common in
  training data than treble or bass clef. Systematic pitch offset errors are
  possible if the model "thinks" in treble clef.
- **Rhythmic precision**: Complex rhythms (tuplets, syncopation, dotted
  patterns within beamed groups) may be simplified or miscounted.
- **Ties vs slurs**: Visually ambiguous -- the model may confuse them.
- **Repeats and special barlines**: First/second endings, D.C./D.S. markings,
  and codas may be missed or mis-encoded.
- **Dynamics and articulations**: These are lower priority and may be
  inconsistently captured.
- **Page-boundary measures**: Measures that span page breaks (continued from
  previous page) are inherently problematic.
- **Measure count drift**: If the model miscounts measures on one page, all
  subsequent page numbering may be off, requiring manual correction.
- **Hallucinated notes**: The model may "fill in" measures it cannot read
  clearly rather than leaving gaps, making errors harder to detect.
- **Token limit truncation**: Very dense pages with many measures could
  exceed the output token limit, resulting in truncated output.

### Comparison Points vs Traditional OMR

| Aspect | LLM Vision | Traditional OMR (HOMR, Audiveris) |
|--------|-----------|-----------------------------------|
| Setup | API key only | Software install, GPU for some |
| Cost per page | ~$0.20-0.30 | Free (compute cost only) |
| Speed | 15-45s per page | 5-30s per page |
| Pitch accuracy | Good for simple, weaker for dense | Generally better on clear scores |
| Rhythm accuracy | Mixed | Better for complex rhythms |
| Clef handling | May struggle with alto clef | Reliable if model trained on it |
| Dynamics | Sometimes captured | Varies by tool |
| Reproducibility | Non-deterministic | Deterministic |
| Adaptability | Prompt changes = instant | Retraining needed |

## Files

| File | Description |
|------|-------------|
| `convert.py` | Main conversion pipeline: PDF to images to Claude API to MusicXML |
| `prompts.py` | System and page prompts for MusicXML transcription |
| `validate.py` | XML validation, music21 analysis, and reference comparison |
| `RESULTS.md` | This file -- approach documentation |

## Running

```bash
# Set API key
export ANTHROPIC_API_KEY=sk-ant-...

# Run conversion (defaults to test-scores/mozart-eine-kleine-viola.pdf)
python tools/llm-vision/convert.py

# With options
python tools/llm-vision/convert.py \
    --pdf test-scores/mozart-eine-kleine-viola.pdf \
    --output-dir results/llm-vision/ \
    --model claude-sonnet-4-6 \
    --dpi 200

# Validate output
python tools/llm-vision/validate.py

# Validate with reference comparison and per-page analysis
python tools/llm-vision/validate.py \
    --validate-pages \
    --output-json results/llm-vision/validation.json
```

## Output Structure

```
results/llm-vision/
  output.musicxml        -- merged full score
  page_1.musicxml        -- per-page raw outputs
  page_2.musicxml
  ...
  run_summary.json       -- timing, tokens, cost breakdown
  validation.json        -- validation results (if --output-json used)
```
