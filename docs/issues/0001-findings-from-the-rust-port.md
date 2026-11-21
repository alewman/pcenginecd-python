# 0001: what the Rust port found in this add-on

Raised 2026-11-12 by the pcenginecd-rust build (its `scripts/reference_notes.py` shows the first on
this add-on). pcenginecd-rust reproduced each item (52 lockstep cases identical, six real discs with
their audio), so the two agreed; the question was whether the behaviour was right.

**Status: settled 2026-11-13** (code in f8649b5). Items 1-4 and most of 5 were fixed, plus one more bug
found while testing item 5 (the RST line). One switch was added (C22). Tiers as in the base board's
[validation.md](https://github.com/alewman/pcengine-python/blob/main/docs/validation.md). The base
board pin (`bc9b976`) is unchanged. Directed tests: `tests/test_issue0001.py` (each fails on e933469),
plus the strengthened Arcade Card wrap test. 105 tests: 103 quick ones on CPython and PyPy, and the
2 slow ones on PyPy.

## Decisions

1. **The drive's clock stood still between events: fixed (a plain bug against the model's own
   rule).** The rule is in `scsi.py`: "the unit calls `run_to(mclk)` before every register access and
   the bus then runs its own timers up to that instant". So a timer counts from the write that starts
   it, and the U8 timings (`SEL_TO_COMMAND_PHASE` and the others) are durations from that write.
   `CdUnit.catch_up` skipped the run while an event waited in the future, and `read`/`write` called
   only `catch_up`. So `ScsiBus.now` (and the CD-DA player's `_now`, which feeds the `$1805`
   latch and READ SUBQ's position) stayed at the last event. Reproduced with the Rust port's script:
   SEL to the command phase took 75,000 master clocks on an idle drive and **0** with CD audio
   pending. Fix: `CdUnit._run_now(mclk)` (it runs `_run(mclk)` unconditionally and sets `mclk`) is
   called before every `$1800-$18FF` access. `catch_up` keeps its early-out, because the board calls
   it at every advance. No timing value changed. After the fix the script gives 75,000 in both cases.
   Tests: `test_sel_to_the_command_phase_takes_the_same_time_with_cd_audio_playing`,
   `test_a_register_access_brings_the_drive_clock_to_its_own_time`.
2. **The unit's own `catch_up` in `read`/`write` did nothing on a board: fixed with item 1.** The
   register path now calls `_run_now`, which does move the clock. CD RAM and BRAM accesses call
   nothing: they are memory and have no clock. Their old call did nothing on a board, so the boards'
   behaviour is unchanged. Off a board (the test host), memory accesses no longer run the drive. The
   Arcade Card path never had a clock. Test: `test_memory_accesses_do_not_run_the_drive`.
3. **A power-on reset kept the unit's timers: fixed (the stated rule: the power-on reset "clears the
   bus" and re-zeroes the unit).** `CdUnit.reset(POWER_ON)` now sets `_dma_at = None` and
   `_latch_guard_until = 0`, and recomputes `_next_event = _soonest()`. `Adpcm.power_on(at=0)` takes
   the reset's time (the unit passes `self.mclk`) and files the idle output there, not at 0 behind
   later events. Test: `test_power_on_reset_clears_the_units_timers_and_files_the_adpcm_idle_at_the_reset`
   (a `$1805` write inside the old guard window used to be ignored after the reset).
4. **`ScsiBus.reset` dropped its IRQ levels without telling the unit: fixed.** It zeroed
   `_irq_levels` before `_update_irq()`, which then saw no change. Now `_irq_levels` is set once in
   `__init__`, and `reset` lets `_update_irq()` report each level that drops, through the callback.
   On a board nothing changes, because both callers cleared the bits themselves and still do
   (`$1804` also clears the subchannel bit). Test: `test_a_bus_reset_tells_the_unit_that_req_dropped`.
5. Small things:
   - `bram=` longer than 2 KiB grew the RAM: **fixed**, now `ValueError` (the RAM is 2 KiB, pcetech 8).
   - A cue `TRACK` before any `FILE` attached to the last file: **fixed**, now `ValueError`. So does an
     `INDEX` before any `TRACK`, which used to be an `IndexError`.
   - `to_bcd(160+)` does not fit a byte: **left**, because it is unreachable. Track numbers stop at 99,
     and MSF minutes stay under 100 on any real disc. The docstring now states the 0-99 domain.
     Raising there would stop a run over a malformed disc, which is worse than a wrong byte.
   - `ASC_INVALID_COMMAND` was unused: **switch** (C22 in m7-record.md). The emulators disagree, and no
     source above tier 5 speaks for this drive. Mesen2 and Geargrafx answer an unknown opcode with
     Good. Mednafen answers CHECK CONDITION with ILLEGAL REQUEST / INVALID COMMAND, which is SCSI-2's
     rule for an unsupported opcode. `ScsiBus.UNKNOWN_COMMAND_CHECK_CONDITION = False` keeps Good. True
     gives Mednafen's sense data (it still answers at the first byte). Both are tested:
     `test_an_unknown_command_answers_good_or_check_condition_with_the_switch`.
   - The 24-bit Arcade Card base-wrap test would pass with a 16-bit wrap: **fixed**. It now also checks
     that `$12FFFF + 2` gives `$130001`. Checked by mutation: with `& 0xFFFF` the old test passed and
     the new one fails.
   - The reset-register test did not test the blocking it named: **fixed, and it found a bug.** While
     writing `test_reset_register_held_keeps_the_drive_irqs_off`, it turned out that
     `ScsiBus.reset()` cleared `rst` itself. So the drive was reset only at the rising edge of
     `$1804` bit 1. While the bit was held, a SEL started a command, the drive answered, and only
     `CdUnit._bus_irq`'s guard kept the IRQ bits off. That contradicts the model's own words
     ("`$1804` bit 1: the SCSI RST line", "while the drive is held in reset"): a reset cannot release
     a line the CPU drives. Mesen2 (tier 5) keeps the line too. Fixed: `rst` is initialised in
     `ScsiBus.__init__` and kept by `reset()`, so the drive stays reset while the bit is held.
     `CdUnit.reset(POWER_ON)` sets `bus.rst = False` (the reset register goes to 0 there). The old
     test was renamed `test_reset_register_clears_drive_irq_enables_and_the_drive_works_after_release`.
   - The unit's docstring said the board calls `catch_up` "every cycle": now "at every advance".

## The discs, before and after (2026-11-13)

One disc extracted at a time with `scripts/scratch.py` into the scratchpad and removed after. The
before run (e933469's `src`, exported to a scratch directory) and the after run (f8649b5) ran side by
side on niced PyPy (`PYPY_GC_NURSERY=1M`). Settings: `syscard3.pce` read in place, 3,000 frames,
RUN held 20 frames at 450, `--png-at 1000,2000,3000`, `--adpcm-writes 40`, and `--arcade` for the
three Arcade Card discs. Load average 7-29. Compared: `summary.json`, `commands.txt` (text and
master-clock time), and the 9-bit rows of the three pictures.

| Disc | Drive commands before / after | ADPCM samples before / after | Pictures 1000/2000/3000 | What moved |
| --- | --- | --- | --- | --- |
| Ryuuko no Ken (Arcade) | 12 / 12 | 47,410 / 47,410 (6 ends) | identical | nothing: same commands at the same clocks, same Arcade Card counts, PC `$7B12` |
| Mad Stalker (Arcade) | **455 / 426** | 0 / 0 | identical | During the CD-audio wait (frames 958-1253) the game polls READ SUBQ (`DD`). Each poll now takes its full SEL-to-command time, so 394 polls fit instead of 423. Every other command (TUR, TOC, the 22 READs, `D8`/`D9`) lands on the same frame, and the Arcade Card counts and PC `$6078` are the same |
| Ginga Fukei Densetsu Sapphire (Arcade) | 19 / 19 | 0 / 0 | identical | nothing |
| Pyramid Plunder | 12 / 12 | 114,688 / 114,688 (2 ends) | identical | nothing |
| The Addams Family | 18 / 18 | 533,755 / 533,755 (1 end) | identical | The 8 READs issued while ADPCM plays (from frame 1249) are logged 1,194-1,227 master clocks later. That is less than one 16 kHz sample period, the most the old clock could lag behind while the sample clock was pending |
| Insanity | 10 / 10 | 0 / 0 | identical | nothing (the BIOS leaves the bus BUSY in its audio commands, as before) |

**Geargrafx** (`scripts/beetle_press.py --core
/data/emu/pcengine-python/reference/src/geargrafx/platforms/libretro/geargrafx_libretro.so`, the CHD
read in place, the same press) was rerun on **Mad Stalker** at frames 1000, 2000 and 3000. It shows
the same scenes as ours: the mechs and "NOW LOADING 02" at 2000, the car/figure cutscene at 3000
(compared by eye, as in m9). It cannot count READ SUBQ polls. The change moves the add-on **closer**
to the detectors' model, judged by timing model rather than pictures, since the pictures did not
move. Geargrafx and Mesen2 keep their drive clock running every cycle, so their SEL delay counts from
the write. Before the fix, ours counted from the last event while CD audio played. Addams moved by
less than a sample period, and its pictures and sample count did not change, so Geargrafx was not
rerun there; m8's comparison stands. No disc's picture, ADPCM count or command sequence moved.

**Not run:** the base board's picture gate (no VDC/VCE code touched), and the audio against
Geargrafx (no `--wav` render, and the ADPCM sample counts are identical).

## What a lockstep port must carry

- `CdUnit.read` / `CdUnit.write`: the Arcade Card pages, CD RAM and BRAM return without any
  catch-up. The register page calls the new `CdUnit._run_now(mclk)` first (`_run(mclk)`, then
  `self.mclk = mclk`). `write` no longer runs `_dma_arm()` / `_next_event = _soonest()` after a CD RAM
  or BRAM write; it still does after a register write.
- `CdUnit.reset(POWER_ON)`: `bus.rst = False` before `bus.reset()`; `adpcm.power_on(self.mclk)`;
  then `_latch_guard_until = 0`, `_dma_at = None`, `_next_event = _soonest()` (before
  `_update_irq()`).
- `Adpcm.power_on(at: int = 0)`: `_output(at, 0)` instead of `_output(0, 0)`.
- `ScsiBus.__init__`: `_irq_levels = (False, False)` and `rst = False` before `reset()`.
  `ScsiBus.reset()`: no longer assigns `rst` or `_irq_levels`; it ends with `_update_irq()`, which
  now reports each level that drops (0x40 and/or 0x20, level False) through the callback.
- New switch `ScsiBus.UNKNOWN_COMMAND_CHECK_CONDITION = False`. When True, an unknown opcode does
  `_fail(SENSE_ILLEGAL_REQUEST, ASC_INVALID_COMMAND)` (sense `$05`/`$20`, CHECK CONDITION) instead of
  `status_message(GOOD)`.
- `CdUnit.__init__`: `ValueError` if `len(bram) > 2048`. `Disc.from_cue`: `ValueError` for a TRACK
  before any FILE or an INDEX before any TRACK.
- No new state fields; the defaults of every timing attribute are unchanged.
