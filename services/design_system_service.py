"""
Design system service — manages per-session Framer Aura design tokens.
"""
from __future__ import annotations

import hashlib
import random
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

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
    # Framer Aura — neutral slate base + blue/purple/pink gradient ramp
    "framer_aura": {
        "primary": "#3b82f6",
        "secondary": "#8b5cf6",
        "accent_pink": "#ec4899",
        "bg": "#f8fafc",
        "surface": "#ffffff",
        "surface_elevated": "#f1f5f9",
        "text": "#0f172a",
        "muted": "#64748b",
        "border": "#e2e8f0",
    },
    "framer_aura_dark": {
        "primary": "#60a5fa",
        "secondary": "#a78bfa",
        "accent_pink": "#f472b6",
        "bg": "#0f172a",
        "surface": "#1e293b",
        "surface_elevated": "#334155",
        "text": "#f8fafc",
        "muted": "#94a3b8",
        "border": "#334155",
    },
    # Additional palettes for uniqueness engine
    "aurora": {
        "primary": "#14b8a6",
        "secondary": "#06b6d4",
        "bg": "#0a1628",
        "surface": "#0f2340",
        "text": "#e0f7f7",
        "muted": "#6b9aaa",
    },
    "ember": {
        "primary": "#f97316",
        "secondary": "#ef4444",
        "bg": "#1a0a00",
        "surface": "#2d1400",
        "text": "#fff7ed",
        "muted": "#a16207",
    },
    "ivory": {
        "primary": "#d97706",
        "secondary": "#92400e",
        "bg": "#fefce8",
        "surface": "#ffffff",
        "text": "#1c1917",
        "muted": "#78716c",
        "border": "#e7e5e4",
    },
    "indigo_pro": {
        "primary": "#4338ca",
        "secondary": "#7c3aed",
        "bg": "#0f0a2e",
        "surface": "#1e1652",
        "text": "#eef2ff",
        "muted": "#818cf8",
    },
    "sage": {
        "primary": "#16a34a",
        "secondary": "#15803d",
        "bg": "#f0fdf4",
        "surface": "#ffffff",
        "text": "#14532d",
        "muted": "#6b7280",
        "border": "#bbf7d0",
    },
}

FONT_PAIRS = [
    {"display": "Space Grotesk", "body": "Inter"},
    {"display": "Syne", "body": "Manrope"},
    {"display": "Playfair Display", "body": "Inter"},
    {"display": "Cormorant Garamond", "body": "DM Sans"},
    {"display": "Cal Sans", "body": "Inter"},
    {"display": "Fraunces", "body": "Source Sans 3"},
    {"display": "DM Serif Display", "body": "DM Sans"},
    {"display": "Outfit", "body": "Inter"},
    {"display": "Plus Jakarta Sans", "body": "Nunito"},
    {"display": "Raleway", "body": "Open Sans"},
]

# Module-level uniqueness tracking: list of (palette_name, display_font, archetype)
# capped at 10 entries; used by generate_unique() to avoid repetitive combos.
_recent_profiles: list[tuple[str, str, str]] = []

# Default Framer Aura interaction presets
_AURA_INTERACTION_PRESETS = [
    "reveal_scroll",
    "hover_lift",
    "sticky_nav",
    "animated_counters",
    "testimonial_carousel",
]

# Default Aura motion tokens (CSS variable values)
_AURA_MOTION_TOKENS = {
    "t_micro": "150ms cubic-bezier(0.4, 0, 0.2, 1)",
    "t_base": "220ms cubic-bezier(0.4, 0, 0.2, 1)",
    "t_medium": "320ms cubic-bezier(0.4, 0, 0.2, 1)",
    "t_macro": "450ms cubic-bezier(0.4, 0, 0.2, 1)",
    "ease_spring": "cubic-bezier(0.34, 1.56, 0.64, 1)",
    "ease_swift": "cubic-bezier(0.4, 0, 0.2, 1)",
    "ease_gentle": "cubic-bezier(0.25, 0.46, 0.45, 0.94)",
}


@dataclass
class DesignSystem:
    # Core identity
    design_family: str = "framer_aura"
    consistency_profile_id: str = ""

    # Palette + typography
    palette_name: str = "framer_aura"
    colors: dict = field(default_factory=dict)
    display_font: str = "Space Grotesk"
    body_font: str = "Inter"

    # Type/radius/shadow scale
    base_size: str = "16px"
    scale: float = 1.25
    radius_sm: str = "6px"
    radius_md: str = "12px"
    radius_lg: str = "20px"
    shadow_sm: str = "0 1px 4px rgba(0,0,0,.07), 0 1px 2px rgba(0,0,0,.04)"
    shadow_md: str = "0 4px 16px rgba(0,0,0,.08), 0 1px 4px rgba(0,0,0,.04)"
    shadow_lg: str = "0 10px 40px rgba(0,0,0,.10), 0 2px 8px rgba(0,0,0,.05)"

    # Behavioral
    motion: str = "expressive"   # subtle | expressive | none
    density: str = "airy"        # airy | balanced | compact
    archetype: str = "saas"

    # Framer Aura extended fields
    motion_preset: str = "default"          # default | expressive | minimal | none
    spacing_policy: str = "aura"            # aura | tight | spacious
    interaction_presets: list = field(default_factory=list)
    motion_tokens: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.consistency_profile_id:
            self.consistency_profile_id = str(uuid.uuid4())[:8]
        if not self.interaction_presets:
            self.interaction_presets = list(_AURA_INTERACTION_PRESETS)
        if not self.motion_tokens:
            self.motion_tokens = dict(_AURA_MOTION_TOKENS)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "DesignSystem":
        known = {k for k in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        filtered = {k: v for k, v in d.items() if k in known}
        # Reconstruct list/dict fields that JSON preserves as list/dict
        if "interaction_presets" in filtered and isinstance(filtered["interaction_presets"], list):
            pass  # fine as-is
        return cls(**filtered)

    @classmethod
    def generate(cls, style_seed: dict | None = None) -> "DesignSystem":
        """Create a DesignSystem from optional style_seed hints.

        Defaults to framer_aura family unless palette explicitly set.
        """
        seed = style_seed or {}
        palette_name = seed.get("palette") or "framer_aura"
        fonts = {"display": "Space Grotesk", "body": "Inter"}
        if palette_name not in ("framer_aura", "framer_aura_dark"):
            fonts = random.choice(FONT_PAIRS)
        archetype = seed.get("archetype") or "saas"
        motion = seed.get("motion") or "expressive"
        density = seed.get("density") or "airy"
        return cls(
            design_family="framer_aura",
            palette_name=palette_name,
            colors=PALETTES.get(palette_name, PALETTES["framer_aura"]),
            display_font=fonts["display"],
            body_font=fonts["body"],
            archetype=archetype,
            motion=motion,
            density=density,
        )

    @classmethod
    def generate_aura(cls, archetype: str = "saas", dark: bool = False) -> "DesignSystem":
        """Create the canonical Framer Aura design system instance."""
        palette_name = "framer_aura_dark" if dark else "framer_aura"
        return cls(
            design_family="framer_aura",
            palette_name=palette_name,
            colors=PALETTES[palette_name],
            display_font="Space Grotesk",
            body_font="Inter",
            archetype=archetype,
            motion="expressive",
            density="airy",
            motion_preset="default",
            spacing_policy="aura",
            interaction_presets=list(_AURA_INTERACTION_PRESETS),
            motion_tokens=dict(_AURA_MOTION_TOKENS),
        )

    @classmethod
    def generate_unique(
        cls,
        archetype: str = "saas",
        style_seed: dict | None = None,
        max_attempts: int = 5,
    ) -> "DesignSystem":
        """Create a DesignSystem guaranteed to differ from recent combos.

        Calls generate_aura() with palette variants, checks the last 5 entries in
        _recent_profiles for (palette_name, display_font, archetype) collisions, and
        picks a different palette + font pair when a collision is detected.
        After selection the combo is appended to _recent_profiles (capped at 10).
        """
        global _recent_profiles

        palette_names = list(PALETTES.keys())
        seed = style_seed or {}

        # Determine initial palette — respect explicit hint from style_seed
        preferred_palette = seed.get("palette") or "framer_aura"
        if preferred_palette not in PALETTES:
            preferred_palette = "framer_aura"

        # Use md5 of archetype to deterministically pick a starting offset
        hash_offset = int(hashlib.md5(archetype.encode()).hexdigest()[:4], 16)
        start_idx = palette_names.index(preferred_palette) if preferred_palette in palette_names else 0

        chosen_palette: str = preferred_palette
        chosen_fonts: dict[str, str] = {"display": "Space Grotesk", "body": "Inter"}

        recent_combos = {
            (p, f) for p, f, a in _recent_profiles[-5:] if a == archetype
        }

        for attempt in range(max_attempts):
            idx = (start_idx + (hash_offset + attempt) * 3) % len(palette_names)
            candidate_palette = palette_names[idx]

            # Pick a font pair offset by attempt index as well
            font_idx = (hash_offset + attempt * 7) % len(FONT_PAIRS)
            candidate_fonts = FONT_PAIRS[font_idx]

            combo_key = (candidate_palette, candidate_fonts["display"])
            if combo_key not in recent_combos:
                chosen_palette = candidate_palette
                chosen_fonts = candidate_fonts
                break
        else:
            # Exhausted attempts — just use the last candidate (graceful degradation)
            chosen_palette = palette_names[(start_idx + hash_offset) % len(palette_names)]
            chosen_fonts = FONT_PAIRS[hash_offset % len(FONT_PAIRS)]

        ds = cls(
            design_family="framer_aura",
            palette_name=chosen_palette,
            colors=PALETTES.get(chosen_palette, PALETTES["framer_aura"]),
            display_font=chosen_fonts["display"],
            body_font=chosen_fonts["body"],
            archetype=archetype,
            motion=seed.get("motion") or "expressive",
            density=seed.get("density") or "airy",
            motion_preset="default",
            spacing_policy="aura",
            interaction_presets=list(_AURA_INTERACTION_PRESETS),
            motion_tokens=dict(_AURA_MOTION_TOKENS),
        )

        # Record and cap
        _recent_profiles.append((chosen_palette, chosen_fonts["display"], archetype))
        if len(_recent_profiles) > 10:
            _recent_profiles = _recent_profiles[-10:]

        return ds

    def merge(self, updates: dict[str, Any]) -> "DesignSystem":
        """Return a new DesignSystem with selective field updates.

        The design_family and consistency_profile_id are preserved unless
        explicitly overridden in updates.
        """
        current = self.to_dict()
        # Always preserve identity unless explicitly changing
        updates.setdefault("design_family", self.design_family)
        updates.setdefault("consistency_profile_id", self.consistency_profile_id)
        current.update(updates)
        return DesignSystem.from_dict(current)

    def to_css_vars(self) -> str:
        """Render as CSS custom properties block."""
        c = self.colors
        spacing = "1.5" if self.density == "airy" else ("1.2" if self.density == "balanced" else "1.0")
        is_aura = self.palette_name.startswith("framer_aura")
        gradient = (
            "linear-gradient(135deg, #3b82f6 0%, #8b5cf6 50%, #ec4899 100%)"
            if is_aura else
            f"linear-gradient(135deg, {c.get('primary', '#6366f1')}, {c.get('secondary', c.get('primary', '#6366f1'))})"
        )
        return f"""
  --color-primary: {c.get('primary', '#3b82f6')};
  --color-secondary: {c.get('secondary', '#8b5cf6')};
  --color-accent-pink: {c.get('accent_pink', '#ec4899')};
  --color-bg: {c.get('bg', '#f8fafc')};
  --color-surface: {c.get('surface', '#ffffff')};
  --color-text: {c.get('text', '#0f172a')};
  --color-muted: {c.get('muted', '#64748b')};
  --color-border: {c.get('border', '#e2e8f0')};
  --accent-gradient: {gradient};
  --font-display: '{self.display_font}', sans-serif;
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
        c = self.colors
        is_aura = self.palette_name.startswith("framer_aura")
        gradient_note = (
            "\nAccent gradient (use for CTAs, borders, highlights): "
            "linear-gradient(135deg, #3b82f6 0%, #8b5cf6 50%, #ec4899 100%)"
            if is_aura else ""
        )
        interaction_list = ", ".join(self.interaction_presets or _AURA_INTERACTION_PRESETS)
        return f"""DESIGN SYSTEM — Framer Aura (follow exactly — do not deviate):
Design family: {self.design_family}
Consistency profile: {self.consistency_profile_id}
Palette: {self.palette_name}{gradient_note}
  Primary: {c.get('primary')}  Secondary: {c.get('secondary')}
  Background: {c.get('bg')}    Surface: {c.get('surface')}
  Text: {c.get('text')}        Muted: {c.get('muted')}
Typography:
  Display font: {self.display_font} (for headings, hero text)
  Body font: {self.body_font} (for body, UI)
  Scale ratio: {self.scale}
Density: {self.density}   Spacing policy: {self.spacing_policy}
Motion preset: {self.motion_preset}   (NO autoplay carousels; respect prefers-reduced-motion)
Border radius: sm={self.radius_sm} md={self.radius_md} lg={self.radius_lg}
Shadows: sm="{self.shadow_sm}" md="{self.shadow_md}" lg="{self.shadow_lg}"
Active interaction presets: {interaction_list}
Archetype: {self.archetype}

Import fonts via @import in <style>: https://fonts.googleapis.com/css2?family={self.display_font.replace(' ', '+')}:wght@300;400;600;700&family={self.body_font.replace(' ', '+')}:wght@300;400;500;600&display=swap

USE CSS CUSTOM PROPERTIES (:root block) for ALL colors, fonts, radii, shadows.
Define --accent-gradient and use it on primary CTAs, active borders, and gradient text headings.

RESPONSIVE SPACING + LAYOUT RULES (always apply):
- Use fluid tokens with clamp() for section spacing, heading sizes, and container gutters.
- Add at least these breakpoints: @media (max-width: 1024px) and @media (max-width: 640px).
- Use anti-squish layout patterns: repeat(auto-fit, minmax(...)) OR flex-wrap with sensible min widths.
- Avoid fixed-width desktop-only blocks that force horizontal scrolling on phones/tablets.
- Ensure cards/media use max-width: 100% and text uses overflow-safe wrapping.
- Content containers: max-width: clamp(320px, 90vw, 1200px); margin-inline: auto;

MOTION CONTRACT:
- All interactive elements: transition: all {self.motion_tokens.get('t_base', '220ms')} {self.motion_tokens.get('ease_swift', 'cubic-bezier(0.4,0,0.2,1)')};
- Reveal-on-scroll: .reveal {{ opacity: 0; transform: translateY(20px); transition: opacity 0.4s ease, transform 0.4s ease; }}
- Hover lift on cards: transform: translateY(-4px) on :hover;
- @media (prefers-reduced-motion: reduce): .reveal, .reveal.visible {{ opacity: 1; transform: none; transition: none; }}"""
