# New office — layout visuals

Generators for the Alphalete new-office drawings (traced from O'Brien sheet A2.01).

| script | builds | output |
|---|---|---|
| `plan2d.py` | numbered 2D key map | `keymap.svg` |
| `isogen.py` | 3D isometric overview of the whole floor | `office.svg` |
| `studio.py` | interactive room-by-room studio (embeds both of the above) | `studio.html` |

Run in that order — `studio.py` reads the two SVGs. Then serve:

    python3 -m http.server 8787      # open studio.html

Rendered copies land in `output/`, which is gitignored — re-run the scripts to regenerate.

## Notes for whoever picks this up

- **Painter's algorithm.** Everything sorts by centroid depth. Big flat things (floors,
  the tall back walls, a long conference table) therefore paint over anything whose
  centroid is behind theirs, which silently erases furniture. Floors and back walls carry
  large negative depth biases so they always paint first; the conference chairs pin their
  depth either side of the table. Add a big object and re-check what vanishes.
- **`box()` is axis-aligned.** Use `rbox()` for anything set at an angle to the room.
- **Foliage** must use `leafy()` — stacked boxes only ever read as blocks, never leaves.
- **The camera is fixed at the south-east.** A chair facing north or west shows only its
  back; a wall on the near side hides the room behind it unless drawn translucent. Rooms
  with glass on two opposite walls (Twaddle's, Megan's) can't show both plus a solid wall.
