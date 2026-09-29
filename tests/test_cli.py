"""CLI: record with a fake API, then replay from the command line with no key."""
import json

from anthropic import Anthropic, DefaultHttpxClient

from fake_claude import FakeClaude, transport
from test_agent import LESSON
from helpers import RESPONSES
from curriculum_auditor import cli
from curriculum_auditor.replay import Recording, RecordingTransport


def test_audit_and_score_replay_from_the_command_line(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "ramp.md").write_text(LESSON)
    (tmp_path / "responses.json").write_text(json.dumps([r.model_dump() for r in RESPONSES]))

    def recording_client(backend, recording=None, env_file=".env"):
        t = RecordingTransport(Recording(tmp_path / recording), inner=transport(FakeClaude()))
        return Anthropic(api_key="k", max_retries=0, http_client=DefaultHttpxClient(transport=t))

    real = cli.make_client
    monkeypatch.setattr(cli, "make_client", lambda backend, recording=None, **kw:
                        recording_client(backend, recording) if backend == "live" else real(backend, recording=recording))
    assert cli.main(["audit", "ramp.md", "--backend", "live", "--record", "rec/cov.json"]) == 0
    assert cli.main(["audit", "ramp.md", "--recording", "rec/cov.json", "--out", "replayed"]) == 0
    coverage = next((tmp_path / "replayed").glob("coverage-*.json"))
    assert json.loads(coverage.read_text())["complete"]
    assert cli.main(["score", "responses.json", "--curriculum", "ramp.md", "--coverage", str(coverage),
                     "--backend", "live", "--record", "rec/scores.json"]) == 0
    assert cli.main(["score", "responses.json", "--curriculum", "ramp.md", "--coverage", str(coverage),
                     "--recording", "rec/scores.json", "--out", "replayed"]) == 0
    assert "0 API call" not in capsys.readouterr().out.split("Saved")[-1]


def test_missing_recording_is_a_clear_error(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "ramp.md").write_text(LESSON)
    assert cli.main(["audit", "ramp.md"]) == 1
    assert "No recording" in capsys.readouterr().err


def test_xq_recordings_must_stay_out_of_git(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "ramp.md").write_text(LESSON)
    assert cli.main(["audit", "ramp.md", "--rubric", "xq", "--backend", "live", "--record", "recordings/x.json"]) == 1
    assert "Save them under data/" in capsys.readouterr().err


def test_label_csv_reads_levels_and_ie(tmp_path):
    path = tmp_path / "labels.csv"
    path.write_text("response_id,skill_id,skill_name,level\nr1,S.a,x,3\nr1,S.b,x,ie\nr2,S.a,x,\n")
    assert cli.read_label_csv(path) == [
        {"response_id": "r1", "skill_id": "S.a", "level": 3, "status": "scored"},
        {"response_id": "r1", "skill_id": "S.b", "level": None, "status": "insufficient_evidence"}]
    path.write_text("response_id,skill_id,skill_name,level\nr1,S.a,x,5\n")
    import pytest
    with pytest.raises(ValueError, match="1-4 or IE"):
        cli.read_label_csv(path)
