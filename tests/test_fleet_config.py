"""Fleet config: optional TOML, per-board overrides, unsafe names rejected."""

from __future__ import annotations

from tailtop.data.fleet_config import BoardConfig, FleetConfig, load_fleet_config


def test_missing_file_gives_defaults(tmp_path) -> None:
    cfg, errs = load_fleet_config(tmp_path / "nope.toml")
    assert cfg == FleetConfig()
    assert errs == []


def test_overrides_and_user_fallback(tmp_path) -> None:
    p = tmp_path / "f.toml"
    p.write_text(
        '[defaults]\nuser="nickv2026"\ninterval=60\n'
        '[boards.plantdashboard]\nservice="tailprobe"\nlabel="plant monitor"\n'
        '[boards.fastclock]\nuser="pi2"\n'
        "[boards.srv]\nignore=true\n"
    )
    cfg, errs = load_fleet_config(p)
    assert errs == []
    assert cfg.interval == 60
    assert cfg.board("plantdashboard").service == "tailprobe"
    assert cfg.board("plantdashboard").label == "plant monitor"
    assert cfg.user_for("plantdashboard") == "nickv2026"
    assert cfg.user_for("fastclock") == "pi2"
    assert cfg.board("srv").ignore is True
    assert cfg.board("unlisted") == BoardConfig("unlisted")


def test_broken_toml_falls_back(tmp_path) -> None:
    p = tmp_path / "f.toml"
    p.write_text("[defaults\n")
    cfg, errs = load_fleet_config(p)
    assert cfg == FleetConfig()
    assert len(errs) == 1
    assert errs[0].startswith("fleet.toml:")


def test_unsafe_service_rejected(tmp_path) -> None:
    p = tmp_path / "f.toml"
    p.write_text('[boards.x]\nservice="kiosk; rm -rf /"\nuser="a b"\n')
    cfg, errs = load_fleet_config(p)
    assert cfg.board("x").service is None
    assert cfg.board("x").user is None
    assert len(errs) == 2
    assert all("x" in e for e in errs)


def test_unsafe_default_user_rejected(tmp_path) -> None:
    p = tmp_path / "f.toml"
    p.write_text('[defaults]\nuser="$(id)"\n')
    cfg, errs = load_fleet_config(p)
    assert cfg.user is None
    assert len(errs) == 1


def test_interval_clamped(tmp_path) -> None:
    p = tmp_path / "f.toml"
    p.write_text("[defaults]\ninterval=1\n")
    assert load_fleet_config(p)[0].interval == 5


def test_only_listed(tmp_path) -> None:
    p = tmp_path / "f.toml"
    p.write_text("[defaults]\nonly_listed=true\n")
    assert load_fleet_config(p)[0].only_listed is True
