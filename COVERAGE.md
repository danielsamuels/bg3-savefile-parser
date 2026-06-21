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
| Deity / god | Character sheet (cleric/paladin) | unsurfaced | `game.god.v0.GodComponent` present, not read |
| Background | Character sheet | unsurfaced | `game.character_creation.v0.BackgroundComponent` present, not read |
| Background-goal progress | Character sheet | unsurfaced | `game.background.v0.GoalRecord` / `GoalsComponent` present, not read |
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
| Hirelings (Withers) | unsurfaced | `game.recruit.v0.RecruitedByComponent` / `RecruiterComponent` identify them; not a report field |
| Active summons | unsurfaced | `game.summons.v0/v1/v2.*` present, not read |
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
| Long rests taken | done | |
| Days passed / in-game date | unsurfaced | `game.calendar.v0.DaysPassedComponent` / `StartingDateComponent` present, not read |

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
3. Component registry (`tests/test_component_registry.py`, tool
   `tests/audit_components.py`). The structural analogue of the resource
   registry, aimed at the tadpole pool's real failure mode: a whole component
   the player sees that nothing reads. It lists every player-facing component a
   save contains that no view consumes, split into GAPS (worth surfacing) and
   INTERNAL; the guard fails if a save has one in neither, so a new component
   from a patch or an unexercised build gets triaged.
4. Name-resolution guard (`tests/test_name_resolution.py`). Asserts every
   base-game spell, quest, and item name still resolves through gamedata in each
   fixture, so a gamedata rebuild cannot silently degrade the report to raw ids.
   Mod content is excluded by design (see below).
5. Live ground-truth validation. The only check that catches unknown unknowns is
   comparing the report to what the game actually shows. See below.

The Osiris database surface was reviewed (2026-06-21) and deliberately left
without a guard: of ~180 player-facing-keyword DBs not consumed, effectively all
are internal story-engine plumbing (background-goal chains, defeat counters,
dialog bookkeeping). The player-facing story state (quests, approval, romance,
flags) is already consumed or reasoned over by the quest-analysis engine, so an
Osiris audit would be almost pure noise. Revisit if a specific story value is
ever found missing; `DB_GLO_Backgrounds_*` is where background-goal progress
lives, and `DB_RelationshipDialogsFinished` tracks romance depth beyond dating.

## Allow-lists and filters

Every place we hardcode an exclusion, with provenance. The principle: a denylist
fails safe (a new thing is visible until excluded), an allowlist fails silent (a
new thing is invisible until added), so filters here are denylists wherever
possible. Each entry is also a small parked bug: prefer fixing it to growing the
list.

| What | Where | Kind | Why / exposure |
|---|---|---|---|
| `KNOWN_UNRESOLVED_ITEMS` (FOR_SchoolOgres_Horn = "Lump's War Horn") | test_name_resolution | masking | base-game quest item whose display name lives on the root template, not the stats entry our extraction keys by; absent from our gamedata stats map. Allow-listed so a *new* unresolved item still fails. Durable fix: capture template display names in gamedata extraction (needs a game install). |
| `MOD_MARKERS` (`_Mods_`, `Macro_`) | test_name_resolution | denylist | excludes mod-added names (unbounded scope); base-game names stay asserted. A mod name not matching these would surface as a failure, not hide silently. |
| `DENY_NAMESPACES` + `DENY_PATTERN` | audit_components | denylist | engine-internal components (visual/AI/UI/ownership/...). Fail-safe: a new player-facing namespace is a candidate by default. Validated across 83 real saves. |
| `COVERED_ELSEWHERE` | audit_components | classification | components surfaced via byte-scan/Osiris/info.json that no name literal catches. Stale risk: if such a consumer is removed, the component stays hidden. |
| `GAPS` / `INTERNAL` | test_component_registry | classification | reviewed disposition per candidate component. Risk: a component misjudged INTERNAL is hidden; the lists were triaged against all 83 real saves to limit that. |
| `handled-unnamed` rows | test_resource_registry | masking | two resources we surface without a gamedata name. |
| `is_real_guid` | audit_resources | denylist | rejects float-fragment byte runs in the census diagnostic. The resource *guard* does not depend on it (it uses the per-character component + named census), so a real resource cannot hide behind it. |
| `BASE_MODULES` | lspk.py | denylist | base-game modules, to detect user mods. Patch-fragile: a renamed/added base module misclassifies. |
| `skipif(not GAME_DATA_AVAILABLE)` | test_parser | env skip | ~8 tests need a local game install, so they do not run in CI. Coverage gap, not masking. |

## Genuinely unreachable (live-only)

These are known unknowns that are not gaps to fix: the engine never writes them
to disk, proven per item (see the format-completeness work and LIMITS.md). They
are reachable only from the running game (`memscan.py`), not from a save:

- Live EntityHandle targets, including exact equipped item slot in the ambiguous
  dual-wield cases
- The "new item" UI flag (session-only)
- Mid-shuffle / fresh-split stack counts (settled saves are exact)
- A handful of live-pointer component fields and DeathData causes
- ComponentDesc hash preimages (need the game binary's RTTI)

## In-game validation checklist

Fill `tests/ground_truth/<save>.json` from the in-game UI for one save, then run
`pytest -k live_parity`. The template lists exactly what to read; values we
already produce are asserted (regression guard), and the rest document the
target for when each gap is closed.

Two-minute priority (these unblock the cheapest wins, the standalone resources
that are already named and read, just not surfaced):

- **Inspiration points** (expected to match resource `a9c98304`, value seen 4)
- **Short rests remaining** (resource `a24ca5e2`, value seen 2) and confirm
  whether the number shown is remaining, the allowance, or rests taken
- **Illithid tadpoles available to spend** (regression check, already shipped)

Then, per the chosen save, for the broader gaps:

- Party gold; camp supplies; long rests taken; days passed / in-game date
- Per party character: HP current/max, AC, exhaustion, active statuses/conditions,
  resistances/immunities, skill proficiencies, deity (cleric/paladin), background,
  and every hotbar resource pool (name + current/max)

The same loop that cracked the tadpole pool (read a number in-game, find it in
the report) is now cheap: `memscan.py` can locate any displayed value in the
running process if it is not yet in a save we can map.
