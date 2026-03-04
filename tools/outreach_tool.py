"""
outreach_tool – LangChain tool.

Generates and persists outreach messages for a product.  Writes records
to the outreach_attempts table.  Does not make live network calls —
real delivery would be wired in production.
"""

import json
import re

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from data.database import get_connection, utc_now


class OutreachToolInput(BaseModel):
    product_name: str = Field(description="Name of the product being pitched.")
    targets: list[str] = Field(description="List of target names or segments to reach.")
    message_template: str = Field(
        description=(
            "Message body. Use {target} as placeholder for the recipient name "
            "and {product} for the product name."
        )
    )
    channel: str = Field(
        default="email",
        description="Outreach channel (email, linkedin, twitter, etc.).",
    )


@tool("outreach_tool", args_schema=OutreachToolInput)
def outreach_tool(
    product_name: str,
    targets: list[str],
    message_template: str,
    channel: str = "email",
) -> str:
    """Generate and persist outreach messages for a list of targets.

    Inserts one outreach_attempts row per target with status 'pending'.

    Returns a JSON string with: created_count, product_name, channel.
    """
    product_id = _get_product_id(product_name)
    created = 0

    with get_connection() as conn:
        for target in targets:
            message = message_template.format(
                target=target,
                product=product_name,
            )
            conn.execute(
                """
                INSERT INTO outreach_attempts
                    (created_at, product_id, target, message, status)
                VALUES (?, ?, ?, ?, 'pending')
                """,
                (utc_now(), product_id, target, message),
            )
            created += 1

    return json.dumps({
        "status": "success",
        "created_count": created,
        "product_name": product_name,
        "channel": channel,
        "targets": targets,
    })


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_product_id(product_name: str) -> int | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM products WHERE name = ?", (product_name,)
        ).fetchone()
    return row["id"] if row else None
