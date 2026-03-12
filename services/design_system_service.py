"""
Design system service — manages per-session luxury modern design tokens.
"""
from __future__ import annotations

import random
from dataclasses import asdict, dataclass, field

PALETTES = {
    "midnight": {
        "primary": "#6366f1",
        "secondary": "#a78bfa",
        "bg": "#0a0a0f",
        "surface": "#12121a",
        "text": "#f0f0ff",
        "muted": "#6b7280",
    },
    "obsidian": {
        "primary": "#f59e0b",
        "secondary": "#fbbf24",
        "bg": "#0c0c0c",
        "surface": "#141414",
        "text": "#fafaf9",
        "muted": "#78716c",
    },
    "arctic": {
        "primary": "#06b6d4",
        "secondary": "#22d3ee",
        "bg": "#020b18",
        "surface": "#0f1929",
        "text": "#e2f3ff",
        "muted": "#64748b",
    },
    "forest": {
        "primary": "#10b981",
        "secondary": "#34d399",
        "bg": "#030a07",
        "surface": "#0d1f15",
        "text": "#ecfdf5",
        "muted": "#6b7280",
    },
    "rose": {
        "primary": "#f43f5e",
        "secondary": "#fb7185",
        "bg": "#0f0508",
        "surface": "#1a0b11",
        "text": "#fff1f2",
        "muted": "#9f8090",
    },
    "slate": {
        "primary": "#94a3b8",
        "secondary": "#cbd5e1",
        "bg": "#0f172a",
        "surface": "#1e293b",
        "text": "#f8fafc",
        "muted": "#64748b",
    },
}

FONT_PAIRS = [
    {"display": "Playfair Display", "body": "Inter"},
    {"display": "Cormorant Garamond", "body": "DM Sans"},
    {"display": "Space Grotesk", "body": "Inter"},
    {"display": "Syne", "body": "Manrope"},
    {"display": "Cal Sans", "body": "Inter"},
    {"display": "Fraunces", "body": "Source Sans 3"},
]


@dataclass
class DesignSystem:
    palette_name: str = "midnight"
    colors: dict = field(default_factory=dict)
    display_font: str = "Playfair Display"
    body_font: str = "Inter"
    base_size: str = "16px"
    scale: float = 1.25  # type scale ratio
    radius_sm: str = "4px"
    radius_md: str = "12px"
    radius_lg: str = "24px"
    shadow_sm: str = "0 1px 3px rgba(0,0,0,.4)"
    shadow_md: str = "0 4px 24px rgba(0,0,0,.5)"
    shadow_lg: str = "0 16px 64px rgba(0,0,0,.6)"
    motion: str = "subtle"   # subtle | expressive | none
    density: str = "airy"   # airy | balanced | compact
    archetype: str = "saas"  # saas | marketplace | tool | agency | social

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "DesignSystem":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})  # type: ignore[attr-defined]

    @classmethod
    def generate(cls, style_seed: dict | None = None) -> "DesignSystem":
        """Create a DesignSystem from optional style_seed hints, randomizing unspecified fields."""
        seed = style_seed or {}
        palette_name = seed.get("palette") or random.choice(list(PALETTES.keys()))
        fonts = random.choice(FONT_PAIRS)
        archetype = seed.get("archetype") or "saas"
        motion = seed.get("motion") or random.choice(["subtle", "expressive"])
        density = seed.get("density") or "airy"
        return cls(
            palette_name=palette_name,
            colors=PALETTES[palette_name],
            display_font=fonts["display"],
            body_font=fonts["body"],
            archetype=archetype,
            motion=motion,
            density=density,
        )

    def to_css_vars(self) -> str:
        """Render as CSS custom properties block."""
        c = self.colors
        spacing = "1.5" if self.density == "airy" else ("1.2" if self.density == "balanced" else "1.0")
        return f"""
  --color-primary: {c.get('primary', '#6366f1')};
  --color-secondary: {c.get('secondary', '#a78bfa')};
  --color-bg: {c.get('bg', '#0a0a0f')};
  --color-surface: {c.get('surface', '#12121a')};
  --color-text: {c.get('text', '#f0f0ff')};
  --color-muted: {c.get('muted', '#6b7280')};
  --font-display: '{self.display_font}', serif;
  --font-body: '{self.body_font}', sans-serif;
  --radius-sm: {self.radius_sm};
  --radius-md: {self.radius_md};
  --radius-lg: {self.radius_lg};
  --shadow-sm: {self.shadow_sm};
  --shadow-md: {self.shadow_md};
  --shadow-lg: {self.shadow_lg};
  --spacing: {spacing};""".strip()

    def to_prompt_block(self) -> str:
        """Render as a prompt injection block for the LLM."""
        return f"""DESIGN SYSTEM (follow exactly — do not deviate):
Palette: {self.palette_name}
  Primary: {self.colors.get('primary')}  Secondary: {self.colors.get('secondary')}
  Background: {self.colors.get('bg')}    Surface: {self.colors.get('surface')}
  Text: {self.colors.get('text')}        Muted: {self.colors.get('muted')}
Typography:
  Display font: {self.display_font} (for headings, hero text)
  Body font: {self.body_font} (for body, UI)
  Scale ratio: {self.scale}
Spacing density: {self.density}
Border radius: sm={self.radius_sm} md={self.radius_md} lg={self.radius_lg}
Shadows (elevation): sm="{self.shadow_sm}" md="{self.shadow_md}" lg="{self.shadow_lg}"
Motion: {self.motion}
Archetype: {self.archetype}

Import fonts via @import in <style>: https://fonts.googleapis.com/css2?family={self.display_font.replace(' ', '+')}:wght@300;400;600;700&family={self.body_font.replace(' ', '+')}:wght@300;400;500;600&display=swap

USE CSS CUSTOM PROPERTIES (:root block) for ALL colors, fonts, radii, shadows.

RESPONSIVE SPACING + LAYOUT RULES (always apply):
- Use fluid tokens with clamp() for section spacing, heading sizes, and container gutters.
- Add at least these breakpoints: @media (max-width: 1024px) and @media (max-width: 640px).
- Use anti-squish layout patterns: repeat(auto-fit, minmax(...)) OR flex-wrap with sensible min widths.
- Avoid fixed-width desktop-only blocks that force horizontal scrolling on phones/tablets.
- Ensure cards/media use max-width: 100% and text uses overflow-safe wrapping."""
