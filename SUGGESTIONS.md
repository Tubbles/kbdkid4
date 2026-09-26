# Suggestions

Ideas noticed during work, not yet asked for. Strike or promote as you see fit.

- **Check the USB notch depth against the nice!nano's real mounting height.** `scripts/export_tray.py` keeps `USB_NOTCH_DEPTH_MM = 3.2` from the old layout, which puts the notch floor at 8.7 mm above the tray floor, 0.9 mm below the board's top face. With the connector now on the board edge the plug overmold passes through the wall rather than over it, so whether 3.2 mm is enough depends on how high the nano sits (soldered flush versus on headers or sockets), which the STEP no longer shows since it carries only the bare board. Noticed while relocating the notch (2026-09-26); left as is because the stack height is not in the sources.
- **The CI outputs job reports 401 non-approved DRC messages on Board 1.1** (clearance drill to drill under 0.35 mm, copper to hole under 0.225 mm). `checks-fatal: false` keeps them from failing the build. Either approve them in LibrePCB or relax the DRC settings in `boards/board_1.1/board.lp` if they are accepted, so a real regression can be told apart from the noise. Noticed in the run log for "finished v1.1" (86d679b).
