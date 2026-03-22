"""
Site spec schema — the structured JSON contract between LLM and renderer.

The spec is the single source of truth for a website.  All edits mutate
the spec; all rendering reads from it.  HTML is a derived artifact.

Pipeline:  User Prompt → LLM (JSON only) → validate_spec() → render()
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from config.settings import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Section prop schemas
# ---------------------------------------------------------------------------

class HeroProps(BaseModel):
    headline: str = "Welcome"
    subheadline: str = ""
    ctaText: str = "Get Started"
    ctaHref: str = "pages/signup.html"
    secondaryCtaText: str = ""
    secondaryCtaHref: str = ""

class FeatureItem(BaseModel):
    icon: str = ""
    title: str = ""
    description: str = ""

class FeaturesProps(BaseModel):
    heading: str = "Features"
    subheading: str = ""
    items: list[FeatureItem] = Field(default_factory=list)

class CtaProps(BaseModel):
    heading: str = ""
    description: str = ""
    buttonText: str = "Get Started"
    buttonHref: str = "pages/signup.html"

class TestimonialItem(BaseModel):
    name: str = ""
    role: str = ""
    quote: str = ""

class TestimonialsProps(BaseModel):
    heading: str = "What people say"
    items: list[TestimonialItem] = Field(default_factory=list)

class PricingTier(BaseModel):
    name: str = ""
    price: str = "$0"
    period: str = "/mo"
    description: str = ""
    features: list[str] = Field(default_factory=list)
    ctaText: str = "Choose Plan"
    highlighted: bool = False

class PricingProps(BaseModel):
    heading: str = "Pricing"
    subheading: str = ""
    tiers: list[PricingTier] = Field(default_factory=list)

class FaqItem(BaseModel):
    question: str = ""
    answer: str = ""

class FaqProps(BaseModel):
    heading: str = "FAQ"
    items: list[FaqItem] = Field(default_factory=list)

class FooterProps(BaseModel):
    brand: str = ""
    tagline: str = ""
    links: list[dict[str, str]] = Field(default_factory=list)
    copyright: str = ""

class StatsItem(BaseModel):
    value: str = ""
    label: str = ""

class StatsProps(BaseModel):
    heading: str = ""
    items: list[StatsItem] = Field(default_factory=list)

class HowItWorksStep(BaseModel):
    step: int = 1
    title: str = ""
    description: str = ""

class HowItWorksProps(BaseModel):
    heading: str = "How it works"
    steps: list[HowItWorksStep] = Field(default_factory=list)

# ---------------------------------------------------------------------------
# Section model (discriminated by type)
# ---------------------------------------------------------------------------

SECTION_TYPES = {"hero", "features", "cta", "testimonials", "pricing", "faq", "footer", "stats", "how_it_works"}

SECTION_PROP_MAP: dict[str, type[BaseModel]] = {
    "hero": HeroProps,
    "features": FeaturesProps,
    "cta": CtaProps,
    "testimonials": TestimonialsProps,
    "pricing": PricingProps,
    "faq": FaqProps,
    "footer": FooterProps,
    "stats": StatsProps,
    "how_it_works": HowItWorksProps,
}

class Section(BaseModel):
    type: str
    props: dict[str, Any] = Field(default_factory=dict)

    @field_validator("type")
    @classmethod
    def type_must_be_known(cls, v: str) -> str:
        if v not in SECTION_TYPES:
            raise ValueError(f"Unknown section type: {v!r}")
        return v

# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------

class NavLink(BaseModel):
    label: str
    href: str

class NavCtaButton(BaseModel):
    label: str = "Get Started"
    href: str = "pages/signup.html"

class Navigation(BaseModel):
    links: list[NavLink] = Field(default_factory=list)
    ctaButton: NavCtaButton = Field(default_factory=NavCtaButton)

# ---------------------------------------------------------------------------
# Auth page props
# ---------------------------------------------------------------------------

class AuthPageProps(BaseModel):
    formType: str = "signup"
    heading: str = "Create your account"
    fields: list[str] = Field(default_factory=lambda: ["name", "email", "password"])
    submitText: str = "Get Started"
    altLinkText: str = "Already have an account? Sign in"
    altLinkHref: str = "../index.html"

# ---------------------------------------------------------------------------
# Dashboard page props
# ---------------------------------------------------------------------------

class DashboardMetric(BaseModel):
    label: str = ""
    value: str = "0"
    icon: str = ""

class DashboardSidebarLink(BaseModel):
    label: str = ""
    href: str = "#"
    icon: str = ""

class DashboardPageProps(BaseModel):
    welcomeHeading: str = "Welcome"
    metrics: list[DashboardMetric] = Field(default_factory=list)
    sidebarLinks: list[DashboardSidebarLink] = Field(default_factory=list)

# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

class Page(BaseModel):
    path: str
    title: str = ""
    type: Literal["landing", "auth", "dashboard", "content"] = "landing"
    sections: list[Section] = Field(default_factory=list)
    props: dict[str, Any] = Field(default_factory=dict)

# ---------------------------------------------------------------------------
# Site-level design tokens
# ---------------------------------------------------------------------------

class SiteDesign(BaseModel):
    title: str = "My Website"
    description: str = ""
    theme: Literal["light", "dark"] = "light"
    primaryColor: str = "#3b82f6"
    secondaryColor: str = "#8b5cf6"
    accentColor: str = "#ec4899"
    bgColor: str = "#f8fafc"
    surfaceColor: str = "#ffffff"
    textColor: str = "#0f172a"
    mutedColor: str = "#64748b"
    borderColor: str = "#e2e8f0"
    displayFont: str = "Space Grotesk"
    bodyFont: str = "Inter"
    logoText: str = ""

# ---------------------------------------------------------------------------
# Top-level SiteSpec
# ---------------------------------------------------------------------------

class SiteSpec(BaseModel):
    site: SiteDesign = Field(default_factory=SiteDesign)
    navigation: Navigation = Field(default_factory=Navigation)
    pages: list[Page] = Field(default_factory=list)

# ---------------------------------------------------------------------------
# Validation + normalization
# ---------------------------------------------------------------------------

_REQUIRED_SECTION_TYPES = {"hero", "features", "cta"}

_DARK_PALETTE = {
    "bgColor": "#0f172a",
    "surfaceColor": "#1e293b",
    "textColor": "#f8fafc",
    "mutedColor": "#94a3b8",
    "borderColor": "#334155",
}
_LIGHT_PALETTE = {
    "bgColor": "#f8fafc",
    "surfaceColor": "#ffffff",
    "textColor": "#0f172a",
    "mutedColor": "#64748b",
    "borderColor": "#e2e8f0",
}


def validate_spec(raw: dict[str, Any]) -> SiteSpec:
    """Parse, validate, and normalise a raw JSON dict into a SiteSpec.

    - Fills missing required sections with defaults
    - Removes unknown section types
    - Enforces theme-consistent colors
    - Ensures at least one page exists
    """
    raw = _normalise_raw(raw)
    spec = SiteSpec.model_validate(raw)
    spec = _enforce_constraints(spec)
    return spec


def _normalise_raw(raw: dict[str, Any]) -> dict[str, Any]:
    """Pre-process raw LLM output before Pydantic validation."""
    if not isinstance(raw, dict):
        raw = {}

    # Ensure top-level keys exist
    raw.setdefault("site", {})
    raw.setdefault("navigation", {})
    raw.setdefault("pages", [])

    site = raw["site"]
    if not isinstance(site, dict):
        raw["site"] = {}
        site = raw["site"]

    # Apply theme palette if colors look like defaults or are missing
    theme = site.get("theme", "light")
    palette = _DARK_PALETTE if theme == "dark" else _LIGHT_PALETTE
    for key, default_val in palette.items():
        if not site.get(key):
            site[key] = default_val

    # Normalise pages
    pages = raw.get("pages", [])
    if not isinstance(pages, list) or len(pages) == 0:
        raw["pages"] = [{"path": "index.html", "type": "landing", "sections": []}]
    for page in raw["pages"]:
        if not isinstance(page, dict):
            continue
        page.setdefault("path", "index.html")
        page.setdefault("type", "landing")
        page.setdefault("sections", [])
        # Strip invalid sections
        page["sections"] = [
            s for s in page["sections"]
            if isinstance(s, dict) and s.get("type") in SECTION_TYPES
        ]
        for section in page["sections"]:
            section.setdefault("props", {})
            _fill_section_defaults(section)

    # Normalise navigation
    nav = raw.get("navigation", {})
    if not isinstance(nav, dict):
        raw["navigation"] = {}

    return raw


def _fill_section_defaults(section: dict) -> None:
    """Fill missing props with type-specific defaults."""
    stype = section.get("type", "")
    model_cls = SECTION_PROP_MAP.get(stype)
    if not model_cls:
        return
    try:
        validated = model_cls.model_validate(section.get("props", {}))
        section["props"] = validated.model_dump()
    except Exception:
        section["props"] = model_cls().model_dump()


def _enforce_constraints(spec: SiteSpec) -> SiteSpec:
    """Post-validation business rule enforcement."""
    # Ensure logoText is set
    if not spec.site.logoText:
        spec.site.logoText = spec.site.title

    # Ensure landing page has required sections
    for page in spec.pages:
        if page.type == "landing" and page.path in ("index.html", ""):
            existing_types = {s.type for s in page.sections}
            for req in _REQUIRED_SECTION_TYPES:
                if req not in existing_types:
                    default_props = SECTION_PROP_MAP[req]().model_dump()
                    page.sections.append(Section(type=req, props=default_props))

    # Ensure footer on landing pages
    for page in spec.pages:
        if page.type == "landing":
            if not any(s.type == "footer" for s in page.sections):
                page.sections.append(Section(
                    type="footer",
                    props=FooterProps(
                        brand=spec.site.logoText,
                        copyright=f"© 2026 {spec.site.logoText}. All rights reserved.",
                    ).model_dump(),
                ))

    # Build navigation from pages if empty
    if not spec.navigation.links:
        for page in spec.pages:
            if page.path == "index.html":
                continue
            label = page.title or page.path.replace("pages/", "").replace(".html", "").title()
            spec.navigation.links.append(NavLink(label=label, href=page.path))

    return spec


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

SPEC_FILENAME = "_spec.json"


def save_spec(slug: str, spec: SiteSpec) -> Path:
    """Write spec JSON to disk alongside the website files."""
    websites_dir = settings.resolve_websites_dir()
    spec_path = websites_dir / slug / SPEC_FILENAME
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(spec.model_dump_json(indent=2), encoding="utf-8")
    return spec_path


def load_spec(slug: str) -> Optional[SiteSpec]:
    """Load spec from disk. Returns None if not found."""
    websites_dir = settings.resolve_websites_dir()
    spec_path = websites_dir / slug / SPEC_FILENAME
    if not spec_path.exists():
        return None
    try:
        raw = json.loads(spec_path.read_text(encoding="utf-8"))
        return validate_spec(raw)
    except Exception as exc:
        logger.warning("Failed to load spec for slug=%r: %s", slug, exc)
        return None
