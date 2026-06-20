# Feature coverage

What a Baldur's Gate 3 player can observe in-game, and whether the report
produces it. This is the top-down companion to FORMAT.md: FORMAT.md tracks
whether the bytes are decoded; this tracks whether the player-facing concept
reaches the report. The two diverge, and that gap is the point of this file.

Why it exists: we once declared the save format "complete" because every byte
was classified, while the Illithid Powers pool a player sees on screen was in no
report. Byte-coverage is not feature-coverage. The lesson is that completeness
has to be measured against the game's observable output, not against our own
model of its internals. Each gap below has a matching `xfail(strict=True)` test
in `tests/test_coverage_gaps.py`, so when one is closed CI forces the marker off.

## Legend

- done: surfaced in the report (JSON/text/AI briefing)
- unsurfaced: read into the model but not in any report output
- unlabeled: value is read but we have no name for it (gamedata gap)
- missing: not read at all
- live-only: not on disk; reachable from the running game via `memscan.py`

## Character sheet

| Feature | In-game location | Status | Notes |
|---|---|---|---|
| Race, class, subclass, level, XP | Character sheet header | done | multiclass included |
| Ability scores | Character sheet | done | |
| HP current/max | Portrait | done | |
| Armour Class | Character sheet | missing | not extracted |
| Initiative bonus | Character sheet | missing | |
| Proficiency bonus | Character sheet | missing | |
| Skill proficiencies / expertise | Character sheet > Skills | missing | |
| Saving-throw proficiencies | Character sheet | missing | |
| Weapon / armour proficiencies | Character sheet | missing | |
| Resistances / immunities / vulnerabilities | Character sheet | missing | FORMAT decodes some damage data; none surfaced |
| Active statuses / conditions (+ durations) | Portrait status row | missing | concentration is the only status we surface |
| Concentration | Portrait | done | |
| Exhaustion level | Status | missing | |
| Inspiration points | Top bar | unsurfaced | it is the standalone resource `a9c98304` "Inspiration Point" (value read, not surfaced); walk the standalone collection to expose it |
| Background + background-goal progress | Character sheet | missing | |
| Passive features (class/racial) | Character sheet > Passives | missing | distinct from feats; we surface feats only |
| Feats taken | Level-up history | done | |
| Prepared / known spells, cantrips | Spellbook | done | with source and level |
| Illithid powers | Illithid Powers tree | done | per character |
| Encumbrance / carry weight | Inventory | missing | |

## Resources (action resources)

| Feature | In-game location | Status | Notes |
|---|---|---|---|
| Per-character pools (spell slots, ki, rage, channel divinity, superiority dice, …) | Hotbar resource row | done | named where gamedata has the GUID |
| Illithid tadpole pool | Illithid Powers screen | done | standalone-collection resource `8b047f9c` "Tadpole Power Point" |
| Inspiration points | Top bar | unsurfaced | standalone resource `a9c98304` "Inspiration Point" (named, read, not surfaced) |
| Short rests remaining | Rest UI | unsurfaced | standalone resource `a24ca5e2` "Number of Short Rests" (named, read, not surfaced) |
| The standalone resource collection generally | various | unsurfaced | `parse_lsmf_action_resources` walks only the per-character component; the collection holding the three above (and others) is not walked. One implementation surfaces all of them. |
| Resource name resolution | gamedata | unlabeled | a few present GUIDs have no gamedata name (e.g. `78236f5a`); harmless but blocks labelling |

Every resource GUID and its handling status lives in one table,
`tests/test_resource_registry.py` (handled / handled-unnamed / gap). A guard
test fails if any named resource present in a save is missing from that table,
so a new resource (new class build, patch, or an unwalked collection) cannot
appear without being given a status. `tests/audit_resources.py` is the matching
diagnostic you run by hand against a fresh save.

## Party and camp

| Feature | Status | Notes |
|---|---|---|
| Active party roster | done | |
| Camp companions | done | |
| Hirelings (Withers) | unsurfaced | touched in code; not a clean report field |
| Camp chest contents | done | |
| Gold (party) | done | summed |
| Camp supplies | done | |
| Approval ratings + romance | done | |
| Companion personal-quest state | missing | beyond the global quest list |

## Inventory and economy

| Feature | Status | Notes |
|---|---|---|
| Equipped gear by slot | done | empty slots visible |
| Carried items, bag contents | done | |
| Item rarity | done | |
| Item charges / per-rest uses remaining | missing | passive use-counts decodable (UsageCountComponent) but not surfaced |
| Runes / dyes applied | missing | |
| Wares (marked to sell) | missing | |
| Recipes known | done | count only |
| Vendor stock | done | |

## Quests, story, world

| Feature | Status | Notes |
|---|---|---|
| Active quests + current objectives | done | |
| Closed quests | done | completed and failed not distinguished |
| Quest dependency / consequence analysis | done | the quest analyser engine |
| Faction reputation / relations | unsurfaced | FactionComponent is decoded per FORMAT; no report field |
| Key story decisions / global flags | unlabeled | raw `global_flags` collected; not interpreted into readable decisions |
| Discovered areas / fog-of-war % | unsurfaced | shroud buffer decoded byte-exact; not summarised |
| Waypoints unlocked | done | |
| Day / long rests taken | done | |

## Save metadata

| Feature | Status |
|---|---|
| Save name, id, timestamp, game version, difficulty, leader, region, mods | done |

## Keeping this honest

Three mechanisms, in order of strength:

1. Strict-xfail backlog (`tests/test_coverage_gaps.py`). Every "missing",
   "unsurfaced", or "unlabeled" row above has a test that asserts the desired
   state and is marked `xfail(strict=True)`. Implement the feature and the test
   goes from xfail to a hard failure demanding the marker be removed. The
   backlog cannot silently rot.
2. Resource registry (`tests/test_resource_registry.py`). Every resource GUID
   carries a status; a guard fails if a save contains a named resource the
   registry does not list. Generalises the tadpole miss: the "we decoded the
   type so we have them all" error is caught at the instance level, not by
   anyone remembering to look.
3. Live ground-truth validation. The only check that catches unknown unknowns is
   comparing the report to what the game actually shows. See below.

## In-game validation checklist

Fill `tests/ground_truth/<save>.json` from the in-game UI for one save, then run
`pytest -k live_parity`. The template lists exactly what to read; values we
already produce are asserted (regression guard), and the rest document the
target for when each gap is closed. Read, per the chosen save:

- Party gold; camp supplies; long rests taken
- Illithid tadpoles available to spend
- Inspiration points
- For each party character: HP current/max, AC, exhaustion level, active
  statuses/conditions, damage resistances/immunities, skill proficiencies, and
  every resource pool shown on their hotbar (name + current/max)

The same loop that cracked the tadpole pool (read a number in-game, find it in
the report) is now cheap: `memscan.py` can locate any displayed value in the
running process if it is not yet in a save we can map.
