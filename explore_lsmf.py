# /// script
# requires-python = ">=3.11"
# dependencies = ["zstandard", "lz4"]
# ///
"""Interactive exploration harness for the BG3 LSMF ECS blob.

Run it to dump a save's complete component directory (name, element size,
row count, ownerlist length, data offset):

    uv run explore_lsmf.py 286            # save number, like bg3save
    uv run explore_lsmf.py path/to.lsv

Or import it for spelunking (see FORMAT.md §6 for the structures):

    from explore_lsmf import Lsmf
    m = Lsmf('286')
    m.comp('game.spell.v3.SpellData')         # descriptor tuple
    m.row_bytes('core.v0.EntityId', 13)       # raw row bytes
    m.rows_of_entity('game.inventory.v0.MemberComponent', 853)
    m.locate(0x15e0b8)                         # offset -> (component, row, byte)
    m.item_entity_rows('Wyll', 'UND_SwordInStone')
"""
import struct
import sys

from bg3parser import discovery, lsf, lsmf, lspk, party


class Lsmf:
    """A loaded save with its ECS blob indexed for exploration."""

    def __init__(self, save_token: str):
        self.save = discovery.find_save_by_token(save_token) or save_token
        self.frames = lspk.extract_frames(self.save)
        self.nodes0 = lsf.parse_lsof(lsf.decomp_frame(self.frames['Globals.lsf']))
        self.blob = b''
        for nd in self.nodes0:
            if nd['name'] == 'NewAge' and nd['parent'] == -1:
                raw = nd['attrs'].get('NewAge')
                if isinstance(raw, bytes):
                    self.blob = raw
                break
        # name -> (elem_size, row_count, data_offset, owner_rows)
        self.index = lsmf.lsmf_component_index(self.blob)
        # Entity bridge: GUID -> EntityId rows; item template maps
        self.ecs = lsmf.parse_lsmf_membership(self.blob)
        self.guid_to_rows = self.ecs[0] if self.ecs else {}
        self.e2t = party.build_entity_template_map(self.nodes0, 'Items')
        self.t2i = party.invert_entity_template_map(self.e2t)
        self.instance_map = party.build_instance_entity_map(self.nodes0)
        meta = lspk.parse_metadata(self.frames)
        player = meta.get('leader_name') or 'Player'
        self.party_nodes = party.find_party_character_nodes(self.nodes0, player)
        self.char_positions = party.collect_character_positions(self.nodes0, self.party_nodes)

    def comp(self, name: str) -> tuple:
        """(elem_size, row_count, data_offset, owner_rows) for a component."""
        return self.index[name]

    def row_bytes(self, name: str, row: int) -> bytes:
        """Raw bytes of one component data row."""
        elem, _rows, off, _owners = self.index[name]
        return self.blob[off + row * elem: off + (row + 1) * elem]

    def rows_of_entity(self, name: str, entity_row: int) -> list[int]:
        """Data-row indices in component `name` owned by the given entity row
        (ownerlist position == data row, see FORMAT.md §6)."""
        _elem, _rows, _off, owners = self.index[name]
        return [k for k, e in enumerate(owners) if e == entity_row]

    def locate(self, off: int) -> tuple[str, int, int] | None:
        """Resolve an absolute byte offset to (component, row, byte_in_row)."""
        for name, (elem, rows, base, _owners) in self.index.items():
            if elem and base <= off < base + elem * rows:
                rel = off - base
                return name, rel // elem, rel % elem
        return None

    def entity_guid(self, row: int) -> str:
        """Canonical GUID string stored in an EntityId row."""
        _elem, _rows, off, _owners = self.index['core.v0.EntityId']
        return lsf.guid_le_str(self.blob[off + row * 16: off + row * 16 + 16])

    def item_entity_rows(self, char_name: str, stats: str) -> list[int]:
        """EntityId rows for a specific character's item instance."""
        pos = None
        for name, t in self.char_positions.items():
            if char_name.lower() in name.lower():
                pos = t
                break
        for (trans, stats_key), eg in self.instance_map.items():
            if trans == pos and stats_key == stats:
                return self.guid_to_rows.get(eg, [])
        return []

    def heap_u64s(self, begin: int, end: int) -> list[int]:
        """Read a {begin, end} heap range as u64s (pointers are absolute-48)."""
        lo = begin + lsmf.LSMF_HEAP_BASE
        hi = end + lsmf.LSMF_HEAP_BASE
        n = max(0, (hi - lo) // 8)
        return list(struct.unpack_from(f'<{n}Q', self.blob, lo))


def main() -> None:
    m = Lsmf(sys.argv[1] if len(sys.argv) > 1 else '')
    print(f'{m.save}: blob={len(m.blob)} bytes, {len(m.index)} components')
    print(f'{"elem":>5} {"rows":>7} {"ownerlist":>9} {"data_off":>10}  name')
    for name, (elem, rows, off, owners) in sorted(
            m.index.items(), key=lambda kv: kv[1][2]):
        print(f'{elem:5d} {rows:7d} {len(owners):9d} {off:#10x}  {name}')


if __name__ == '__main__':
    main()
