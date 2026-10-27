# fallout2-modding-tools

Private collection of the custom tools used to mod Fallout 2 and to build maps
for it, including the Gecko-based map workflow. Extracted from the `tools/`
folder of the FOC mod project (`HogLord69/FOCMod`).

This repo is **code only**. No game data, no art, no third-party binaries.

## Layout

The scripts expect the FOC project layout. Most of them find the project root
as the parent of `tools/` (and some hardcode `F:\FOCMod`), so the folder
structure here is kept the same as in the mod project: drop `tools/` into a
project root and run from there.

```
tools/
  foclib/         shared readers: DAT1/DAT2, MAP/PRO/FRM formats, virtual file system
  selftest/       probes and tests for the format readers and map writer
  designs/        per-site layout definitions (midland, webb, rwfac1-3)
  gecko_browse/   launchers that swap Gecko between game installs and back
  *.py            everything else, grouped below
docs/
  MAP_LAYOUT_GUIDE.md, MAP_STORYTELLING_GUIDE.md, SITE_PLANS.md, TOOLCHAIN.md
  gecko/          notes on custom Gecko work (copy/paste brief)
```

## Tool groups (`tools/`)

Each script starts with a docstring that says what it does and how to run it.

| Group | Scripts |
|---|---|
| Map writing and compiling | `mapbuild.py`, `gridmap.py`, `compose_map.py`, `mapedit.py` (+ `mapedit.html`), `make_blank.py`, `make_slice.py` |
| Map editing and cleanup | `map_trim.py`, `map_crop.py`, `map_edges.py`, `map_exits_to_edge.py`, `map_fixup.py`, `map_finalize.py`, `map_link.py`, `shift_map.py`, `carve_map.py`, `restore_map.py`, `sync_maps.py`, `strip_blockers.py` |
| Map surveys and checks | `map_survey*.py`, `edge_survey.py`, `exit_survey.py`, `stairs_survey.py`, `story_survey.py`, `check_links.py`, `compare_map.py`, `validate.py` |
| Stamps and building kits | `stamps.py`, `port_stamp.py`, `building_stamps.py`, `area_stamps.py`, `sitekit.py`, `wallkit.py`, `wallsets.py`, `tilewfc.py`, `groundkit.py`, `corpus.py` |
| Site builds | `build_redwell.py`, `build_clcourt.py`, `build_rwfac1-3.py`, `rework_clcourt.py`, `site_plan.py` |
| Porting assets between games | `port.py`, `port_bulk.py`, `port_gun.py`, `port_head.py`, `port_item.py`, `port_look.py` |
| Art and sprites | `recolor_*.py`, `scale_*.py`, `repack_art.py`, `frm_sheet.py`, `pc_*.py`, `sprite_*.py`, `restyle_*.py` |
| Scripts, dialogue and protos | `dlg.py`, `bind_*.py`, `npc_protos.py`, `creature_protos.py`, `colonist_protos.py`, `gen_ids.py`, `ids.py` |
| World map and engine registration | `worldmap.py`, `paint_worldmap.py`, `render_worldmap.py` |
| Build and deploy | `build.py`, `deploy.py`, `make-base.ps1`, `install-sfall.py`, `boot_test.ps1` |
| Gecko | `build_gecko_browsers.py`, `gecko_browse/` |

## Not in this repo

- The Gecko editor itself lives in `HogLord69/gecko-private`.
- The compiler and DAT tools (`sslc`, `int2ssl`, `dat2`, `dat3`), the
  fallout2-ce build and w64devkit are third-party downloads. `docs/TOOLCHAIN.md`
  lists versions, sources and SHA-256 hashes.
- Anything generated or machine-specific: the TC browser launchers that
  `build_gecko_browsers.py` writes, extracted game data, scratch previews.
- The Gemini key used by `restyle_sheets.py` is read from a `.gemini_key` file
  that is git-ignored. Never commit it.
