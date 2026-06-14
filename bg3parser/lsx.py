"""Helpers for reading Larian's LSX files (the game's XML data format).

LSX documents are attribute bags: ``<node id="X">`` elements carry
``<attribute id="..." value="..."/>`` (or ``handle="..."`` for localised
strings) children, and nest further nodes under a ``<children>`` wrapper. These
helpers parse with the stdlib XML parser and expose node iteration plus
attribute lookup, so callers select data by element and attribute identity
rather than by matching the serialised text — which is robust to attribute
order, whitespace, self-closing tags, and entity escaping.
"""

from xml.etree import ElementTree as ET


def parse(text: str) -> ET.Element:
    """Parse LSX text and return its root element."""
    return ET.fromstring(text)


def all_nodes(root: ET.Element):
    """Yield every ``<node>`` element at any depth under root (root included)."""
    return root.iter('node')


def iter_nodes(root: ET.Element, node_id: str):
    """Yield every ``<node id="node_id">`` at any depth under root.

    Nesting is handled by the parser, so a node is found wherever it sits in the
    tree; callers do not have to reason about how deeply it is wrapped.
    """
    for node in root.iter('node'):
        if node.get('id') == node_id:
            yield node


def attrs(node: ET.Element) -> dict[str, str | None]:
    """Map a node's direct ``<attribute id=...>`` children to their value.

    A ``value`` attribute is preferred; ``handle`` (used by TranslatedString
    localisation references) is the fallback. Only direct children are read, so
    attributes of nested child nodes never bleed into the parent.
    """
    out: dict[str, str | None] = {}
    for attr in node.findall('attribute'):
        aid = attr.get('id')
        if aid is None:
            continue
        out[aid] = attr.get('value', attr.get('handle'))
    return out
