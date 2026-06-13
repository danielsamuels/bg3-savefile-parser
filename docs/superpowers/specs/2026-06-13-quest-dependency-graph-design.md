# Quest dependency graph and `quest_outlook` MCP tool

Status: approved design, 2026-06-13. MCP-only (local game install required).

## Motivation

An AI agent assisting a player wants to answer questions like "Are there any
quests I should prioritise completing?". To do that with grounded facts rather
than model recall, the MCP server needs to expose the game's own quest
interaction graph: which actions (advancing the story past a point of no
return, entering or leaving a region, killing an NPC, finishing another quest)
will close or advance a quest the player currently has open.

This relationship is game logic, not save state. A single save is a snapshot,
so the consequence cannot be derived from it. The rules live in the game data.

## Why this is feasible (spike findings, 2026-06-13)

The graph is authored declaratively in the paks and ships as readable text:

- `Gustav.pak` carries 805 Osiris goal scripts as source under
  `Mods/*/Story/RawFiles/Goals/*.txt` (no decompilation needed).
- Those goals contain a declarative `DB_QuestDef_*` database that ties triggers
  to quest state changes. Observed edge counts in the current install:
  `State` 965, `State_ConditionalFlag` 308, `ChainedState` 255,
  `LevelLoaded` 51, `BookReadState` 44, `State_CompanionLeft` 31,
  `SawDeadState` 28, `PermaDefeatedState` 22, `DefeatedState` 14,
  `ConditionalState` 7, `SawPermaDefeatedState` 6, `SawDefeatedState` 6,
  `LevelUnloading` 5. About 1,742 edges total.
- `quest_prototypes.lsx` defines each quest's `QuestStep` nodes, mapping a step
  id to its `Objective`, its `QuestTitle`, and an `UnlockDisable` value.
  `UnlockDisable == 2` marks a terminal (quest-closing) step; live progression
  steps are `0`, gated steps `1`. This is the close/terminal signal (there is
  no explicit boolean).
- `objective_prototypes.lsx` maps an `ObjectiveID` to a `Description` handle,
  resolved to English through `english.loca`.
- Flag names are embedded inline next to their GUIDs in the goal source, so the
  save's otherwise-cryptic `DB_GlobalFlag` GUIDs are nameable from these files.

End to end resolution was proven on a real install: the Act 2 point of no
return closes "Save Mayrina" (`HAG_HagSpawn`, step `ReachedNoReturn` ->
objective `HAG_HagSpawn_COMPLETION`, `UnlockDisable=2`), "Explore the Ruins"
(`CHA_Chapel`), "Cure the Poisoned Gnome" (`UND_DuergarPoison`), and others.

On-demand build cost measured at 0.46s total (0.41s of that is reading the
145,832-entry LSPK file list once; parsing 805 goals is 0.04s). The graph does
not need to be shipped; it is built on demand from the user's install and
cached, the same way display names already are.

## Architecture

### New module: `bg3parser/quest_graph.py`

Kept separate from `gamedata.py` to keep each module focused.

`build_quest_graph(data_dir) -> QuestGraph`
- Open `Gustav.pak` once, read its file list once (the earlier slowness came
  from `lspk_extract` re-reading the 145k-entry list per call; we extract from
  the held handle instead).
- Extract every `Story/RawFiles/Goals/*.txt`, parse all `DB_QuestDef_*`
  statements. Parser anchors on `DB_QuestDef_(\w+)\((.*?)\);` with DOTALL
  (statements end in `);`; argument casts like `(FLAG)`, `(ITEM)`,
  `(CHARACTER)` carry their own parens, so anchoring on the trailing `);`
  avoids truncating at a cast). Split the captured argument list on top-level
  commas, strip cast prefixes, then read quoted strings and `S_<name>_<guid>`
  tokens.
- Read `quest_prototypes.lsx` `QuestStep` nodes to build
  `(quest_id, step_id) -> {objective_id, unlock_disable, quest_title_handle}`,
  and `objective_prototypes.lsx` for `objective_id -> description_handle`
  (this second map already exists in `gamedata.py`; reuse rather than duplicate).
- Resolve title and objective handles through the loca map already loaded by
  `DisplayNames`.
- Cache the built graph under `XDG_CACHE_HOME` keyed on the source paks'
  mtime and size plus `QUEST_GRAPH_SCHEMA_VERSION`, mirroring
  `gamedata.build_displayname_maps`.

`QuestGraph` (dataclass / small class)
- Holds the edge list and lookup indices.
- `terminating_edges_for(quest_id) -> list[Edge]`: edges whose target quest is
  `quest_id` and whose target step is terminal (`unlock_disable == 2`).
- `edges_for(quest_id) -> list[Edge]`: all edges touching the quest.
- `point_of_no_return_groups() -> list[...]`: terminal edges grouped by their
  point-of-no-return trigger.

### Edge model

Each `DB_QuestDef_*` kind normalises to a common `Edge` with a human trigger
descriptor:

- `State(flag, quest, step)`: trigger is the flag, resolved to its inline name.
  Flags whose name contains `PointOfNoReturn` are marked `point_of_no_return`.
  `State_ConditionalFlag` and `State_CompanionLeft` are State variants; include
  them with best-effort trigger text.
- `LevelLoaded(quest, step, LEVEL)` / `LevelUnloading`: trigger is
  "Entering" / "Leaving" the region, resolved to a display name via the
  existing subregion map where the LEVEL id is present there, else the raw id.
- `DefeatedState` / `PermaDefeatedState` / `SawDeadState` / `SawDefeatedState`
  / `SawPermaDefeatedState (quest, step, S_<npc>_<guid>)`: trigger is the NPC
  dying; name taken from the `S_<name>_<guid>` token.
- `BookReadState(quest, step, S_<item>_<guid>)`: trigger is reading the item.
- `ChainedState(questA, stepA, questB, stepB)`: an edge from one quest step to
  another; records both endpoints.
- `ConditionalState`: include with best-effort text.

Fields: `kind`, `trigger_kind` (one of `flag`, `point_of_no_return`,
`region_enter`, `region_leave`, `npc_death`, `book_read`, `quest_chain`,
`conditional`), `trigger_label` (human string), `quest_id`, `quest_title`,
`target_step`, `target_objective_text`, `terminal` (bool), `result`
("closes" when terminal, else "advances").

### MCP tool: `quest_outlook(save)` in `bg3parser/mcp_server.py`

Dedicated tool; leaves `parse_save` and its token budget untouched.

- Resolve the save with the existing `cached_report(path, want_quests=True)` to
  get active and closed quest ids and the current objective per active quest.
- Load the `QuestGraph` (cached build).
- For each active quest, attach its `terminating_edges` (the triggers that will
  close it). Also build a `point_of_no_return_groups` summary so the agent can
  say "advancing to the Shadow-Cursed Lands will close: A, B, C".

Output shape:

```json
{
  "active_quests": [
    {
      "id": "HAG_HagSpawn",
      "title": "Save Mayrina",
      "current_objective": "Defeat the hag",
      "terminating_triggers": [
        {
          "trigger_kind": "point_of_no_return",
          "trigger": "Reaching the Act 2 point of no return (Shadow-Cursed Lands)",
          "result": "closes",
          "result_text": "..."
        }
      ]
    }
  ],
  "point_of_no_return_groups": [
    { "trigger": "Act 2 point of no return", "closes": ["Save Mayrina", "Explore the Ruins"] }
  ]
}
```

The agent composes the prioritisation advice from this structured data.

## Decisions and deliberate v1 boundaries

- Fail versus complete: the tool surfaces `terminal` plus the resulting journal
  text and lets the agent judge "lost" versus "finished". There is no boolean
  in the data; the text carries the meaning. No fail classifier is built.
- Imminence: v1 surfaces the static relationship and a human trigger
  description, not a computed "how close is this trigger". Proximity would need
  story-progress modelling. Point-of-no-return triggers are inherently "the
  next major advance", which is the actionable signal.
- Parity: Python and MCP only for v1. No change to `gamedata.json`, so the TS
  port and the web site are untouched. TS parity is deferred with the rest of
  web support.
- Packaging: built on demand and cached, not shipped. The committed-fallback
  file (for no-install contexts like the web) is deferred until web support is
  wanted.

## Testing

- Pure parser unit test (runs in CI, no install): feed inline goal-text samples
  covering each `DB_QuestDef_*` kind and assert the parsed edges, including the
  cast-prefix and multi-line cases.
- Install-gated integration test: mirror the existing
  `GAME_DATA_AVAILABLE = gamedata.DisplayNames.load().available` plus
  `@pytest.mark.skipif` pattern. Build the real graph and assert known edges
  resolve (for example `HAG_HagSpawn` has an Act 2 point-of-no-return terminal
  edge resolving to "Save Mayrina").
- A small MCP-level test that `quest_outlook` on a fixture save returns the
  expected structure.

## Implementation order

1. `quest_graph.py`: edge parser (pure function over goal text) plus its unit
   test.
2. `quest_graph.py`: prototype reading (QuestStep / objective / title) and loca
   resolution, reusing `gamedata` helpers.
3. `quest_graph.py`: `build_quest_graph` with caching, plus the `QuestGraph`
   lookups and the install-gated integration test.
4. `mcp_server.py`: the `quest_outlook` tool and its test.
5. Update the MCP server description and any user-facing docs.

## Implementation notes (as built, 2026-06-13)

Deviations and discoveries from the build, kept for posterity:

- Caching: built once per MCP server process (`shared_quest_graph`), not the
  disk cache the design proposed. The build is about 0.9s and the server is
  long-lived, so an in-process cache is enough; a disk cache can be added if a
  per-process CLI command ever needs the graph.
- New `lspk_extract_many(pak, predicate)` opens the pak and reads its file list
  once for bulk extraction (the single-file `lspk_extract` re-reads the 145k
  entry list per call). The whole graph build is one pak open.
- `ChainedState` has two forms: the documented 4-arg cross-quest form and a
  3-arg within-quest form `(quest, fromStep, toStep)`. `normalize_edge` handles
  both and guards against statements with too few args (132 real 3-arg chains
  would otherwise crash).
- More edge kinds than first surveyed: `State_ConditionalFlag` and
  `State_CompanionLeft` join the State family; trigger kinds are
  point_of_no_return, flag, companion_left, region_enter, region_leave,
  npc_death, npc_defeated, book_read, quest_chain, conditional.
- NPC and book triggers label with the internal entity name (e.g.
  "GLO_DoubtingArtist is defeated"), not a display name; per-entity display
  names are the known FixedString limit, so the agent interprets the internal
  name.
- Built graph on the test install: 1466 edges, 269 terminal, 20 explicit
  point-of-no-return. quest_outlook on an Act 3 save returns 8 of 18 active
  quests with closing triggers (0 point-of-no-return groups, since that save
  is already past the Act 2 gate).
