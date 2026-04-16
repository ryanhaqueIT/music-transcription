"""
Prompt engineering for LLM Vision-based sheet music transcription.

Strategy: We ask Claude to output MusicXML directly rather than an intermediate
format. MusicXML is verbose but well-structured XML, and Claude has strong
knowledge of the format from training data. An intermediate format would require
a separate, error-prone conversion step.

We use a two-phase approach per page:
  1. SYSTEM prompt: Stable context about MusicXML structure, cached across pages.
  2. PAGE prompt: Per-image instructions with measure continuity hints.
"""

# ---------------------------------------------------------------------------
# System prompt -- cached across all page requests for a given run
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are an expert music engraver and MusicXML specialist. Your task is to \
read images of printed sheet music and transcribe them into well-formed \
MusicXML (partwise format, version 4.0).

## MusicXML structure you must follow

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN"
  "http://www.musicxml.org/dtds/partwise.dtd">
<score-partwise version="4.0">
  <part-list>
    <score-part id="P1">
      <part-name>INSTRUMENT_NAME</part-name>
    </score-part>
  </part-list>
  <part id="P1">
    <!-- measures go here -->
  </part>
</score-partwise>
```

## Key rules

1. **Clef detection**: Identify the clef at the start of each system/line. \
Common clefs: treble (G line 2), bass (F line 4), alto/viola (C line 3), \
tenor (C line 4).

2. **Key signature**: Express as <fifths> (e.g. G major = 1, F major = -1). \
Only emit <key> in the first measure or when it changes.

3. **Time signature**: Emit <time> in the first measure or when it changes.

4. **Divisions**: Use divisions="2" (two divisions per quarter note). This \
means: whole=8, half=4, dotted-half=6, quarter=2, dotted-quarter=3, eighth=1, \
dotted-eighth=1.5 (use <dot/> instead), sixteenth=0.5 (not possible with \
divisions=2, so if you see sixteenths, use divisions="4" instead where \
sixteenth=1).

5. **Notes**: Every <note> must have:
   - <pitch> with <step>, optional <alter>, and <octave> (middle C = C4)
   - OR <rest/> for rests
   - <duration> (integer, relative to <divisions>)
   - <voice>1</voice>
   - <type> (whole, half, quarter, eighth, 16th, 32nd)
   - <dot/> if dotted
   - <staff>1</staff>

6. **Ties and slurs**: Use <tie type="start"/> inside <note> and \
<tied type="start"/> inside <notations> for ties. Use <slur> for slurs.

7. **Accidentals**: <alter>1</alter> for sharp, <alter>-1</alter> for flat, \
<alter>0</alter> for natural. Add <accidental> element too.

8. **Beaming**: You may omit <beam> elements; they are optional.

9. **Dynamics and articulations**: Include them in <direction> and \
<notations> where clearly visible, but prioritize pitch/rhythm accuracy.

10. **Measure numbering**: Number measures sequentially starting from 1 \
(or from the provided starting measure number).

11. **Tuplets**: For triplets, use <time-modification> with \
<actual-notes>3</actual-notes><normal-notes>2</normal-notes>.

12. **Repeats**: Use <barline> with <repeat direction="forward"/> or \
<repeat direction="backward"/>.

## Output format

Return ONLY the MusicXML content. No explanation, no markdown fences, \
no commentary. Start with <?xml and end with the closing tag.
"""

# ---------------------------------------------------------------------------
# Per-page user prompt
# ---------------------------------------------------------------------------


def make_page_prompt(
    page_number: int,
    total_pages: int,
    start_measure: int = 1,
    instrument_name: str = "Viola",
    clef_hint: str | None = None,
    key_hint: str | None = None,
    time_sig_hint: str | None = None,
) -> str:
    """Build the user-facing prompt for a single page image.

    Parameters
    ----------
    page_number : int
        1-based page number.
    total_pages : int
        Total pages in the score.
    start_measure : int
        Expected first measure number on this page.
    instrument_name : str
        Name of the instrument/part.
    clef_hint : str or None
        E.g. "alto clef (C line 3)" -- carried forward from previous page.
    key_hint : str or None
        E.g. "G major (1 sharp)" -- carried forward from previous page.
    time_sig_hint : str or None
        E.g. "4/4" -- carried forward from previous page.
    """
    ctx_parts = []

    ctx_parts.append(
        f"This is page {page_number} of {total_pages} of a {instrument_name} part."
    )

    if page_number == 1:
        ctx_parts.append(
            "This is the first page. Include <part-list> and all header information."
        )
    else:
        ctx_parts.append(
            "This is a continuation page. Output ONLY the <measure> elements "
            "for this page (no XML declaration, no <score-partwise> wrapper, "
            "no <part-list>). I will merge them into the full score."
        )

    ctx_parts.append(f"Start numbering measures from {start_measure}.")

    if clef_hint:
        ctx_parts.append(f"The active clef from the previous page is: {clef_hint}.")
    if key_hint:
        ctx_parts.append(f"The active key signature is: {key_hint}.")
    if time_sig_hint:
        ctx_parts.append(f"The active time signature is: {time_sig_hint}.")

    ctx_parts.append(
        "Transcribe every measure visible on this page. Be precise about "
        "pitch (including octave), rhythm, rests, ties, and accidentals. "
        "If a measure is partially visible at the edge of the page, include "
        "what you can see and note it with an XML comment."
    )

    return "\n\n".join(ctx_parts)


# ---------------------------------------------------------------------------
# Merge prompt -- used to ask Claude to combine page fragments
# ---------------------------------------------------------------------------

MERGE_SYSTEM_PROMPT = """\
You are a MusicXML assembly tool. You receive a sequence of MusicXML fragments \
(one per page of a score) and must combine them into a single valid MusicXML \
document.

Rules:
1. Use the first page's header (<score-partwise>, <part-list>, etc.).
2. Combine all <measure> elements sequentially inside a single <part>.
3. Renumber measures if there are gaps or duplicates.
4. Ensure the final document is well-formed XML.
5. Return ONLY the merged MusicXML. No explanation.
"""


def make_merge_prompt(page_xmls: list[str]) -> str:
    """Build the prompt for merging page-level MusicXML fragments."""
    parts = ["Merge these MusicXML page fragments into one complete document:\n"]
    for i, xml in enumerate(page_xmls, 1):
        parts.append(f"--- PAGE {i} ---")
        parts.append(xml)
        parts.append("")
    return "\n".join(parts)
