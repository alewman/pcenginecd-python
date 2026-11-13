# 0001: what the Rust port found in this add-on (not yet decided)

Raised 2026-11-12 by the pcenginecd-rust build (its `scripts/reference_notes.py` shows the first on
this add-on). Status: **open; nothing changed.** pcenginecd-rust reproduces each (52 lockstep cases
identical, six real discs with their audio), so the two agree; the question is whether this is right.

1. **The drive's clock stands still between events.** `CdUnit.catch_up` moves `ScsiBus.now` only
   when an event is due or none is pending; while one waits in the future, timers started by a
   register write count from the last time the bus ran. Shown: SEL to the command phase takes
   75,000 master clocks on an idle drive and **0** when CD audio has played for a second (with
   ADPCM playing the clock is at most one sample period old). The fix would be to run the bus to
   `mclk` in every register access. This is the one about behaviour: it changes drive timing in
   exactly the situation games are in (audio playing).
2. The unit's own `catch_up` calls in `read` and `write` do nothing on a board (the board has just
   caught the unit up to the same clock).
3. A power-on reset keeps `_dma_at`, `_next_event` and `_latch_guard_until`; `Adpcm.power_on`
   files its idle event at time 0, behind later ones.
4. `ScsiBus.reset` drops its IRQ levels without telling the unit; both callers clear the bits.
5. Small: `bram=` longer than 2 KiB grows the RAM; a `TRACK` before any `FILE` attaches to the last
   file; `to_bcd(160+)` does not fit a byte; `ASC_INVALID_COMMAND` is unused; the 24-bit Arcade
   Card base-wrap test would pass with a 16-bit wrap; the reset-register test does not test the
   blocking it names.

Any change here is repinned and transcribed into pcenginecd-rust.
