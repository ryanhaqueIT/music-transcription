# Web API Services -- Research Results

Summary of PDF-to-MusicXML web services evaluated for API availability,
pricing, and automation potential.

## API Availability Matrix

| Service              | Public API? | PDF/OMR via API? | Auth Method          | Python Pkg       |
|----------------------|-------------|-------------------|----------------------|------------------|
| Soundslice           | Yes         | NO (web UI only)  | HTTP Basic Auth      | soundsliceapi    |
| Flat.io              | Yes         | NO (web UI only)  | Bearer token (OAuth) | flat-api         |
| Klangio              | Yes (audio) | NO (OMR is web)   | Bearer token         | (none)           |
| pdftomusicxml.com    | No          | N/A               | N/A                  | N/A              |
| ScanScore            | No          | N/A               | N/A                  | N/A              |
| Newzik               | No          | N/A               | N/A                  | N/A              |
| ACE Studio (bonus)   | No          | N/A               | N/A                  | N/A              |

### Key finding

**No service offers end-to-end PDF-to-MusicXML conversion through a public API.**

- Soundslice and Flat.io have REST APIs for managing scores and exporting
  MusicXML, but their PDF import / OMR features are web-UI only.
- Klangio has an API but it is for audio transcription, not sheet music scanning.
- The remaining services (pdftomusicxml.com, ScanScore, Newzik) have no API at all.

The best automated workflow is a hybrid approach:
1. Manually upload the PDF through a web UI (Soundslice or Flat.io)
2. Use the API to export MusicXML from the resulting score

## Service Details

### Soundslice
- **API docs:** https://www.soundslice.com/help/data-api/
- **Python library:** https://github.com/soundslice/soundsliceapi
- **What the API can do:**
  - Create/list/delete slices
  - Upload notation files (MusicXML, Guitar Pro -- NOT PDFs)
  - Export MusicXML from any slice
  - Manage recordings and syncpoints
- **What requires web UI:** PDF and image scanning (OMR)
- **API auth:** HTTP Basic with app_id + password (request credentials from Soundslice)
- **OMR engine:** Custom ML model, continuously improved
- **Pricing:**
  - Plus plan: $5/month or $50/year (100 scanned pages/month)
  - API access: separate from Plus, by special request

### Flat.io
- **API docs:** https://flat.io/developers/docs/api/
- **Python library:** `pip install flat-api` (PyPI)
- **What the API can do:**
  - Create scores from MusicXML, MIDI, Guitar Pro, MuseScore files
  - Export as MusicXML (xml/mxl), MIDI, MP3, WAV, PDF
  - Manage scores, collections, and collaborations
- **What requires web UI:** PDF import (https://flat.io/pdf-import)
- **API auth:** Personal Access Token (quick) or OAuth2 (production apps)
- **Pricing:**
  - Free tier: limited scores
  - Power plan: $7.99/month -- unlimited scores, PDF import
  - API rate limits not publicly documented

### Klangio / Scan2Notes
- **API page:** https://klang.io/api/
- **API scope:** Audio transcription only (piano, guitar, bass, vocals, drums)
- **Scan2Notes (OMR):** Web UI only at https://scan2notes.klang.io/
- **API pricing:**
  - Free: 50 requests/month, max 15s audio
  - Startup: $99/month (500 requests)
  - Business: $499/month (3,000 requests)
  - Enterprise: custom
- **Note:** Must fill out API request form to get credentials; full docs not public

### pdftomusicxml.com
- **No API whatsoever**
- **Engine:** DeepScore (proprietary)
- **Claims:** 99% accuracy on born-digital PDFs
- **Free tier:** 2 pages free per document, 1 free conversion/day
- **Paid:** Pay-as-you-go (pricing not publicly listed)
- **Formats:** MusicXML, MIDI, MuseScore (.mscz)

### ScanScore
- **No API; desktop application only**
- **Pricing (annual license, no auto-renewal):**
  - Melody: ~$9/year (1 staff)
  - Ensemble: ~$99/year (up to 4 staves)
  - Professional: ~$179/year (unlimited staves)
- **Platforms:** Windows 8+, macOS 10.12+
- 30-day money-back guarantee

### Newzik
- **No API; web/iPad app only**
- **Engine:** Maestria AI
- **Pricing:**
  - Essentials: EUR 29.99 one-time (10 pages, no MusicXML export)
  - Premium: EUR 9.99/month or EUR 49.99/year (unlimited conversions + export)
  - Lifetime: EUR 199 one-time
- **Key limitation:** MusicXML export requires Premium

### ACE Studio (acestudio.ai)
- **No API**
- **Free:** 10 conversions/day, first 5 pages, max 2 staves
- **Paid:** ACE Studio subscription for unlimited
- **Run by:** ACCIDENTAL

## Pricing Comparison (for testing a single viola part)

| Service            | Cost for first test       | Ongoing cost           |
|--------------------|---------------------------|------------------------|
| pdftomusicxml.com  | Free (2 pages)            | Pay-as-you-go          |
| Scan2Notes         | Free (limited)            | N/A (web UI)           |
| ACE Studio         | Free (10/day, 5 pages)    | Subscription           |
| Soundslice         | $5/month (Plus plan)      | $5/month               |
| Flat.io            | Free tier available       | $7.99/month for PDF    |
| ScanScore          | $9/year (Melody)          | $9/year                |
| Newzik             | EUR 9.99/month (Premium)  | EUR 9.99/month         |

## Recommendations

1. **For quick free testing:** pdftomusicxml.com or ACE Studio -- no signup needed,
   free tier covers our test file.

2. **For best quality evaluation:** Test all web-UI services manually using the
   guide in `manual-test-guide.md`, then compare MusicXML outputs.

3. **For automation pipeline:** Soundslice or Flat.io offer the best hybrid
   approach (manual PDF upload, API-driven export). Soundslice has the more
   mature API and Python library.

4. **For batch processing:** None of these services support fully automated
   PDF-to-MusicXML via API. Consider local OMR tools (Audiveris, oemer, HOMR)
   for batch/CI pipelines instead.

## Test Results

_No automated test results yet. Manual test results should be added below
as each service is tested with `test-scores/mozart-eine-kleine-viola.pdf`._

| Service            | Tested? | Accuracy Notes | Output File |
|--------------------|---------|----------------|-------------|
| pdftomusicxml.com  | [ ]     |                |             |
| Soundslice         | [ ]     |                |             |
| Flat.io            | [ ]     |                |             |
| Scan2Notes         | [ ]     |                |             |
| ScanScore          | [ ]     |                |             |
| Newzik             | [ ]     |                |             |
| ACE Studio         | [ ]     |                |             |
