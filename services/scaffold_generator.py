"""
Scaffold generator — builds a complete React app from a user prompt in one LLM call.

Returns:
    (changes: list[FileChange], meta: dict)

Generated files:
    index.html       — self-contained preview (React 18 CDN + Babel standalone inline)
    package.json     — project metadata
    src/main.jsx     — entry point
    src/App.jsx      — root component
    src/index.css    — global styles + CSS variables
    src/App.css      — app-level styles
    src/components/{Name}/{Name}.jsx  (3–5 focused components)
    src/components/{Name}/{Name}.css  (optional per-component styles)

The index.html is fully self-contained: all component code lives in one
<script type="text/babel"> block so it renders in any browser with internet
access — no build step required.  The src/ files are the "source" view
shown in the code editor.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LLM system prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an expert React developer and app scaffolder.

Given a user request, generate a complete, working React app.
Return ONLY a valid JSON object — no markdown fences, no prose.

Required JSON structure:
{
  "app_name": "string",
  "description": "string",
  "assistant_message": "1-2 sentences describing what was built",
  "files": {
    "index.html": "...",
    "package.json": "...",
    "src/main.jsx": "...",
    "src/App.jsx": "...",
    "src/index.css": "...",
    "src/App.css": "...",
    "src/components/ComponentA/ComponentA.jsx": "...",
    "src/components/ComponentA/ComponentA.css": "...",
    ... (3-5 component pairs)
  }
}

═══ RULES FOR index.html ═══════════════════════════════════════════════════
This file IS the live preview. It must be 100% self-contained.

Required <head> scripts (in this order):
  <script crossorigin src="https://unpkg.com/react@18/umd/react.development.js"></script>
  <script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.development.js"></script>
  <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>

Required structure:
  • <meta name="viewport" content="width=device-width, initial-scale=1.0">
  • All CSS in <style> blocks in <head> — use CSS custom properties (--primary, --bg, etc.)
  • ONE <script type="text/babel"> block containing ALL component code
  • First line of that script: const { useState, useEffect, useCallback, useRef, useMemo } = React;
  • Define EVERY component as a named function inside that single script block
  • Final line: ReactDOM.createRoot(document.getElementById('root')).render(<App />);

Quality requirements:
  • Implement REAL, working functionality — no TODOs, no placeholder text
  • Beautiful, polished UI — modern design, good spacing, readable typography
  • Responsive layout using CSS grid/flexbox and relative units
  • Meaningful interactivity (state changes, user input, feedback)

═══ RULES FOR src/ files ════════════════════════════════════════════════════
These files show project structure in the code editor.

src/main.jsx — standard Vite entry point:
  import React from 'react';
  import ReactDOM from 'react-dom/client';
  import App from './App.jsx';
  import './index.css';
  ReactDOM.createRoot(document.getElementById('root')).render(<React.StrictMode><App /></React.StrictMode>);

src/App.jsx — root component:
  • Proper ES module syntax: import React from 'react'; ... export default function App() { ... }
  • Imports sub-components from ./components/
  • Manages top-level state

src/index.css — global base:
  • CSS reset (box-sizing, margin, padding)
  • :root with CSS custom properties for colors, fonts, radii, shadows
  • body base styles

src/App.css — app-level layout styles

src/components/{Name}/{Name}.jsx:
  • 3-5 single-responsibility components
  • Proper imports/exports
  • Real props and logic
  • No placeholder content

package.json — valid JSON with:
  {"name": "...", "version": "0.1.0", "private": true,
   "dependencies": {"react": "^18.3.1", "react-dom": "^18.3.1"},
   "devDependencies": {"vite": "^5.3.4", "@vitejs/plugin-react": "^4.3.1"},
   "scripts": {"dev": "vite", "build": "vite build", "preview": "vite preview"}}

═══ COMPONENT DESIGN RULES ═════════════════════════════════════════════════
• Each component handles ONE thing clearly (Display, ButtonGrid, Sidebar, etc.)
• Use realistic data structures — no "Item 1", "Value 2" labels
• CSS: scoped class names (.calculator-display vs just .display)
• Animations/transitions welcome but keep them subtle
• Mobile-first: stack on small screens, expand on larger ones
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_scaffold(
    slug: str,
    message: str,
    existing_files: dict[str, str] | None = None,
) -> tuple[list, dict[str, Any]]:
    """Generate a React app scaffold via a single LLM call.

    Returns:
        changes: list[FileChange]  — ready for file_persistence.save_website_files()
        meta: dict                 — app_name, description, assistant_message,
                                     file_count, provider, model_mode, fallback_used
    """
    from services.provider_router import call_llm
    from services.code_generation_service import FileChange

    app_name = slug.replace("-", " ").title()
    meta: dict[str, Any] = {
        "app_name": app_name,
        "description": "",
        "assistant_message": f"Built **{app_name}** — React app ready.",
        "file_count": 0,
        "provider": "fallback",
        "model_mode": "scaffold",
        "fallback_used": False,
    }

    # Build user prompt
    if existing_files:
        file_list = "\n".join(f"  {p}" for p in sorted(existing_files.keys())[:20])
        user_prompt = (
            f"Update the app for slug '{slug}'.\n\n"
            f"Existing project files:\n{file_list}\n\n"
            f"User request: {message}\n\n"
            "Return the complete updated scaffold JSON. "
            "Include ALL files (unchanged ones too) so the project is coherent."
        )
    else:
        user_prompt = (
            f"Build: {message}\n"
            f"App slug: {slug}\n\n"
            "Generate the complete React app scaffold JSON now."
        )

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    try:
        llm_result = call_llm(messages, max_tokens=8000)
        meta["provider"] = llm_result.provider
        meta["model_mode"] = llm_result.model_mode
        meta["fallback_used"] = llm_result.fallback_used

        if llm_result.fallback_used or not llm_result.content:
            logger.warning("scaffold_generator: LLM unavailable — using template")
            meta["fallback_used"] = True
            meta["assistant_message"] = f"Built **{app_name}** (LLM unavailable — template used)."
            changes = _fallback_scaffold(slug, message, app_name)
            meta["file_count"] = len(changes)
            return changes, meta

        data = _parse_scaffold_json(llm_result.content)
        files_dict: dict[str, str] = data.get("files") or {}

        if not files_dict or "index.html" not in files_dict:
            raise ValueError(f"LLM scaffold missing index.html (got keys: {list(files_dict.keys())[:5]})")

        meta["app_name"] = data.get("app_name") or app_name
        meta["description"] = data.get("description") or ""
        meta["assistant_message"] = (
            data.get("assistant_message")
            or f"Built **{meta['app_name']}** — {len(files_dict)} files created."
        )

        changes = _build_file_changes(slug, files_dict)
        meta["file_count"] = len(changes)
        logger.info("scaffold_generator: generated %d files for %s", len(changes), slug)
        return changes, meta

    except Exception as exc:
        logger.warning("scaffold_generator: error generating scaffold — %s", exc)
        meta["fallback_used"] = True
        meta["assistant_message"] = f"Built **{app_name}** (template — generation error)."
        changes = _fallback_scaffold(slug, message, app_name)
        meta["file_count"] = len(changes)
        return changes, meta


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_scaffold_json(content: str) -> dict:
    """Extract and parse the JSON blob from LLM output."""
    content = content.strip()

    # Strip markdown code fences if present
    content = re.sub(r'^```(?:json)?\s*\n?', '', content, flags=re.MULTILINE)
    content = re.sub(r'\n?```\s*$', '', content, flags=re.MULTILINE)
    content = content.strip()

    # Direct parse
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # Find outermost JSON object by matching braces
    start = content.find('{')
    if start != -1:
        depth = 0
        for i, ch in enumerate(content[start:], start):
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(content[start:i + 1])
                    except json.JSONDecodeError:
                        break

    raise ValueError(f"Cannot parse JSON from LLM response (first 300 chars): {content[:300]!r}")


def _build_file_changes(slug: str, files_dict: dict[str, str]) -> list:
    """Convert {rel_path: content} to list[FileChange]."""
    from services.code_generation_service import FileChange

    changes = []
    for rel_path, content in files_dict.items():
        if not rel_path or not isinstance(content, str) or not content.strip():
            continue
        full_path = f"data/websites/{slug}/{rel_path}"
        changes.append(FileChange(
            path=full_path,
            action="create",
            content=content,
            summary=f"Generated {rel_path}",
        ))
    return changes


# ---------------------------------------------------------------------------
# Fallback scaffold (template-based, no LLM required)
# ---------------------------------------------------------------------------

def _fallback_scaffold(slug: str, message: str, app_name: str) -> list:
    """Minimal but working React scaffold when LLM is unavailable."""
    from services.code_generation_service import FileChange

    safe_msg = message[:120].replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;')

    index_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{app_name}</title>
  <script crossorigin src="https://unpkg.com/react@18/umd/react.development.js"></script>
  <script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.development.js"></script>
  <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    :root {{
      --bg: #0f172a; --surface: #1e293b; --border: #334155;
      --text: #f1f5f9; --muted: #94a3b8; --accent: #6366f1; --accent-hover: #4f46e5;
      --radius: 12px; --font: system-ui, -apple-system, sans-serif;
    }}
    body {{ font-family: var(--font); background: var(--bg); color: var(--text); min-height: 100vh; }}
    .app {{
      display: flex; flex-direction: column; align-items: center;
      justify-content: center; min-height: 100vh; gap: 1.5rem; padding: 2rem;
    }}
    h1 {{ font-size: clamp(2rem, 6vw, 3.5rem); font-weight: 800; letter-spacing: -0.02em; }}
    h1 span {{ color: var(--accent); }}
    p {{ color: var(--muted); max-width: 42ch; text-align: center; line-height: 1.6; font-size: 1.1rem; }}
    .btn {{
      padding: 0.75rem 2rem; border-radius: var(--radius); border: none; cursor: pointer;
      font-size: 1rem; font-weight: 600; font-family: var(--font);
      background: var(--accent); color: #fff; transition: background 150ms;
    }}
    .btn:hover {{ background: var(--accent-hover); }}
  </style>
</head>
<body>
  <div id="root"></div>
  <script type="text/babel">
    const {{ useState }} = React;

    function App() {{
      const [started, setStarted] = useState(false);
      return (
        <div className="app">
          <h1>{{!started ? <><span>{app_name}</span></> : "Let's go!"}}</h1>
          <p>{{started ? "App is loading…" : "{safe_msg}"}}</p>
          {{!started && (
            <button className="btn" onClick={{() => setStarted(true)}}>
              Get Started
            </button>
          )}}
        </div>
      );
    }}

    ReactDOM.createRoot(document.getElementById('root')).render(<App />);
  </script>
</body>
</html>"""

    pkg = json.dumps({
        "name": slug,
        "version": "0.1.0",
        "private": True,
        "dependencies": {"react": "^18.3.1", "react-dom": "^18.3.1"},
        "devDependencies": {
            "vite": "^5.3.4",
            "@vitejs/plugin-react": "^4.3.1",
            "@types/react": "^18.3.3",
            "@types/react-dom": "^18.3.0",
        },
        "scripts": {
            "dev": "vite",
            "build": "vite build",
            "preview": "vite preview",
        },
    }, indent=2)

    src_main = """\
import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App.jsx';
import './index.css';

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
"""

    src_app = f"""\
import React, {{ useState }} from 'react';
import './App.css';

export default function App() {{
  const [started, setStarted] = useState(false);

  return (
    <div className="app">
      <h1 className="app-title">{app_name}</h1>
      <p className="app-desc">{safe_msg}</p>
      {{!started && (
        <button className="btn" onClick={{() => setStarted(true)}}>
          Get Started
        </button>
      )}}
    </div>
  );
}}
"""

    src_index_css = """\
*, *::before, *::after {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

:root {
  --bg: #0f172a;
  --surface: #1e293b;
  --border: #334155;
  --text: #f1f5f9;
  --muted: #94a3b8;
  --accent: #6366f1;
  --accent-hover: #4f46e5;
  --radius: 12px;
  --font: system-ui, -apple-system, sans-serif;
}

body {
  font-family: var(--font);
  background: var(--bg);
  color: var(--text);
  min-height: 100vh;
  -webkit-font-smoothing: antialiased;
}
"""

    src_app_css = """\
.app {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  gap: 1.5rem;
  padding: 2rem;
}

.app-title {
  font-size: clamp(2rem, 6vw, 3.5rem);
  font-weight: 800;
  letter-spacing: -0.02em;
  color: var(--accent);
}

.app-desc {
  color: var(--muted);
  max-width: 42ch;
  text-align: center;
  line-height: 1.6;
  font-size: 1.1rem;
}

.btn {
  padding: 0.75rem 2rem;
  border-radius: var(--radius);
  border: none;
  cursor: pointer;
  font-size: 1rem;
  font-weight: 600;
  font-family: var(--font);
  background: var(--accent);
  color: #fff;
  transition: background 150ms;
}

.btn:hover {
  background: var(--accent-hover);
}
"""

    return [
        FileChange(
            path=f"data/websites/{slug}/index.html",
            action="create", content=index_html, summary="App preview (self-contained React)",
        ),
        FileChange(
            path=f"data/websites/{slug}/package.json",
            action="create", content=pkg, summary="Project configuration",
        ),
        FileChange(
            path=f"data/websites/{slug}/src/main.jsx",
            action="create", content=src_main, summary="React entry point",
        ),
        FileChange(
            path=f"data/websites/{slug}/src/App.jsx",
            action="create", content=src_app, summary="Root component",
        ),
        FileChange(
            path=f"data/websites/{slug}/src/index.css",
            action="create", content=src_index_css, summary="Global styles",
        ),
        FileChange(
            path=f"data/websites/{slug}/src/App.css",
            action="create", content=src_app_css, summary="App component styles",
        ),
    ]
