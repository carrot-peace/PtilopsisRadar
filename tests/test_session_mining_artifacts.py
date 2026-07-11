import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "analysis" / "session_mining" / "mine_phase2.py"


def _session(home: Path, name: str, mtime: int) -> Path:
    path = home / ".codex" / "sessions" / "2026" / "07" / "08" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"role": "user", "content": "please review and fix"}) + "\n")
    os.utime(path, (mtime, mtime))
    return path


def _claude_session(home: Path, project: str, name: str, mtime: int) -> Path:
    path = home / ".claude" / "projects" / project / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"role": "user", "content": "please review and fix"}) + "\n")
    os.utime(path, (mtime, mtime))
    return path


def test_artifacts_are_cutoff_bounded_and_do_not_publish_local_paths(tmp_path):
    home = tmp_path / "private-home"
    output = tmp_path / "output"
    included = _session(home, "rollout-private-session-id.jsonl", 1_700_000_000)
    _session(home, "rollout-future-private-id.jsonl", 1_800_000_000)

    cutoff = "2023-11-14T22:13:20Z"
    subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--home",
            str(home),
            "--output-dir",
            str(output),
            "--cutoff",
            cutoff,
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    candidate_list = (output / "analysis" / "session_mining" / "candidate_files.txt").read_text()
    sample_list = (output / "analysis" / "session_mining" / "sample_files.txt").read_text()
    evidence = (output / "evidence.md").read_text()
    report = json.loads((output / "analysis" / "session_mining" / "phase2_report.json").read_text())

    assert report["candidate_files"] == 1
    assert report["corpus_cutoff"] == cutoff
    assert report["evidence"] == "evidence.md"
    assert "candidate-0001" in candidate_list
    assert "candidate-0001" in sample_list
    assert cutoff in evidence
    for published in (candidate_list, sample_list, evidence, json.dumps(report)):
        assert str(home) not in published
        assert included.name not in published
        assert "private-session-id" not in published


def test_cutoff_requires_timezone(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--home",
            str(tmp_path),
            "--output-dir",
            str(tmp_path / "output"),
            "--cutoff",
            "2026-07-08T16:29:15",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "must include a timezone offset or Z" in result.stderr


def test_distinct_claude_projects_keep_distinct_anonymous_lifecycles(tmp_path):
    home = tmp_path / "private-home"
    output = tmp_path / "output"
    for project in ("secret-alpha", "secret-beta"):
        for index in range(3):
            _claude_session(home, project, f"session-{index}.jsonl", 1_700_000_000 + index)

    subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--home",
            str(home),
            "--output-dir",
            str(output),
            "--cutoff",
            "2023-11-15T00:00:00Z",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    evidence = (output / "evidence.md").read_text()
    assert "Claude project 001" in evidence
    assert "Claude project 002" in evidence
    assert "secret-alpha" not in evidence
    assert "secret-beta" not in evidence
