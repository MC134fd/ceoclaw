"""
Agent capability registry for future autonomous agents.

Each AgentCapability describes one discrete action an agent may take.
The registry is consumed by:
  - The agent planner (to enumerate available actions)
  - The UI (to surface what the agent can do to the user)
  - The safety layer (to enforce confirmation requirements)

Scope boundaries:
  workspace  — reads/writes inside the project slug directory only
  session    — reads/writes session state (chat history, versions, design system)
  global_read — read-only access to shared config / templates (no writes)

Future extension:
  - Add capabilities for Stripe integration, external API calls, GitHub push, etc.
  - Each new capability must declare its scope_boundary and requires_confirmation.
  - Network-touching capabilities must declare external_services.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Data contracts
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AgentCapability:
    """A single operation an agent is permitted to perform."""
    name: str                        # machine-readable identifier, e.g. "edit_file"
    description: str                 # human-readable one-liner shown in UI
    parameters: tuple[str, ...]      # required parameter names
    scope_boundary: str              # "workspace" | "session" | "global_read"
    requires_confirmation: bool      # must the user approve before execution?
    destructive: bool = False        # does this overwrite/delete existing data?
    external_services: tuple[str, ...] = ()  # e.g. ("stripe", "github")
    enabled: bool = True             # can be toggled off without removing the definition


@dataclass
class CapabilityRegistry:
    """
    Registry of all declared agent capabilities.

    Usage:
        registry = CapabilityRegistry.default()
        cap = registry.get("edit_file")
        safe = registry.list_by_scope("workspace")
        needs_confirm = registry.list_requiring_confirmation()
    """
    _capabilities: dict[str, AgentCapability] = field(default_factory=dict)

    @classmethod
    def default(cls) -> "CapabilityRegistry":
        """Build the registry with all currently-defined capabilities."""
        r = cls()
        for cap in _DEFAULT_CAPABILITIES:
            r._capabilities[cap.name] = cap
        return r

    def get(self, name: str) -> Optional[AgentCapability]:
        return self._capabilities.get(name)

    def all(self) -> list[AgentCapability]:
        return list(self._capabilities.values())

    def list_enabled(self) -> list[AgentCapability]:
        return [c for c in self._capabilities.values() if c.enabled]

    def list_by_scope(self, scope: str) -> list[AgentCapability]:
        return [c for c in self.list_enabled() if c.scope_boundary == scope]

    def list_requiring_confirmation(self) -> list[AgentCapability]:
        return [c for c in self.list_enabled() if c.requires_confirmation]

    def list_destructive(self) -> list[AgentCapability]:
        return [c for c in self.list_enabled() if c.destructive]

    def to_prompt_block(self) -> str:
        """Format enabled capabilities as an LLM-readable list for agent planning prompts."""
        lines = ["AVAILABLE AGENT CAPABILITIES:"]
        for cap in self.list_enabled():
            confirm_tag = " [requires confirmation]" if cap.requires_confirmation else ""
            lines.append(
                f"  - {cap.name}: {cap.description}{confirm_tag}"
                f" (scope={cap.scope_boundary})"
            )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Default capability definitions
# ---------------------------------------------------------------------------

_DEFAULT_CAPABILITIES: list[AgentCapability] = [
    # ── Workspace file operations ──────────────────────────────────────────
    AgentCapability(
        name="read_file",
        description="Read a file from the project workspace",
        parameters=("slug", "relative_path"),
        scope_boundary="workspace",
        requires_confirmation=False,
    ),
    AgentCapability(
        name="write_file",
        description="Write or update a file in the project workspace",
        parameters=("slug", "relative_path", "content"),
        scope_boundary="workspace",
        requires_confirmation=False,
        destructive=True,
    ),
    AgentCapability(
        name="list_files",
        description="List all files in the project workspace",
        parameters=("slug",),
        scope_boundary="workspace",
        requires_confirmation=False,
    ),
    AgentCapability(
        name="delete_file",
        description="Delete a file from the project workspace",
        parameters=("slug", "relative_path"),
        scope_boundary="workspace",
        requires_confirmation=True,
        destructive=True,
    ),
    AgentCapability(
        name="diff_files",
        description="Compare two versions of a workspace file",
        parameters=("slug", "relative_path", "version_id_a", "version_id_b"),
        scope_boundary="workspace",
        requires_confirmation=False,
    ),

    # ── Code generation ────────────────────────────────────────────────────
    AgentCapability(
        name="generate_page",
        description="Generate a new HTML page and add it to the workspace",
        parameters=("slug", "page_name", "description"),
        scope_boundary="workspace",
        requires_confirmation=False,
    ),
    AgentCapability(
        name="edit_section",
        description="Edit a specific section of an existing page",
        parameters=("slug", "relative_path", "section", "instruction"),
        scope_boundary="workspace",
        requires_confirmation=False,
        destructive=True,
    ),
    AgentCapability(
        name="apply_design_system",
        description="Apply a design system palette to all workspace HTML files",
        parameters=("slug", "design_system"),
        scope_boundary="workspace",
        requires_confirmation=True,
        destructive=True,
    ),

    # ── Session / version management ───────────────────────────────────────
    AgentCapability(
        name="save_version",
        description="Snapshot the current workspace as a named version",
        parameters=("session_id", "slug", "label"),
        scope_boundary="session",
        requires_confirmation=False,
    ),
    AgentCapability(
        name="restore_version",
        description="Restore a previous workspace snapshot",
        parameters=("session_id", "version_id"),
        scope_boundary="session",
        requires_confirmation=True,
        destructive=True,
    ),
    AgentCapability(
        name="list_versions",
        description="List all saved versions for a session",
        parameters=("session_id",),
        scope_boundary="session",
        requires_confirmation=False,
    ),

    # ── Validation & analysis ──────────────────────────────────────────────
    AgentCapability(
        name="validate_html",
        description="Validate HTML accessibility and structure without modifying files",
        parameters=("slug", "relative_path"),
        scope_boundary="workspace",
        requires_confirmation=False,
    ),
    AgentCapability(
        name="run_lighthouse_audit",
        description="Run a Lighthouse-style audit on a workspace page (read-only)",
        parameters=("slug", "relative_path"),
        scope_boundary="workspace",
        requires_confirmation=False,
    ),

    # ── External integrations (future, currently disabled) ─────────────────
    AgentCapability(
        name="push_to_github",
        description="Push the workspace to a GitHub repository",
        parameters=("slug", "repo_url", "branch"),
        scope_boundary="workspace",
        requires_confirmation=True,
        external_services=("github",),
        enabled=False,   # not yet implemented
    ),
    AgentCapability(
        name="connect_stripe",
        description="Wire up Stripe checkout to the pricing section",
        parameters=("slug", "stripe_price_id"),
        scope_boundary="workspace",
        requires_confirmation=True,
        external_services=("stripe",),
        enabled=False,   # not yet implemented
    ),
    AgentCapability(
        name="send_marketing_email",
        description="Send a product announcement email via the configured email provider",
        parameters=("subject", "body", "recipient_list"),
        scope_boundary="session",
        requires_confirmation=True,
        external_services=("sendgrid", "resend"),
        enabled=False,
    ),
]


# Module-level singleton
_default_registry: Optional[CapabilityRegistry] = None


def get_registry() -> CapabilityRegistry:
    """Return the shared default capability registry (lazy-initialised)."""
    global _default_registry
    if _default_registry is None:
        _default_registry = CapabilityRegistry.default()
    return _default_registry
