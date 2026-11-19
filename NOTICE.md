<!-- SPDX-License-Identifier: MIT -->
# Third-party notices

pcenginecd-python is MIT licensed (LICENSE). It contains no code from the GPL emulators its
documents cite; see the base board's `docs/provenance.md` for the rule and the check.

## MAME (BSD-3-Clause)

MAME's PC Engine CD files are BSD-3-Clause (the first line of each file, checked). They were read
as a permissive emulator's description of the hardware; **no code was transcribed** from them.
Four sets of facts in this add-on are MAME's, and their notice is kept here:

- `src/pcenginecd_python/syscard.py`: the Super System Card's id-register values
  (`$1`=AA, `$2`=55, `$3`=00, `$5`/`$6` by region, `$7`=03) as MAME's `src/devices/bus/pce/pce_scdsys.cpp` returns them.
  Copyright Fabio Priuli, Wilbert Pol.
- `src/pcenginecd_python/adpcm.py`: the MSM5205 step formula (the signal change per index and
  magnitude), as modelled by MAME's `src/devices/sound/msm5205.cpp`. Copyright Aaron Giles.
- `src/pcenginecd_python/scsi.py`: the command-length and answer-length facts that MAME's
  `src/mame/nec/pce_cd.cpp` lists (the drive's command table, READ TOC answer lengths, the
  auto-ACK pulse), cited where used. Copyright Wilbert Pol, Angelo Salese.
- `src/pcenginecd_python/arcade.py`: the Arcade Card's ports and registers as MAME's
  `src/devices/bus/pce/pce_acard.cpp` describes them (with ares, ISC, as the second readable
  source). Copyright Fabio Priuli, Angelo Salese.

The licence of those files:

```
Copyright (c) the copyright holders named above (MAME, https://www.mamedev.org)

Redistribution and use in source and binary forms, with or without modification, are permitted
provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this list of
   conditions and the following disclaimer.
2. Redistributions in binary form must reproduce the above copyright notice, this list of
   conditions and the following disclaimer in the documentation and/or other materials provided
   with the distribution.
3. Neither the name of the copyright holder nor the names of its contributors may be used to
   endorse or promote products derived from this software without specific prior written
   permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR
IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND
FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER
IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT
OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

## Dave Shadoff's PCECD_seek (MIT)

`src/pcenginecd_python/seek.py` (the zone table and the shape of the seek-time model) is derived from
Dave Shadoff's `seektime.c` (https://github.com/pce-devel/PCECD_seek), which is MIT licensed:

```
MIT License

Copyright (c) 2019 David Shadoff

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
