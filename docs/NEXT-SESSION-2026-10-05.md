# Next Session Worklist — 2026-10-05

## Active Focus: Ratchet-Off Forward Shadow A/B

1. **Shadow Harness (`tools/ratchet_shadow.py`):**
   - Implemented stateful shadow execution harness reusing engine & filter rules.
   - Calibration gate verified against the 0.75R master book and max-hold era.
   - Forward log and state tracking established starting at T0.

2. **Monitoring & Ops:**
   - Allow shadow harness to accumulate trades in parallel with live forward testing.
   - Track live vs shadow metrics across 150 trades / 21 days window.
   - Monitor host-side MT5 stability per `docs/REVIEW-2026-09-29-feed-outage.md` §7.

3. **Frozen Items (Do not touch):**
   - Live engine parameters remain untouched (`BE_TRIGGER_R = 0.75`, `MAX_HOLD_MINUTES = 240`).
   - `H-side-awareness` remains DROPPED.
   - Session-band candidate remains unregistered until ratchet-off trial concludes.
