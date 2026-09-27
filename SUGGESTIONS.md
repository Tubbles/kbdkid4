# Suggestions

Ideas noticed during work, not yet asked for. Strike or promote as you see fit.

- **The nice!nano's board edge clears the tray ledge by only 0.03 mm.** With the nano under the board (`U1`, flipped), its PCB reaches to 0.63 mm inside the board's north edge, while the 1.0 mm ledge minus the 0.4 mm gap reaches 0.6 mm under the board edge (`scripts/export_tray.py`, `DEFAULT_LEDGE_WIDTH_MM`, `DEFAULT_GAP_MM`). The USB window removes the ledge over its 14 mm width, but the nano is 17.8 mm wide, so 2 mm at each end still face the ledge at 3.85 to 5.25 mm above the floor. Options: a narrower ledge (`ledge_width=0.9` or less), no ledge along that stretch, or the nano 0.3 mm further south on the board. Measured on LibrePCB's populated STEP export on 2026-09-27; not changed because it is a design choice between the ledge and the nano's position.
