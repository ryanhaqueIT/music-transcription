# Manual Testing Guide -- Web-Only OMR Services

These services do not expose a public API for PDF-to-MusicXML conversion.
Each must be tested manually through a web browser.

**Test file:** `test-scores/mozart-eine-kleine-viola.pdf`
**Save results to:** `results/web-apis/{service-name}/`

---

## 1. pdftomusicxml.com (DeepScore engine)

### Steps
1. Go to https://pdftomusicxml.com
2. Click the upload area or drag-and-drop the PDF
3. Wait for processing (typically under 30 seconds)
4. Select **MusicXML** as the output format (also offers MIDI, MuseScore .mscz)
5. Download the result
6. Save to `results/web-apis/pdftomusicxml/mozart-eine-kleine-viola.musicxml`

### Settings
- No settings to configure; it auto-detects staves, clefs, etc.
- Supports PDF, JPG, and PNG input

### Pricing
- **Free tier:** First 2 pages free per document, plus one free conversion daily
- **Paid:** Pay-as-you-go (exact per-page pricing not publicly listed)
- SSL encrypted; files auto-deleted within 24 hours

### Notes
- Claims 99% accuracy on born-digital (computer-generated) PDFs
- Powered by DeepScore proprietary engine
- No API or developer access documented
- Contact via /contact page to inquire about API access

---

## 2. Soundslice (web UI for PDF scanning)

The Soundslice Data API exists but explicitly does NOT support PDF/image
scanning.  PDF scanning must be done through the web UI; then you can use
the API to export MusicXML from the resulting slice.

### Steps -- PDF scanning (web UI)
1. Go to https://www.soundslice.com/ and sign in (requires Plus plan, $5/month)
2. Click **Create** > **From a PDF or photo**
3. Upload the PDF
4. Wait for the ML-based OMR to process
5. Review the recognized notation in the editor
6. Fix any recognition errors if desired

### Steps -- MusicXML export (API or web UI)
**Via web UI:**
1. Open the slice in the Soundslice editor
2. Click the three-dot menu > **Export** > **MusicXML**
3. Save to `results/web-apis/soundslice/mozart-eine-kleine-viola.musicxml`

**Via API (after web-UI scan):**
```bash
export SOUNDSLICE_APP_ID=your_app_id
export SOUNDSLICE_PASSWORD=your_password
python convert.py test-scores/mozart-eine-kleine-viola.pdf soundslice --slug <SCOREHASH>
```
The scorehash is visible in the slice URL (e.g., `soundslice.com/slices/AbCdE/`).

### Pricing
- **Free account:** Editor access, no PDF scanning
- **Plus:** $5/month or $50/year -- includes 100 scanned pages/month
- **Teacher:** $20/month -- includes scanning + student management
- **API access:** Separate from Plus; request API credentials from Soundslice

### Notes
- ML-based OMR with ongoing improvements (chord diagrams, slant correction)
- Good for interactive practice; notation is editable in-browser
- API requires separate permission for notation upload (by special request)

---

## 3. ScanScore (desktop + cloud)

### Steps
1. Download ScanScore from https://scan-score.com/en/
2. Install the desktop application (Windows 8+ or macOS 10.12+)
3. Open ScanScore and import the PDF
4. Review the recognized notation and correct errors
5. Export as MusicXML: **File** > **Export** > **MusicXML**
6. Save to `results/web-apis/scanscore/mozart-eine-kleine-viola.musicxml`

### Pricing (annual licenses, no auto-renewal)
- **ScanScore Melody:** ~$9/year -- single staff only (lead sheets, parts)
- **ScanScore Ensemble:** ~$99/year -- up to 4 staves (SATB, small ensembles)
- **ScanScore Professional:** ~$179/year -- unlimited staves (orchestral scores)
- 30-day money-back guarantee on all tiers

### Notes
- Desktop application only; no public API or cloud API
- For our viola part (single staff), even the Melody tier should work
- Supports PDF, image, and camera input
- No programmatic/batch conversion possible

---

## 4. Newzik LiveScores (iPad/web app)

### Steps
1. Go to https://newzik.com/ and create an account
2. Upload the PDF to your Newzik library
3. Click **Convert to LiveScore** on the uploaded PDF
4. Wait for OMR processing (powered by their "Maestria" AI engine)
5. Open the LiveScore and verify recognition quality
6. Export MusicXML: available only on **Premium** plan
7. Save to `results/web-apis/newzik/mozart-eine-kleine-viola.musicxml`

### Pricing
- **Essentials:** EUR 29.99 one-time -- 10 pages of LiveScore conversions, no MusicXML export
- **Premium Monthly:** EUR 9.99/month -- unlimited conversions + MusicXML/MIDI export
- **Premium Annual:** EUR 49.99/year -- same as monthly, better value
- **Premium Lifetime:** EUR 199 one-time -- all Premium features forever

### Notes
- MusicXML export requires Premium subscription
- Free tier only gives 10 pages and no export
- Primarily designed as an iPad sheet music reader
- No public API; all interaction through web/app UI

---

## 5. Scan2Notes / Klangio (web app)

The Klangio API exists but is for AUDIO transcription only (piano, guitar,
drums, vocals).  Scan2Notes (their OMR product) is web-UI only.

### Steps
1. Go to https://scan2notes.klang.io/
2. Upload the PDF or drag-and-drop
3. Wait for AI-powered OMR processing
4. Review detected notation on screen
5. Download as XML (MusicXML), MIDI, or PDF
6. Save to `results/web-apis/klangio/mozart-eine-kleine-viola.musicxml`

### Pricing
- **Free:** Limited scans (exact quota not publicly documented)
- **Klangio API (audio only):** Free tier = 50 requests/month, max 15s audio
  - Startup: $99/month (500 requests)
  - Business: $499/month (3,000 requests)
  - Enterprise: custom pricing

### Notes
- Scan2Notes is separate from the Klangio audio transcription API
- OMR accuracy is competitive; handles standard notation symbols
- Supports notes, rhythms, clefs, key/time signatures, ties, slurs
- No batch/programmatic access for OMR; API form on klang.io/api is for audio only

---

## 6. ACE Studio / acestudio.ai (bonus)

### Steps
1. Go to https://acestudio.ai/pdf-to-musicxml/
2. Upload the PDF
3. Wait for conversion
4. Download the MusicXML result

### Pricing
- **Free:** Up to 10 conversions/day, first 5 pages per PDF, max 2 staves
- **Paid ACE Studio subscription:** Unlimited usage

### Notes
- Run by ACCIDENTAL; separate from the main ACE Studio vocal synthesis product
- 2-stave limit may be fine for single-instrument parts
- No API documented
- Good for quick free tests on simple scores

---

## Testing Checklist

For each service, evaluate:
- [ ] Did it correctly identify the clef (viola = alto clef)?
- [ ] Are the key signature and time signature correct?
- [ ] Note accuracy (pitch and rhythm)
- [ ] Articulations, dynamics, slurs preserved?
- [ ] Multi-measure rests handled?
- [ ] Processing time
- [ ] Output file size and validity (opens in MuseScore/Finale?)
