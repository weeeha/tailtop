"""Command palette provider — surfaces verbs for the selected peer + globals."""

from __future__ import annotations

from textual.command import DiscoveryHit, Hit, Hits, Provider


class TailtopCommands(Provider):
    """Feeds the built-in command palette (Ctrl+P) from the app's verb list."""

    async def discover(self) -> Hits:
        for label, callback, help_text in self.app.palette_entries():
            yield DiscoveryHit(label, callback, help=help_text)

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        for label, callback, help_text in self.app.palette_entries():
            score = matcher.match(label)
            if score > 0:
                yield Hit(score, matcher.highlight(label), callback, help=help_text)
