"""Pure DP 45 (manual run) byte-packing for the Inkbird IIC-400-WIFI. No I/O,
no Home Assistant imports - ported from the standalone scripts/iic400.py so
it can be unit-checked in isolation.

DP 45 FORMAT (manual run, 18 bytes, base64):
  [0]=1 start/reset, [1]=1 specific zones,
  [2-9] run time per zone (2 bytes BE, minutes, z1..z4),
  [10-17] single-use time, same layout. Stop: [0]=1, rest zero - this stops
  ALL manual zones at once, not a single zone (hardware behavior).

  Hardware-confirmed 2026-07-12: sending this exact layout (zone 1, 1
  minute) flipped DP 101 (operation mode) to "Manual" on its own and set
  DP 107's zone-1 bit, i.e. the zone actually ran. An alternate layout
  hypothesized from a differently-captured trace (flag at [1] only, no
  duplicated [10-17] block) was tested back-to-back on the same device and
  did *not* start the zone or flip the mode - rejected. The layout
  implemented below is the one to use; no open discrepancy remains.
"""
import base64


def build_manual(minutes_per_zone):
    """Build the 18-byte DP 45 payload (base64-encoded) for a manual run.

    minutes_per_zone: list of up to 4 ints (minutes for zone 1..4). Use 0 for
    zones that should not (re)start - the device only auto-stops zones with a
    nonzero duration once it elapses.
    """
    b = bytearray(18)
    b[0] = 1
    b[1] = 1
    for i, minutes in enumerate(minutes_per_zone[:4]):
        m = max(0, int(minutes))
        b[2 + i * 2] = (m >> 8) & 0xFF
        b[3 + i * 2] = m & 0xFF
        b[10 + i * 2] = (m >> 8) & 0xFF
        b[11 + i * 2] = m & 0xFF
    return base64.b64encode(bytes(b)).decode()


def build_stop():
    """Build the DP 45 stop-all payload (base64). Stops every manual zone at
    once - there is no verified hardware behavior for stopping a single zone
    while others keep running. Do not build a per-zone stop without testing
    against real hardware first.
    """
    b = bytearray(18)
    b[0] = 1
    return base64.b64encode(bytes(b)).decode()
