"""Convenience facade: gather the model and render it as text in one call."""

from .model import gather_report
from .render import render_text


def build_report(save_path: str, frames: dict[str, bytes] | None = None, opts=None) -> str:
    """Parse a save and return the plain-text report (model + text view)."""
    return render_text(gather_report(save_path, frames, opts), opts)
