# TypeScript parser & site

A client-side port of the Python reference implementation in `bg3parser/`.
The goal: a fully static, privacy-first website (GitHub Pages / Cloudflare
Pages) that parses a `.lsv` save entirely in the browser — the file never
leaves the machine.

## Layout

- `ts/parser` — `@bg3save/parser`: pure library, no DOM. Mirrors the Python
  module boundaries one-to-one (`lspk` / `lsf` / `lsmf` / `party` / `model`)
  so any divergence has an obvious home in both codebases.
- `ts/site` — the static web app (not started yet).

Tooling: Bun workspaces, vitest (kept over `bun test` for its browser mode),
strict TypeScript. Only runtime dependency: `fzstd`; LZ4 (block + frame) is
implemented in `src/lz4.ts`.

## Parity rules

The Python implementation stays the research lab and reference. The fixture
saves under `tests/fixtures/` are the shared oracle: TS tests read them
directly and assert in-game-verified facts; once the report model exists,
canonical JSON from `bg3save --json` becomes the field-for-field contract.
New format discoveries land in Python first, get a fixture test, then port.

## Milestones

1. ~~LSPK container, decompression, SaveInfo.json~~ ✅
2. ~~LSOF node-tree parser (meta.lsf + Globals.lsf, ~260ms for 24MB)~~ ✅
3. ~~LSMF ECS blob: component directory + ownerlist scan, membership
   counts, ContainerSlotData positions, stack amounts (34ms)~~ ✅
   (spell books and classes land with milestone 4)
4. Classification: party attribution, equipment cluster, slot conflicts,
   per-instance duplicates — full report parity with `bg3save --json`
   (gamedata JSON built by Python and consumed at runtime)
5. The site: drag-drop + Web Worker parse, report views, IndexedDB history,
   File System Access live mode, PWA; deploy to Pages
