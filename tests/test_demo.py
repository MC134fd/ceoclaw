"""
Focused tests for Step 3 demo deliverables.

1.  demo subcommand completes and surfaces run_id in output.
2.  demo subcommand generates an export file.
3.  export subcommand writes Markdown for most recent run.
4.  export subcommand --run-id for a specific run.
5.  API /summary/latest returns ok when data exists.
6.  API /summary/latest returns no_runs status when DB is empty.
7.  API list endpoints return [] instead of 500 on unexpected error.
8.  run subcommand always includes run_id in output.
9.  quiet=True suppresses streaming but run_graph still returns run_id.
10. _print_cycle_table handles empty DB gracefully.
"""

import sys
import io
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    tmp_db = str(tmp_path / "test_demo.db")
    monkeypatch.setenv("CEOCLAW_DATABASE_PATH", tmp_db)
    import config.settings as cs
    cs.settings = cs.Settings()
    cs.settings.database_path = tmp_db  # prevent load_dotenv(override=True) clobber
    from data.database import init_db
    init_db()
    yield


# ---------------------------------------------------------------------------
# Demo subcommand
# ---------------------------------------------------------------------------

def test_demo_subcommand_completes_and_shows_run_id(capsys):
    """demo --cycles 3 --mock-model must complete and print a run_id."""
    from main import main
    main(["demo", "--cycles", "3", "--mock-model"])
    captured = capsys.readouterr()
    assert "Run ID" in captured.out
    # run_id is a UUID (contains hyphens)
    assert "-" in captured.out


def test_demo_subcommand_generates_export_file(tmp_path, monkeypatch):
    """demo mode must create a Markdown export file."""
    # Point exports dir to tmp_path via db path
    tmp_db = str(tmp_path / "demo.db")
    monkeypatch.setenv("CEOCLAW_DATABASE_PATH", tmp_db)
    import config.settings as cs
    cs.settings = cs.Settings()
    cs.settings.database_path = tmp_db  # prevent load_dotenv(override=True) clobber
    from data.database import init_db
    init_db()

    from main import main
    main(["demo", "--cycles", "3", "--mock-model"])

    exports_dir = tmp_path / "exports"
    md_files = list(exports_dir.glob("*_summary.md"))
    assert len(md_files) >= 1, "Expected at least one _summary.md export file"
    content = md_files[0].read_text()
    assert "## KPI Timeline" in content
    assert "## Artifacts" in content
    assert "## Confidence Note" in content


def test_demo_export_failure_does_not_crash(capsys):
    """If export_run_summary raises, demo must still print the KPI summary."""
    from main import main
    with patch("core.agent_loop.export_run_summary", side_effect=RuntimeError("disk full")):
        main(["demo", "--cycles", "2", "--mock-model"])
    captured = capsys.readouterr()
    # Run ID must still be visible
    assert "Run ID" in captured.out
    # Warning must be shown
    assert "warn" in captured.out.lower() or "Export skipped" in captured.out


# ---------------------------------------------------------------------------
# Export subcommand
# ---------------------------------------------------------------------------

def test_export_subcommand_most_recent_run(tmp_path, monkeypatch, capsys):
    """export (no --run-id) writes Markdown for the most recent run."""
    tmp_db = str(tmp_path / "export.db")
    monkeypatch.setenv("CEOCLAW_DATABASE_PATH", tmp_db)
    import config.settings as cs
    cs.settings = cs.Settings()
    cs.settings.database_path = tmp_db
    from data.database import init_db
    init_db()

    # Seed a run first
    from core.agent_loop import run_graph
    run_graph(cycles=1, mock_mode=True, goal_mrr=100.0, max_cycles=1)

    from main import main
    main(["export"])
    captured = capsys.readouterr()
    assert "Report" in captured.out
    assert "_summary.md" in captured.out


def test_export_subcommand_specific_run_id(tmp_path, monkeypatch, capsys):
    """export --run-id <uuid> writes Markdown for that specific run."""
    tmp_db = str(tmp_path / "export2.db")
    monkeypatch.setenv("CEOCLAW_DATABASE_PATH", tmp_db)
    import config.settings as cs
    cs.settings = cs.Settings()
    cs.settings.database_path = tmp_db
    from data.database import init_db
    init_db()

    from core.agent_loop import run_graph
    final = run_graph(cycles=1, mock_mode=True, goal_mrr=100.0, max_cycles=1)
    run_id = final["run_id"]

    from main import main
    main(["export", "--run-id", run_id])
    captured = capsys.readouterr()
    assert run_id in captured.out
    assert "_summary.md" in captured.out


# ---------------------------------------------------------------------------
# API /summary/latest
# ---------------------------------------------------------------------------

@pytest.fixture()
def client():
    from api.server import app
    return TestClient(app)


def test_summary_latest_no_runs(client):
    """/summary/latest returns no_runs when get_recent_graph_runs returns []."""
    import api.server as server_mod
    from unittest.mock import patch
    with patch.object(server_mod._sm, "get_recent_graph_runs", return_value=[]):
        resp = client.get("/summary/latest")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "no_runs"


def test_summary_latest_after_run(client):
    """/summary/latest returns ok with run data after a run."""
    from core.agent_loop import run_graph
    run_graph(cycles=2, mock_mode=True, goal_mrr=100.0, max_cycles=2)

    resp = client.get("/summary/latest")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "run_id" in body
    assert "final_weighted_score" in body
    assert "kpi_trend" in body
    assert isinstance(body["kpi_trend"], list)
    assert body["artifact_count"] >= 0


def test_summary_latest_never_500(client):
    """/summary/latest must not return 500 even on empty DB."""
    resp = client.get("/summary/latest")
    assert resp.status_code != 500


# ---------------------------------------------------------------------------
# API list endpoint stability
# ---------------------------------------------------------------------------

def test_runs_recent_returns_empty_list_not_500(client):
    resp = client.get("/runs/recent")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_kpi_trend_returns_empty_list_not_500(client):
    resp = client.get("/kpi/trend")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_artifacts_recent_returns_empty_list_not_500(client):
    resp = client.get("/artifacts/recent")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ---------------------------------------------------------------------------
# run_graph quiet mode
# ---------------------------------------------------------------------------

def test_run_graph_quiet_suppresses_output(capsys):
    """quiet=True must suppress streaming output but still return run_id."""
    from core.agent_loop import run_graph
    final = run_graph(cycles=1, mock_mode=True, goal_mrr=100.0, max_cycles=1, quiet=True)
    captured = capsys.readouterr()
    # No cycle headers in stdout
    assert "CEOClaw" not in captured.out
    assert "Finished" not in captured.out
    # run_id must still be present in return value
    assert final.get("run_id") is not None


def test_run_graph_always_sets_run_id():
    """run_graph must return a state dict with run_id even in quiet mode."""
    from core.agent_loop import run_graph
    final = run_graph(cycles=1, mock_mode=True, goal_mrr=100.0, max_cycles=1, quiet=True)
    assert "run_id" in final
    assert len(final["run_id"]) == 36  # UUID format


# ---------------------------------------------------------------------------
# _print_cycle_table graceful fallback
# ---------------------------------------------------------------------------

def test_print_cycle_table_empty_db(capsys):
    """_print_cycle_table must not raise when no cycle_scores exist."""
    from main import _print_cycle_table
    import uuid
    _print_cycle_table(str(uuid.uuid4()))  # non-existent run_id
    # Must not raise — output is a graceful message
    captured = capsys.readouterr()
    assert "unavailable" in captured.out or "no cycle data" in captured.out


# ---------------------------------------------------------------------------
# Shell script sanity (bash -n syntax check)
# ---------------------------------------------------------------------------

def test_run_local_sh_exists_and_is_valid_bash():
    """scripts/run_local.sh must exist and pass bash -n syntax check."""
    import subprocess
    script = Path(__file__).resolve().parent.parent / "scripts" / "run_local.sh"
    assert script.exists(), "scripts/run_local.sh not found"
    result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
    assert result.returncode == 0, f"bash -n failed:\n{result.stderr}"


def test_bootstrap_sh_exists_and_is_valid_bash():
    """scripts/bootstrap.sh must exist and pass bash -n syntax check."""
    import subprocess
    script = Path(__file__).resolve().parent.parent / "scripts" / "bootstrap.sh"
    assert script.exists(), "scripts/bootstrap.sh not found"
    result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
    assert result.returncode == 0, f"bash -n failed:\n{result.stderr}"
