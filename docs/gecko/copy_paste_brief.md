Add copy, cut and paste of map areas to gecko (this repo, branch `hoglord-edits`).

Read CLAUDE.md first and follow it. Do all of the work yourself; do not hand any of it to sub-agents. Make a new branch `copy-paste` from `hoglord-edits`, commit there and push it to this repo (HogLord69/gecko-private) only. Never push to the public fork HogLord69/gecko and never open a pull request to JanSimek/gecko.

## What the owner wants

Select part of a map, copy it, and paste it somewhere else, on the same map, another elevation, or another open map.

**Copy (Ctrl+C, Edit > Copy, right-click > Copy)**
- Takes the current selection on the current elevation: the selected floor tiles, roof tiles and objects (whatever the current selection mode picked up). Hex selections (the HEXES mode used for wall blockers) are ignored.
- Objects are deep-copied with every field kept (`MapObject::cloneDeep`, inventory included): container contents, exit grid destination, stair/ladder destination (`elevhex`, `map`), door state, light, critter fields, amount, flags, direction, art.
- Floor or roof squares whose id is `Map::EMPTY_TILE` are left out, so a paste never punches holes in the ground under it.
- The anchor is the centre of the copied area's bounds, snapped so its column and row are even (tile-aligned). The paste preview then sits centred under the cursor.
- The clipboard is in memory and shared by every open map (keep it at MainWindow level or another app-wide owner, not per EditorWidget). A new copy replaces it. The status bar says what was copied ("Copied 42 objects, 120 floor, 30 roof tiles").

**Cut (Ctrl+X, Edit > Cut, right-click > Cut)**
- Copy, then delete the selected objects through the existing `deleteSelectedObjects` path (one undo step). Tiles are left as they are, matching what Delete does today.

**Paste (Ctrl+V, Edit > Paste, right-click > Paste)**
- Enters a paste mode that works like the existing stamp mode (`EditorWidget::beginStampPattern`, `updateStampPreview`, `stampPatternAt`): a see-through ghost of the floor, roof and objects follows the cursor. Left-click drops a copy and stays in paste mode so the owner can keep dropping; right-click or Esc leaves it. Status bar text like the stamp mode's.
- Placement moves in 2-hex steps so tiles stay locked to the objects, using the same parity snapping as `PatternStamper::plan`.
- Each drop is ONE undo entry covering its objects, tiles and any script records (build a `pattern::FillPlan` with full cloned MapObjects and TileChanges and commit it the way `PlacementBatch::replay` does, or an equivalent single batch).
- Every drop makes fresh clones from the clipboard, so repeated drops never share objects. Each clone gets its position translated, `elevation` set to the current elevation, and a new unique object id (`unknown0`, see `ScriptEditService::allocateObjectId`). Treat `critter_index` the way existing object placement does.
- A copied object that had a script gets its own new script record running the same script program in the same section (what `ScriptEditService::attachScript` does: new SID, new OID). The record must be inside the same undo entry, so Ctrl+Z removes the object and its script together. Spatial scripts are not copied.
- Exit grid and stair/ladder destinations point to other places, so they are kept exactly, not translated.
- Objects or tiles that would land off the map are dropped and counted in the status message (as stamps do).

**Menus and keys**
- Edit menu: Cut, Copy, Paste with Ctrl+X / Ctrl+C / Ctrl+V.
- The right-click menu (`EditorWidget::showObjectContextMenu`, currently the draw-order commands) gets Cut and Copy when something is selected and Paste when the clipboard has something. It currently returns early when no objects are selected; it must still open to offer Paste, and Copy must also work for a tiles-only selection.
- The keys must work while the map viewport has focus. The draw-order keys (Home/PgUp/PgDown/End) go through `src/ui/input/InputHandler` rather than window shortcuts; follow the same route if QAction shortcuts don't reach the viewport. Ctrl+C in text fields and the log panel must keep doing a normal text copy.

## Tests

Put the pure logic in a helper with no UI dependencies (for example `src/editor/helper/MapClipboard.{h,cpp}`, like `ObjectOrder` and `BlackEdge`) and cover it in `tests/general/test_map_clipboard.cpp`, registered in `tests/CMakeLists.txt`:
- capture: offsets from the anchor, anchor snapped to even column/row, empty tiles skipped, objects deep-copied (inventory included);
- placement: translation with parity snapping, exit grid and stair data unchanged, new object ids unique across the map and across repeated drops, one script record per scripted copy with the same program, off-grid entries dropped and counted.

## Build and finish

Try to build and run `general_tests` (and `qt_tests` if they build) with the commands in CLAUDE.md. If this machine can't build gecko (missing Qt6/SFML or similar), say so plainly. The owner's local Claude builds on Windows. Format with `./format.sh` style (WebKit) and match the comment density and naming of the code around each change. Don't change file formats, stamps, or unrelated behaviour.

End with a short report: what you built, files changed, test results, and anything you weren't sure about.
