"""
Provider-agnostic image generation adapter.

Routing order:
  1. DALL-E 2 via OpenAI Images API (when API key is available)
  2. Deterministic SVG placeholder — always works, no API key needed

Placeholders are category-aware: palette, icons, and layout all reflect
the detected product category.
"""
from __future__ import annotations

import base64
import hashlib
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

logger = logging.getLogger(__name__)

# Category-aware palettes (mirrors tools/website_builder._category_palette)
_PALETTES: dict[str, dict[str, str]] = {
    "health":    {"bg": "#f0fdf4", "primary": "#16a34a", "secondary": "#dcfce7", "text": "#14532d"},
    "finance":   {"bg": "#eff6ff", "primary": "#2563eb", "secondary": "#dbeafe", "text": "#1e3a8a"},
    "crm":       {"bg": "#faf5ff", "primary": "#7c3aed", "secondary": "#ede9fe", "text": "#4c1d95"},
    "devtools":  {"bg": "#0f172a", "primary": "#38bdf8", "secondary": "#1e293b", "text": "#e2e8f0"},
    "edtech":    {"bg": "#fff7ed", "primary": "#ea580c", "secondary": "#ffedd5", "text": "#7c2d12"},
    "ecommerce": {"bg": "#fdf2f8", "primary": "#db2777", "secondary": "#fce7f3", "text": "#831843"},
    "saas":      {"bg": "#f8fafc", "primary": "#6366f1", "secondary": "#e0e7ff", "text": "#1e1b4b"},
}
_DEFAULT_PALETTE = _PALETTES["saas"]

_FEATURE_EMOJI: dict[str, str] = {
    "track": "📊", "calorie": "🥗", "workout": "💪", "health": "❤️", "diet": "🥦",
    "payment": "💳", "invoice": "🧾", "budget": "💰", "finance": "📈", "expense": "💸",
    "crm": "🤝", "contact": "👥", "lead": "🎯", "pipeline": "🔄", "prospect": "📋",
    "code": "💻", "deploy": "🚀", "monitor": "🔍", "api": "⚡", "debug": "🐛",
    "learn": "📚", "quiz": "❓", "course": "🎓", "progress": "📈", "study": "✏️",
    "shop": "🛍️", "product": "📦", "cart": "🛒", "order": "📋", "store": "🏪",
    "dashboard": "📊", "analytics": "📉", "report": "📄", "data": "🗃️", "chart": "📊",
}

# Style hints per category for DALL-E prompts
_CATEGORY_STYLE: dict[str, str] = {
    "health":    "fresh green tones, organic shapes, wellness aesthetic",
    "finance":   "clean blue tones, professional, financial charts aesthetic",
    "crm":       "warm purple tones, people-centric, business relationship aesthetic",
    "devtools":  "dark theme, neon accents, developer tools aesthetic",
    "edtech":    "warm orange tones, educational, learning platform aesthetic",
    "ecommerce": "vibrant pink tones, retail, shopping experience aesthetic",
    "saas":      "modern indigo tones, sleek, SaaS product aesthetic",
}


def _detect_category(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ["calorie", "health", "workout", "fitness", "diet", "nutrition"]): return "health"
    if any(k in t for k in ["finance", "payment", "invoice", "budget", "money", "expense"]): return "finance"
    if any(k in t for k in ["crm", "contact", "lead", "sales", "prospect", "pipeline"]): return "crm"
    if any(k in t for k in ["code", "deploy", "api", "developer", "devops", "debug"]): return "devtools"
    if any(k in t for k in ["learn", "course", "quiz", "education", "study", "tutor"]): return "edtech"
    if any(k in t for k in ["shop", "ecommerce", "product", "cart", "store", "retail"]): return "ecommerce"
    return "saas"


def _feature_emoji(text: str) -> str:
    t = text.lower()
    for kw, emoji in _FEATURE_EMOJI.items():
        if kw in t:
            return emoji
    return "✨"


# ---------------------------------------------------------------------------
# DALL-E image generation
# ---------------------------------------------------------------------------

def _dalle_available() -> bool:
    """Check if DALL-E generation can be attempted."""
    from config.settings import settings
    return bool(settings.openai_api_key and settings.image_generation_enabled)


_MAX_IMAGE_BYTES = 900_000  # compress to stay well under the 1MB pipeline limit


def _optimize_image(raw_png: bytes) -> tuple[bytes, str]:
    """Optimize an image for web delivery. Returns (bytes, extension).

    If the raw PNG is under the limit, returns it as-is with '.png'.
    Otherwise compresses to JPEG (much smaller for photographic DALL-E output).
    """
    if len(raw_png) <= _MAX_IMAGE_BYTES:
        return raw_png, ".png"

    try:
        from io import BytesIO
        from PIL import Image

        img = Image.open(BytesIO(raw_png)).convert("RGB")
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=85, optimize=True)
        compressed = buf.getvalue()
        logger.info(
            "Compressed image: %d KB PNG → %d KB JPEG",
            len(raw_png) // 1024,
            len(compressed) // 1024,
        )
        return compressed, ".jpg"
    except Exception as exc:
        logger.warning("Image compression failed, returning raw PNG: %s", exc)
        return raw_png, ".png"


def _call_dalle(prompt: str, size: str) -> tuple[bytes, str] | None:
    """Call the OpenAI Images API. Returns (image_bytes, extension) or None."""
    import httpx
    from config.settings import settings

    try:
        resp = httpx.post(
            "https://api.openai.com/v1/images/generations",
            headers={
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.dalle_model,
                "prompt": prompt,
                "n": 1,
                "size": size,
                "response_format": "b64_json",
            },
            timeout=settings.dalle_timeout,
        )
        resp.raise_for_status()
        b64_data = resp.json()["data"][0]["b64_json"]
        raw = base64.b64decode(b64_data)
        return _optimize_image(raw)
    except Exception as exc:
        logger.warning("DALL-E image generation failed: %s", exc)
        return None


def generate_hero_image(intent: dict[str, Any]) -> tuple[bytes, str] | None:
    """Generate a hero image via DALL-E 2. Returns (image_bytes, ext) or None."""
    if not _dalle_available():
        return None

    from config.settings import settings
    product_name = (intent.get("product_name") or "Product")[:60]
    tagline = (intent.get("tagline") or intent.get("raw_message") or "")[:100]
    cat = _detect_category(f"{product_name} {tagline}")
    style = _CATEGORY_STYLE.get(cat, _CATEGORY_STYLE["saas"])

    prompt = (
        f"Clean modern hero illustration for a {product_name} website. "
        f"{tagline}. Professional product hero image, "
        f"minimal flat design, soft gradients, {style}, "
        f"no text, no words, no letters, abstract shapes and patterns"
    )[:1000]

    return _call_dalle(prompt, settings.dalle_hero_size)


def generate_feature_icon_image(feature: str) -> tuple[bytes, str] | None:
    """Generate a feature icon via DALL-E 2. Returns (image_bytes, ext) or None."""
    if not _dalle_available():
        return None

    from config.settings import settings
    cat = _detect_category(feature)
    style = _CATEGORY_STYLE.get(cat, _CATEGORY_STYLE["saas"])

    prompt = (
        f"Minimal flat icon representing '{feature}'. "
        f"Simple geometric design, {style}, "
        f"single centered symbol on clean background, "
        f"no text, no words, app icon style"
    )[:1000]

    return _call_dalle(prompt, settings.dalle_icon_size)


def generate_all_images(
    intent: dict[str, Any],
) -> dict[str, bytes]:
    """Generate hero + feature icon images in parallel via DALL-E.

    Returns {asset_path: image_bytes} for successfully generated images.
    Asset paths include the correct extension based on compression outcome.
    Failures are silently skipped (caller should fill in SVG fallbacks).
    """
    if not _dalle_available():
        return {}

    results: dict[str, bytes] = {}
    features = (intent.get("core_features") or [])[:3]
    import re as _re

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures: dict = {}

        futures[pool.submit(generate_hero_image, intent)] = ("hero", None)

        for i, feature in enumerate(features):
            feature_slug = _re.sub(r'[^a-z0-9]+', '-', feature.lower()).strip('-')
            futures[pool.submit(generate_feature_icon_image, feature)] = (
                f"icon-{i + 1}",
                f"icon-{feature_slug}",
            )

        for future in as_completed(futures):
            key = futures[future]
            try:
                result = future.result()
                if result:
                    img_bytes, ext = result
                    name_primary, name_alias = key
                    results[f"assets/{name_primary}{ext}"] = img_bytes
                    if name_alias:
                        results[f"assets/{name_alias}{ext}"] = img_bytes
            except Exception as exc:
                logger.warning("Image generation future failed: %s", exc)

    return results


# ---------------------------------------------------------------------------
# SVG placeholder generators (fallback)
# ---------------------------------------------------------------------------

def generate_hero_svg(intent: dict[str, Any]) -> str:
    """Generate a hero section SVG placeholder (800×400)."""
    product_name = (intent.get("product_name") or "Product")[:24]
    tagline = (intent.get("tagline") or "The smarter way")[:48]
    cat = _detect_category(f"{product_name} {tagline}")
    p = _PALETTES.get(cat, _DEFAULT_PALETTE)

    # Deterministic variation seeded by product name
    seed = int(hashlib.md5(product_name.encode()).hexdigest()[:4], 16)
    cx1 = 580 + (seed % 60)
    cx2 = 100 + ((seed >> 4) % 40)

    escaped_name = _esc(product_name)
    escaped_tag = _esc(tagline)
    bg_text = p["bg"] if cat != "devtools" else "#0f172a"
    dark = cat == "devtools"
    label_color = "#ffffff" if dark else "#ffffff"
    hero_text_color = "#ffffff" if dark else "#1e293b"
    sub_color = "#94a3b8" if dark else "#64748b"

    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 400" width="800" height="400">
  <defs>
    <linearGradient id="hbg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:{bg_text};stop-opacity:1"/>
      <stop offset="100%" style="stop-color:{p['secondary']};stop-opacity:1"/>
    </linearGradient>
  </defs>
  <rect width="800" height="400" fill="url(#hbg)"/>
  <circle cx="{cx1}" cy="60" r="140" fill="{p['primary']}" opacity="0.07"/>
  <circle cx="720" cy="360" r="90" fill="{p['primary']}" opacity="0.05"/>
  <circle cx="{cx2}" cy="320" r="70" fill="{p['primary']}" opacity="0.06"/>
  <!-- UI card mock -->
  <rect x="470" y="70" width="280" height="260" rx="18" fill="{'#1e293b' if dark else 'white'}" opacity="0.85" filter="drop-shadow(0 8px 32px rgba(0,0,0,0.10))"/>
  <rect x="490" y="92" width="100" height="9" rx="4" fill="{p['primary']}" opacity="0.8"/>
  <rect x="490" y="112" width="240" height="5" rx="2.5" fill="{'#334155' if dark else '#e2e8f0'}"/>
  <rect x="490" y="124" width="200" height="5" rx="2.5" fill="{'#334155' if dark else '#e2e8f0'}"/>
  <rect x="490" y="144" width="240" height="72" rx="10" fill="{p['secondary']}" opacity="{'0.3' if dark else '0.55'}"/>
  <rect x="508" y="160" width="80" height="6" rx="3" fill="{p['primary']}" opacity="0.6"/>
  <rect x="508" y="174" width="140" height="5" rx="2.5" fill="{'#475569' if dark else '#cbd5e1'}"/>
  <rect x="508" y="185" width="100" height="5" rx="2.5" fill="{'#475569' if dark else '#cbd5e1'}"/>
  <rect x="490" y="228" width="120" height="9" rx="4" fill="{'#334155' if dark else '#e2e8f0'}"/>
  <rect x="490" y="244" width="160" height="9" rx="4" fill="{'#334155' if dark else '#e2e8f0'}"/>
  <rect x="490" y="272" width="96" height="32" rx="10" fill="{p['primary']}"/>
  <text x="538" y="293" font-family="system-ui,sans-serif" font-size="12" font-weight="600" fill="{label_color}" text-anchor="middle">Start free</text>
  <!-- Hero text -->
  <text x="50" y="170" font-family="system-ui,-apple-system,sans-serif" font-size="38" font-weight="800" fill="{hero_text_color}">{escaped_name}</text>
  <text x="50" y="202" font-family="system-ui,sans-serif" font-size="15" fill="{sub_color}">{escaped_tag}</text>
  <rect x="50" y="224" width="148" height="40" rx="12" fill="{p['primary']}"/>
  <text x="124" y="249" font-family="system-ui,sans-serif" font-size="14" font-weight="600" fill="white" text-anchor="middle">Get Started →</text>
  <rect x="208" y="224" width="120" height="40" rx="12" fill="{'rgba(255,255,255,0.08)' if dark else 'rgba(0,0,0,0.04)'}" stroke="{'rgba(255,255,255,0.15)' if dark else 'rgba(0,0,0,0.10)'}" stroke-width="1"/>
  <text x="268" y="249" font-family="system-ui,sans-serif" font-size="14" fill="{sub_color}" text-anchor="middle">See demo</text>
</svg>'''


def generate_feature_icon_svg(feature: str) -> str:
    """Generate a 64×64 feature icon SVG."""
    emoji = _feature_emoji(feature)
    cat = _detect_category(feature)
    p = _PALETTES.get(cat, _DEFAULT_PALETTE)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64">'
        f'<rect width="64" height="64" rx="16" fill="{p["secondary"]}"/>'
        f'<text x="32" y="44" font-size="28" text-anchor="middle">{emoji}</text>'
        f'</svg>'
    )


def _esc(text: str) -> str:
    """XML-escape for SVG text content."""
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
    )
