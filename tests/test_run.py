import pytest

from reports import run
from reports.report import NoDataForPeriod

pytestmark = pytest.mark.skipif(
    not run.ADS_PARQUET.exists(), reason="needs data/clean/ads.parquet (run pipeline/clean.py)"
)


def test_list_prints_clients_and_themes(capsys):
    assert run.main(["--list"]) == 0
    out = capsys.readouterr().out
    assert "clients:" in out and "themes:" in out and "northlight" in out


def test_default_anchor_writes_one_file_per_client(tmp_path):
    code = run.main(["--client", "all", "--period", "last-week", "--out", str(tmp_path)])
    assert code == 0
    assert len(list(tmp_path.glob("*.html"))) == 3


def test_unknown_theme_fails_before_writing(tmp_path):
    with pytest.raises(SystemExit):
        run.main(["--theme", "nope", "--out", str(tmp_path)])
    assert list(tmp_path.iterdir()) == []


def test_batch_is_atomic_when_a_build_raises(tmp_path, monkeypatch):
    calls = {"n": 0}
    real = run.build_report

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("boom")
        return real(*args, **kwargs)

    monkeypatch.setattr(run, "build_report", flaky)
    with pytest.raises(RuntimeError):
        run.main(["--client", "all", "--out", str(tmp_path)])
    assert list(tmp_path.glob("*.html")) == []  # nothing written despite client 1 building fine


def test_missing_data_for_one_client_skips_that_one_only(tmp_path, monkeypatch, capsys):
    real = run.build_report

    def sometimes(ads, client, *args, **kwargs):
        if client == "Nordfit Equipment":
            raise NoDataForPeriod("Nordfit Equipment: no rows")
        return real(ads, client, *args, **kwargs)

    monkeypatch.setattr(run, "build_report", sometimes)
    code = run.main(["--client", "all", "--out", str(tmp_path)])
    assert code == 0
    written = {p.name.split("_")[0] for p in tmp_path.glob("*.html")}
    assert written == {"clinica-vantia", "solmar-hotels"}
    assert "skipped Nordfit Equipment" in capsys.readouterr().err
