# Live-readiness timeline assessment — 2026-10-20

Scope: read-only assessment of the execution plan and checked-in data through 11:59 UTC, not production-host verification or authorization for real orders. No runtime settings changed.

## Checks and status

Ran check_data.py (0 fail / 8 warn), handoff_check.py (FRESH, 2 advisory drift), check_structural_stop.py (geometry PASS), check_gap_rides.py (registered closure count 2/2), pressure_report.py --root ., and xm_quote_report.py.

Latest ledger: 645 closed paper trades, 128W/277L/238BE/2TIME, no open trade. Gross cumulative P&L -$342.24; net -$600.24 at the registered $0.40 round trip. This is a historical mixed-strategy ledger, not an independent test of one unchanged strategy. Structural-stop era is now n=148; this does not reopen the expired n=150 judgement arm.

The plan's judgement/reconciliation work is complete; the next runtime action remains blocked. The closure-gap revert trigger fired, requiring the owner-defined guard first and then the prescribed structural-stop revert. The owner previously left the guard undefined; this assessment does not re-ask or invent its policy. Pressure-guided holding is research only, not a prerequisite for going live.

Quote collection is at 6/14 complete UTC days and 1/2 weekends. Assuming uninterrupted collection, the target could be reached around October 28–29. First-look median spread is $0.55 versus the registered $0.40 round trip; do not adopt a new cost assumption before the review. Slippage, commissions and any applicable swap need separate treatment. Broker DST needs observed evidence in the October 25–November 1 discriminating window.

## Additional execution work before any live pilot

- engine.py hardcodes ORDER_FILLING_FOK while the captured broker spec reports IOC filling support. Resolve and demo-test the compatibility; do not infer successful execution from the existence of order_send.
- run_live does not call check_position, so paper breakeven/time management is not demonstrated in the live loop. Implement/verify intended live equivalents and their outage limitations.
- run_live requests the current M1 bar (position 0), unlike the closed-bar sidecar path. Validate closed-bar timing and deduplication parity.
- Demonstrate broker-position/deal reconciliation, restart recovery, accurate realized-loss gates, rejection handling, sizing against contract limits, disconnect safety, monitoring and a kill switch on a demo account using the intended execution path. This is a readiness checklist, not a claim that every item has been exhaustively audited or is absent.
- Verify the running executable and services on the production host; repository checks cannot establish deployed health.

## Conditional estimates, not deadlines

- Next 1–2 weeks: cost/DST evidence can mature in parallel. The guard/revert cannot proceed without the previously deferred owner decision.
- After that decision, allow roughly 2–4 engineering weeks for guard/revert review, live-path hardening and demo integration, subject to findings and host access. This is an estimate, not an approved implementation plan.
- December 2026–February 2027: earliest useful next strategy reassessment under the existing 2–4 month research horizon, assuming a stable, pre-registered forward window. Require positive expectancy after realistic costs, uncertainty assessment, acceptable drawdown and multiple regimes; 100 trades alone is not proof.
- April–October 2027: conservative planning window for a separate live-readiness review, consistent with the existing 6–12 month horizon. A tightly capped pilot is possible only if evidence and operational gates pass and the owner explicitly approves. Failed evidence or strategy changes can extend this indefinitely.

No date can be promised for profitable live trading. Time elapsed, a higher win rate or a larger mixed-era trade count cannot substitute for evidence of an edge.
