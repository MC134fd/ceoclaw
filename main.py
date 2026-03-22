"""
CEOClaw entry point  – v0.4 (demo-ready subcommands).

Subcommands:
    python main.py run    [--cycles N] [--continuous] [--goal-mrr X]
    python main.py export [--run-id UUID]      # omit --run-id to export most recent run
    python main.py demo   [--cycles N] [--goal-mrr X]
"""

import argparse
import sys


# ---------------------------------------------------------------------------
# Subcommand: run
# ---------------------------------------------------------------------------

def _cmd_run(args: argparse.Namespace) -> None:
    from core.agent_loop import run_graph

    final_state = run_graph(
        cycles=args.cycles,
        continuous=args.continuous,
        goal_mrr=args.goal_mrr,
        max_cycles=args.max_cycles,
    )
    _print_final_summary(final_state)


# ---------------------------------------------------------------------------
# Subcommand: export
# ---------------------------------------------------------------------------

def _cmd_export(args: argparse.Namespace) -> None:
    from core.agent_loop import export_run_summary
    from data.database import init_db, get_connection

    init_db()

    run_id = getattr(args, "run_id", None)
    if not run_id:
        try:
            with get_connection() as conn:
                row = conn.execute(
                    "SELECT run_id FROM graph_runs ORDER BY started_at DESC LIMIT 1"
                ).fetchone()
            if row is None:
                print("Error: no runs found in database.", file=sys.stderr)
                sys.exit(1)
            run_id = row["run_id"]
        except Exception as exc:
            print(f"Error reading database: {exc}", file=sys.stderr)
            sys.exit(1)

    try:
        path = export_run_summary(run_id)
        print(f"Run ID : {run_id}")
        print(f"Report : {path}")
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Subcommand: demo
# ---------------------------------------------------------------------------

def _cmd_demo(args: argparse.Namespace) -> None:
    from core.agent_loop import run_graph, export_run_summary

    print("\n" + "=" * 66)
    print("  CEOClaw  –  Autonomous Founder Agent  –  Demo Mode")
    print("=" * 66)
    print(f"  goal=${args.goal_mrr:.0f} MRR | cycles={args.cycles}")
    print("-" * 66)

    final_state = run_graph(
        cycles=args.cycles,
        goal_mrr=args.goal_mrr,
        max_cycles=args.cycles,
        quiet=True,
    )

    run_id = final_state["run_id"]

    # Clean cycle-by-cycle KPI table from persisted cycle_scores
    _print_cycle_table(run_id)

    # Final KPI summary (run_id always visible)
    _print_final_summary(final_state)

    # Auto-export — failure never crashes the display
    print("  Exporting run summary…")
    try:
        path = export_run_summary(run_id)
        print(f"  Report  : {path}")
    except Exception as exc:
        print(f"  [warn] Export skipped: {exc}")

    # API quick links (best-effort probe)
    _print_api_links(run_id)


# ---------------------------------------------------------------------------
# Shared display helpers
# ---------------------------------------------------------------------------

def _print_cycle_table(run_id: str) -> None:
    """Print a clean per-cycle KPI table from persisted cycle_scores."""
    try:
        from data.database import get_connection
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM cycle_scores WHERE run_id=? ORDER BY cycle_count ASC",
                (run_id,),
            ).fetchall()
    except Exception:
        print("  (cycle table unavailable)")
        return

    if not rows:
        print("  (no cycle data persisted)")
        return

    header = (
        f"  {'#':>3}  {'Domain':<11}  {'Action':<28}  "
        f"{'MRR':>7}  {'Score':>6}  {'Trend':>5}  Flags"
    )
    sep = "  " + "─" * 72
    print(header)
    print(sep)
    for r in rows:
        flags = "⏸ stagnant" if r["stagnant_cycles"] >= 3 else ""
        print(
            f"  {r['cycle_count']:>3}  {r['domain']:<11}  {r['action']:<28}  "
            f"${r['mrr']:>6.2f}  {r['weighted_score']:>6.3f}  "
            f"{r['trend_direction']:>5}  {flags}"
        )
    print(sep)


def _print_final_summary(final_state: dict) -> None:
    evaluation = final_state.get("evaluation", {})
    metrics = final_state.get("latest_metrics", {})
    run_id = final_state.get("run_id", "n/a")
    errors = len(final_state.get("errors", []))
    print(
        f"\n  Run ID      : {run_id}\n"
        f"  Cycles      : {final_state.get('cycle_count', 0)}\n"
        f"  MRR         : ${metrics.get('mrr', 0.0):.2f}"
        f"  (goal ${final_state.get('goal_mrr', 100.0):.2f})\n"
        f"  Traffic     : {metrics.get('website_traffic', 0)}\n"
        f"  Signups     : {metrics.get('signups', 0)}\n"
        f"  Weighted    : {final_state.get('weighted_score', 0.0):.3f} / 1.000\n"
        f"  Progress    : {evaluation.get('progress_score', 0.0):.1%}\n"
        f"  Stop reason : {final_state.get('stop_reason') or 'n/a'}\n"
        f"  Errors      : {errors}\n"
    )


def _print_api_links(run_id: str) -> None:
    """Probe local API server and print endpoint quick-links."""
    import urllib.request

    base = "http://localhost:8000"
    try:
        urllib.request.urlopen(f"{base}/health", timeout=0.5)
        server_up = True
    except Exception:
        server_up = False

    status_tag = "live" if server_up else "offline — start: uvicorn api.server:app --port 8000 &"
    print(f"  API server: {status_tag}")
    print(f"    GET /status         → {base}/status")
    print(f"    GET /runs/timeline  → {base}/runs/{run_id}/timeline")
    print(f"    GET /kpi/trend      → {base}/kpi/trend")
    print(f"    GET /artifacts      → {base}/artifacts/recent")
    print(f"    GET /summary/latest → {base}/summary/latest")
    print()


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="ceoclaw",
        description="Autonomous founder agent iterating toward $100 MRR.",
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    # --- run ---
    run_p = sub.add_parser("run", help="Run the agent graph for N cycles.")
    run_p.add_argument("--cycles", type=int, default=1,
                       help="Cycles to run (default: 1).")
    run_p.add_argument("--continuous", action="store_true",
                       help="Run until goal or --max-cycles.")
    run_p.add_argument("--goal-mrr", type=float, default=100.0, dest="goal_mrr",
                       help="Target MRR in USD (default: 100.0).")
    run_p.add_argument("--max-cycles", type=int, default=20, dest="max_cycles",
                       help="Hard cycle ceiling (default: 20).")

    # --- export ---
    exp_p = sub.add_parser("export", help="Export a Markdown run summary.")
    exp_p.add_argument("--run-id", default=None, dest="run_id", metavar="UUID",
                       help="Run ID to export (default: most recent run).")

    # --- demo ---
    demo_p = sub.add_parser("demo", help="Full demo: run + table + export + API links.")
    demo_p.add_argument("--cycles", type=int, default=8,
                        help="Cycles to run (default: 8).")
    demo_p.add_argument("--goal-mrr", type=float, default=100.0, dest="goal_mrr",
                        help="Target MRR in USD (default: 100.0).")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    if args.command == "run":
        _cmd_run(args)
    elif args.command == "export":
        _cmd_export(args)
    elif args.command == "demo":
        _cmd_demo(args)
    else:
        _parse_args(["--help"])


if __name__ == "__main__":
    main()
