# Site Plans

Every FOC map is planned on paper before anything is placed: a to-scale drawing in the game's own projection, built from a real place and from how the original games and the total conversions lay out the same kind of place. The map is then built from the plan's data, and checked against it.

## How a plan is made

1. **The real site.** `tools/real_site.py` fetches the real place's layout from OpenStreetMap (runways, streets, building footprints) and draws it to scale, north up. Where there is nothing usable on the map (a Cold War relay site), the plan follows documented examples instead.
2. **The game references.** Every comparable map in Fallout 1, Fallout 2, Sonora, Nevada, Resurrection, Yesterday and Story of the Jackal is rendered and measured by `tools/plan_refs.py`, using `tools/map_survey.py`'s numbers: play area, building count and size, the gaps between buildings, the road share, and clutter near buildings and on open ground.
3. **The plan.** `tools/site_plan.py` reads `mod/maps_src/plans/<name>.plan.json` and draws `docs/plans/<name>.png`:
   - every building's true footprint, from its stamp, with its doors in red and new doorways in orange
   - roads, zones, features, exits, the start, and the walking routes the player is meant to take
   - when the map starts from an existing level, that level drawn underneath, with its real rooms found, numbered and named
   - checks for overlaps, gaps under the minimum, buildings off the play area or away from a road, the start-to-exit distance, and any Olympus asset
4. **The stories.** Every plan names its kind of place, its materials and its vignettes, the small scenes that tell what happened there, by the rules in [MAP_STORYTELLING_GUIDE.md](MAP_STORYTELLING_GUIDE.md). They are drawn as numbered markers.
5. **The build.** The map is composed from the plan's own coordinates, then rendered and compared against the drawing.

Olympus 2207 assets are the owner's alone. `site_plan.py` flags them, and `compose_map.py` refuses to write a map that contains any.

## The plans

| Map | Starts from | Real reference | Drawings |
|---|---|---|---|
| Webb Airbase | stamps laid out in bands: runway, apron, Front Avenue and the hangar line, cantonment, safety zone | Webb AFB / Big Spring airfield ([OSM](https://www.openstreetmap.org/#map=15/32.214/-101.522)) | [plan](plans/webb.png), [references](plans/webb_refs.png) |
| Midland Ruins | stamps at the Wall Street and Main Street crossing | downtown Midland: Wall St, Main St, Centennial Plaza, the bank and office towers ([OSM](https://www.openstreetmap.org/#map=17/31.997/-102.077)) | [plan](plans/midland.png), [references](plans/midland_refs.png) |
| Waterworks (RWFAC1) | built from RWFAC1_DESIGN.md by tools/build_rwfac1.py: Fallout 2's industrial panel walls (dv) and Gecko's hatches, the brn checker framed in vtgst, the rock field round it | a filter plant's operating gallery with the beds down its side and the chlorine sealed away from it; laid out as a dungeon like Gecko's tunnels | build/rwfac1/ renders |
| Military annex (RWFAC2) | built by tools/build_rwfac2.py: Fallout 2's military base walls (mmb) and vault doors, the steel plate framed in vtgsl, hazard stripes along the back walls, stairs between the levels as Fallout 2 joins floors, the galleries in the brown cave set, the rock field round it | military district planning: checkpoint, quarters, armory, power, command | build/rwfac2/ renders |
| Root Chamber (RWFAC3) | built by tools/build_rwfac3.py: the trial station's observation room (mmb) at the mouth of a cavern in the brown cave set, grown through with the mould (Fallout 1's Master's growths) | a natural cavern | build/rwfac3/ renders |
| Vault 39 | FO2 VAULT15, all three levels, used whole | the Vault-Tec pattern: entrance and door, living level, lab level | [entrance](plans/v39_0.png), [living](plans/v39_1.png), [labs](plans/v39_2.png), [references](plans/v39_refs.png) |
| Relay Station | Sonora RRADIO, used whole | AT&T Long Lines relay sites: one hardened building with equipment racks and diesel generators, buried fuel tanks, a lattice tower, a fenced compound | [plan](plans/relay.png), [basement](plans/relay1.png), [references](plans/relay_refs.png) |
| Lamesa Depot | stamps on the layout of the Andrews County waste site | Waste Control Specialists, Andrews County: a fenced site entered by an access road and guard house, a rail spur and unloading facility, a maintenance building, administration buildings with labs, a container storage building, and the disposal cells ([WCS](https://www.wcstexas.com/about/our-facilities/), [OSM](https://www.openstreetmap.org/#map=14/32.437/-103.060)) | [plan](plans/lamesa.png), [references](plans/lamesa_refs.png) |
| Garden City | stamps at the Main Street and highway crossing | Garden City, Glasscock County: the courthouse square on Main Street, the school grounds ([OSM](https://www.openstreetmap.org/#map=16/31.864/-101.482)) | [plan](plans/gardencity.png), [references](plans/gardencity_refs.png) |
| Odessa downtown | stamps on Grant Avenue and 8th Street | downtown Odessa: the Ector County courthouse, Grant Avenue ([OSM](https://www.openstreetmap.org/#map=16/31.845/-102.371)) | [plan](plans/odessa.png), [references](plans/odessa_refs.png) |
| Odessa cell works | stamps on the power plant and tank farm layout | Odessa's power plant, rail yard and tank farm ([OSM](https://www.openstreetmap.org/#map=15/31.83/-102.325)) | [plan](plans/odworks.png), [references](plans/odworks_refs.png) |
| Midland Air Base | stamps on the bomber field's layout | Midland Army Airfield, now Midland International ([OSM](https://www.openstreetmap.org/#map=14/31.943/-102.202)) | [plan](plans/midlandab.png), [references](plans/midlandab_refs.png) |
| Clairemont camp | your map, with its stories | refugee site planning: a central water point, latrines away from the tents and the water | [plan](plans/clcamp.png), [references](plans/clcamp_refs.png) |

### Webb Airbase

The real field runs in bands parallel to the flightline: the runway, the taxiway and apron, a row of hangars along Front Avenue (Hangar 25 among them), then the cantonment's parallel avenues, with the town beyond. The game bases (Olympus San Jose, Navarro, FORTDESO, BTBASEXT) put 2 to 6 large buildings, 3 to 10 squares apart, inside a fenced compound with a gate. The plan:

- the runway across the top, with the apron, the parked bombers and the crashed bomber (Sonora TSGRAVE and RNDBOMB)
- Hangar 25 and the control tower on Front Avenue
- the fuel tanks at the east end
- a fenced cantonment below: HQ opening onto the gate road, the parade ground across from it with the barracks north and the mess south, and the tents in rows in its west corner
- the powder store and the teamsters' shed in the far south-east corner, behind a barrier line

### Midland Ruins

Downtown Midland is a grid of roughly 100 m blocks. At the game's scale one crossing fills a map, so the plan is the crossing of Wall Street and Main Street:

- the ruined Petroleum Building on one corner
- the First Capital Bank on another, the band's home, its door on Wall Street
- Centennial Plaza with Ash's camp and the monument
- the Wilco ruin
- Front Street and the rail line to the south, where the caravan wreckage blocks Main Street by the exit

### The Facility Below

Built room by room in code by the originals' rules (tools/build_rwfac1.py, build_rwfac2.py, build_rwfac3.py); nothing copied, no Olympus pieces.

- **Waterworks, well-head level:** the stair landing under the colonists' ladder, a corridor with the stores off one side and the well-head room (the well's bore and its pump) off the other, the motor room behind it with a back passage round to the stores, and the intake shaft's open pit with the winch on its ledge.
- **Waterworks, treatment level:** the shaft foot where the rope comes down, the filter gallery with its bays, the chlorine store behind an airlock, the maintenance office and the control room behind electronic locks, the flooded pump hall (water over most of it, a grating walkway along the pumps and down to the west door), the breaker room and the service lift, the fallen-in dead east wing, and the pipe tunnel round to the control room's back door.
- **Annex, checkpoint:** the lift lobby with a wash room off it, the checkpoint hall with the guards' crate barricade and the guard post behind its window, the sealed vault door with its interlock panel, and the tunnel and stair room beyond.
- **Annex, main level:** one long corridor, with barracks, mess, command office and power room on the north side and a service passage behind the mess, the office and the power room, so the level loops; officers' quarters, the locked armory, stores, decontamination, the latrine and the stair room down on the south side.
- **Annex, trial station:** the alga tank lab behind its window, the sample lab and the monitoring post, the trial log room and the cold store, and the corridor's broken west wall into the natural galleries, which wind to a side cave with the survey team's cache and on to the way down, the mould thickening.
- **Root Chamber:** the approach up from the galleries, the observation room with its consoles under the window onto the cavern, and the cavern grown through with the mould, thickest at the back where the trial's intake pipe ends; the survey party's last camp just inside the mouth.

### Vault 39

Fallout 2's ruined Vault 15 holds the three levels:

- the cave and cog door, with mould growing out of the seal
- the living level: atrium, overseer's office, clinic and family quarters, with mould coming through the floors
- the lab level: culture labs, the water plant with the filter records, the cold store with the fungicide agent, the FEV store, and the experiment core broken into the root mass

### Relay Station

Sonora's Rangers radio station: a fenced compound with the lattice tower and a hatch to the hardened basement control room (where the broadcast is sent), the transmitter building with the operator's room, the buried fuel tank caps, and the crew's graves outside the fence. The operator is a ghoul who kept the station on the air after the war.

### Lamesa Depot

Laid out like the real low-level waste site near Andrews, Texas, on the New Mexico line:

- **Entry.** The access road comes in from the south past the guard house (the security bunker, with the locker) and a scale house with its weighbridge, added for the hazmat suit. A caravan yard with Odie's brahmin pens sits outside the fence.
- **Inside the fence.** The cask pad stands where the real site keeps its storage, with the gantry crane and the casks in rows. The processional path runs between the rows to the Reliquary at the east end.
- **The buildings.** The container storage building is the Hot Cell, with the rod racks and the bar among them. The administration and labs are the Chapel of Plutonius, and the maintenance building is Deacon Tritium's shop.
- **North.** The rail spur runs along the north side with a derailed cask on it, and beyond it the capped disposal cells are the flock's fields.

### Garden City

The real town is a small grid round the Glasscock County courthouse on Main Street. The plan puts:

- the courthouse (the town hall, where the council decides whether to tax, rob or serve the road) on a market square at the crossing of Main Street and the highway
- the saloon, the general store, a highway motel and the clinic along the highway
- toll gates of wrecked cars at both ends of the highway
- the settlers' camp on the old school field, with its water point and a latrine downwind

### Odessa

Two maps.

**Downtown** is Grant Avenue and 8th Street:

- the Cell Guild Hall and the Water Exchange in the guild quarter
- the Ector County Courthouse (the warlord sheriff) on the square, with the Pit
- the tenements and the clinic in the walled wards
- the caravan depot, where Redwell's water would come in

**The cell works** is the old power plant: the substation yard, the tank farm, the turbine hall as the assembly line, the cell store, and the gate and loading yard.

### Midland Air Base

The bomber field west of Midland:

- the runway and the hardstands with three B-25 hulks
- the bomber and maintenance hangars on the flightline road
- the tower
- the cell depot and ordnance bunkers in the east corner
- the garrison's barracks, officers' quarters, parade ground and motor pool by the gate

I made the garrison the Cell Guild's, holding its cell stockpile. Change that if you want someone else.

### The owner's maps

The owner's maps change only where the owner says yes.

| Map | Suggestion |
|---|---|
| Clairemont | A scroll ring so the camera stays on the town. |
| RWCORE2 | 602 exit hexes on four sides; towns use about 64 at road ends. |
