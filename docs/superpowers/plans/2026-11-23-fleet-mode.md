# tailtop Fleet Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fourth tailtop mode, Fleet, that ranks the tailnet's Linux boards worst first from `tailscale status` plus a read-only `tailscale ssh` probe, and offers restart-service and reboot behind a confirm with a terminal handover.

**Architecture:** Pure data code in `tailtop/data/` (config, probe parsing, verdicts, a `FleetPoller` with an injected probe runner); Textual UI in `tailtop/modes/fleet.py` plus two widgets; the app owns one `FleetPoller` that runs only while Fleet is active and reads the app's latest `Status`. Fixes bypass `_run_mutation` and use `suspend()` like `action_ssh`.

**Tech Stack:** Python ≥3.13, Textual 1.x, `tomllib`, asyncio, pytest + pytest-asyncio (`asyncio_mode = "auto"`).

**Spec:** `docs/superpowers/specs/2026-11-23-fleet-mode-design.md`

## Global Constraints

- Nothing is installed on the boards; probes are read-only and never use sudo.
- No password, key or user name is stored or hard-coded in code; the only user example lives in `fleet.example.toml` (`boarduser`).
- Probe: 10 s timeout per board, at most 4 at once, interval 30 s default, offline boards never probed.
- Status poller cadence while Fleet is active: 5 s.
- History ring buffer: 60 samples per board (temperature and load1).
- Warn thresholds: temp ≥ 70 °C, disk ≥ 85 %, mem ≥ 90 %, load1 ≥ 2 × cores, under-voltage or throttled now.
- Verdict order: down, unreachable/rebooting, useless, warn, ok; ties by longest in state.
- Name regex for `service` and `user`: `^[A-Za-z0-9@._:-]+$`.
- Reboot window: "rebooting" for up to 180 s, re-probe every 15 s.
- Config path: `~/.config/tailtop/fleet.toml`; missing file means defaults.
- Fix commands, verbatim: `tailscale ssh -t <user@>host sudo systemctl restart <service>` and `tailscale ssh -t <user@>host sudo systemctl reboot`.
- Existing 37 tests keep passing. Run tests with `uv run --extra dev pytest -q`.

## Review Focus

1. A board whose probe output is partial (e.g. Pi without `vcgencmd`, no thermal zone, a container): the row shows "–" for missing fields, never crashes. Pinned in Task 3.
2. A board that is online in Tailscale but refuses the SSH user: shows "unreachable · set user in fleet.toml", not stale numbers. Pinned in Task 4.
3. A board that goes offline while a probe is in flight, or between cycles: its last numbers are dropped and it shows "down" with `LastSeen`. Pinned in Task 4.
4. Leaving Fleet mode while probes are running: no exception, poller stops, no SSH processes left. Pinned in Task 6.
5. `R` pressed on a board with no service configured, or `B` on an offline board: a warning notice, no confirm, no subprocess. Pinned in Task 7.

---

## File map

| File | Responsibility |
|---|---|
| `tailtop/data/models.py` (modify) | add `Peer.last_seen` |
| `tailtop/data/fleet_config.py` (new) | `BoardConfig`, `FleetConfig`, `load_fleet_config` |
| `tailtop/data/fleet.py` (new) | probe script, `BoardHealth`, `parse_probe`, `decode_throttled`, `Board`, `Verdict`, `verdict`, `rank_boards` |
| `tailtop/data/fleet_poller.py` (new) | `ProbeError`, `ssh_probe_runner`, `FleetHistory`, `FleetPoller` |
| `tailtop/data/demo.py` (modify) | eight demo board peers, `demo_fleet_config`, `demo_probe_runner` |
| `tailtop/modes/fleet.py` (new) | `FleetMode` (summary row, table, detail, R/B bindings) |
| `tailtop/widgets/fleet_table.py`, `tailtop/widgets/fleet_detail.py` (new) | table and detail pane |
| `tailtop/themes/fleet.tcss` (new) | Fleet layout and state colours |
| `tailtop/app.py`, `tailtop/widgets/status_bar.py` (modify) | wiring, number keys, fixes, SSH user |
| `fleet.example.toml`, `README.md` (new/modify) | example config, docs |
| `tests/test_fleet_config.py`, `tests/test_fleet.py`, `tests/test_fleet_poller.py`, `tests/test_fleet_app.py` (new), `tests/test_models.py` (modify) | tests |

---

### Task 1: `Peer.last_seen`

**Files:**
- Modify: `tailtop/data/models.py` (`Peer` dataclass and `Peer.from_json`)
- Modify: `tailtop/data/demo.py` (`_PeerSpec`, `_spec_to_peer`)
- Test: `tests/test_models.py`

**Interfaces:**
- Produces: `Peer.last_seen: datetime | None` (keyword field with default `None`, placed after `tags`), parsed from `LastSeen` with `_parse_time` (Go zero time → `None`). `_PeerSpec.last_seen_ago_s: float | None = None`.

- [ ] **Step 1: Write the failing tests** in `tests/test_models.py`

```python
def test_last_seen_parsed():
    p = Peer.from_json({"ID": "1", "HostName": "slowclock", "LastSeen": "2026-06-05T21:52:12.1Z"})
    assert p.last_seen == datetime(2026, 6, 5, 21, 52, 12, 100000, tzinfo=UTC)

def test_last_seen_zero_time_is_none():
    p = Peer.from_json({"ID": "1", "LastSeen": "0001-01-01T00:00:00Z"})
    assert p.last_seen is None
```

- [ ] **Step 2: Run** `uv run --extra dev pytest tests/test_models.py -q`. Expected: 2 FAIL (`AttributeError: last_seen`).
- [ ] **Step 3: Implement** the field and parsing; in demo, set `last_seen` to `now - last_seen_ago_s` when given.
- [ ] **Step 4: Run** `uv run --extra dev pytest -q`. Expected: 39 passed.
- [ ] **Step 5: Commit** `git commit -m "feat(models): parse Peer.last_seen"`

---

### Task 2: Fleet config

**Files:**
- Create: `tailtop/data/fleet_config.py`, `fleet.example.toml`
- Test: `tests/test_fleet_config.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) BoardConfig(name: str, user: str | None = None, service: str | None = None, label: str | None = None, ignore: bool = False)`
  - `@dataclass(frozen=True) FleetConfig(user: str | None = None, interval: float = 30.0, only_listed: bool = False, boards: dict[str, BoardConfig] = field(default_factory=dict))` with `def board(self, name: str) -> BoardConfig` (returns the listed one or `BoardConfig(name)`) and `def user_for(self, name: str) -> str | None` (board user, else default user).
  - `DEFAULT_PATH = Path.home() / ".config" / "tailtop" / "fleet.toml"`
  - `NAME_RE = re.compile(r"^[A-Za-z0-9@._:-]+$")`
  - `def load_fleet_config(path: Path = DEFAULT_PATH) -> tuple[FleetConfig, list[str]]`: returns config and a list of human error strings. Missing file → `(FleetConfig(), [])`. Broken TOML → `(FleetConfig(), ["fleet.toml: <tomllib message>"])`. A `user` or `service` failing `NAME_RE` is dropped from that board with an error naming the board and field. Unknown keys ignored. `interval` below 5 is clamped to 5.

- [ ] **Step 1: Write the failing tests** (use `tmp_path`)

```python
def test_missing_file_gives_defaults(tmp_path):
    cfg, errs = load_fleet_config(tmp_path / "nope.toml")
    assert cfg == FleetConfig() and errs == []

def test_overrides_and_user_fallback(tmp_path):
    p = tmp_path / "f.toml"
    p.write_text('[defaults]\nuser="boarduser"\ninterval=60\n'
                 '[boards.greenhouse]\nservice="tailprobe"\nlabel="plant monitor"\n'
                 '[boards.fastclock]\nuser="pi2"\n[boards.srv]\nignore=true\n')
    cfg, errs = load_fleet_config(p)
    assert errs == []
    assert cfg.interval == 60
    assert cfg.board("greenhouse").service == "tailprobe"
    assert cfg.user_for("greenhouse") == "boarduser"
    assert cfg.user_for("fastclock") == "pi2"
    assert cfg.board("srv").ignore is True
    assert cfg.board("unlisted") == BoardConfig("unlisted")

def test_broken_toml_falls_back(tmp_path):
    p = tmp_path / "f.toml"; p.write_text("[defaults\n")
    cfg, errs = load_fleet_config(p)
    assert cfg == FleetConfig() and len(errs) == 1 and errs[0].startswith("fleet.toml:")

def test_unsafe_service_rejected(tmp_path):
    p = tmp_path / "f.toml"
    p.write_text('[boards.x]\nservice="kiosk; rm -rf /"\nuser="a b"\n')
    cfg, errs = load_fleet_config(p)
    assert cfg.board("x").service is None and cfg.board("x").user is None
    assert len(errs) == 2 and all("x" in e for e in errs)

def test_interval_clamped(tmp_path):
    p = tmp_path / "f.toml"; p.write_text("[defaults]\ninterval=1\n")
    assert load_fleet_config(p)[0].interval == 5
```

- [ ] **Step 2: Run** `uv run --extra dev pytest tests/test_fleet_config.py -q`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement** `tailtop/data/fleet_config.py`. Write `fleet.example.toml` at the repo root with the spec 5.1 example, every line commented as an example, `user = "boarduser"` shown as an example only, plus `only_listed`.
- [ ] **Step 4: Run** the file's tests. Expected: 5 passed.
- [ ] **Step 5: Commit** `git commit -m "feat(fleet): config loader with name validation"`

---

### Task 3: Probe parsing and verdicts

**Files:**
- Create: `tailtop/data/fleet.py`
- Test: `tests/test_fleet.py`, fixtures `tests/fixtures/probe_pi4.txt`, `probe_zero2w.txt`, `probe_no_vcgencmd.txt`, `probe_service_inactive.txt`

**Interfaces:**
- Produces:
  - `PROBE_SCRIPT: str`, a POSIX `sh` script, read on stdin, that prints one `key=value` line each for: `hostname`, `uptime` (first field of `/proc/uptime`), `loadavg` (first three fields of `/proc/loadavg`), `cores` (`nproc`), `temp_milli` (`thermal_zone0/temp`), `mem_total_kb`, `mem_avail_kb`, `disk_pct` (Use% of `df -P /` without `%`), `throttled` (hex after `throttled=`), `model` (`/proc/device-tree/model` with NUL stripped), `service` (`systemctl is-active "$SERVICE"`). Missing sources print nothing for that key. `$SERVICE` arrives as the script's first positional argument (`sh -s -- <service>`); when empty, skip the `service` line.
  - `@dataclass(frozen=True) Throttle(undervolt_now: bool, throttled_now: bool, undervolt_ever: bool, throttled_ever: bool)`
  - `def decode_throttled(hex_value: str) -> Throttle`: bit 0 under-voltage now, bit 2 throttled now, bit 16 under-voltage since boot, bit 18 throttled since boot. Bad input → all `False`.
  - `@dataclass BoardHealth(temp_c: float | None, load1: float | None, load5: float | None, load15: float | None, cores: int | None, mem_pct: float | None, disk_pct: float | None, uptime_s: float | None, throttle: Throttle | None, model: str | None, service_state: str | None, error: str | None, probed_at: datetime)`
  - `def parse_probe(text: str, *, now: datetime) -> BoardHealth`: tolerant; a missing or unparseable key gives `None`; empty text gives `error="empty probe output"`.
  - `class Verdict(Enum)`: members `DOWN, UNREACHABLE, REBOOTING, USELESS, WARN, OK, PENDING`, with a `rank: int` property: DOWN 0, UNREACHABLE and REBOOTING 1, USELESS 2, WARN 3, OK 4, PENDING 5. PENDING means online but not probed yet. It renders dim as `probing`, so the first frame doesn't flash every board as a problem.
  - `@dataclass Board(name: str, peer: Peer, config: BoardConfig, health: BoardHealth | None = None, rebooting_since: datetime | None = None, state_since: datetime | None = None)`
  - `def verdict(board: Board, *, now: datetime) -> Verdict`, per spec 5.4. Order of checks: offline → DOWN; within the reboot window and (`health is None` or `health.error`) → REBOOTING; `health is None` → PENDING; `health.error` → UNREACHABLE; then USELESS, WARN, OK. `REBOOTING` when `rebooting_since` is within 180 s and the probe failed or is pending. `USELESS` only when `config.service` is set and `health.service_state != "active"`. Warn thresholds from Global Constraints.
  - `def warnings(board: Board) -> list[str]`: human reasons, e.g. `"72°C"`, `"disk 91%"`, `"under-voltage"`.
  - `def since(board: Board, *, now: datetime) -> timedelta | None`: for DOWN, `now - peer.last_seen`; otherwise `now - state_since`.
  - `def rank_boards(boards: list[Board], *, now: datetime) -> list[Board]`: sort by `(verdict.rank, -since_seconds, name)`.
  - `def select_boards(status: Status, config: FleetConfig) -> list[tuple[Peer, BoardConfig]]`: peers with `os == "linux"`, not self, not `ignore`; when `only_listed`, only names in `config.boards`.

- [ ] **Step 1: Write the fixture files.** `probe_pi4.txt` from a Pi 4 (temp_milli 52000, loadavg 0.40 0.30 0.20, cores 4, mem 3900000/2000000, disk 46, throttled 0x0, model "Raspberry Pi 4 Model B Rev 1.5", service active). `probe_zero2w.txt` from the real greenhouse numbers (temp_milli 47236, loadavg 0.02 0.01 0.00, cores 4, mem_total_kb 425984 mem_avail_kb 209920, disk 46, throttled 0x0, model "Raspberry Pi Zero 2 W Rev 1.0", uptime 7358700). `probe_no_vcgencmd.txt`: same as Pi 4 without the `throttled` and `model` lines. `probe_service_inactive.txt`: Pi 4 with `service=inactive`.
- [ ] **Step 2: Write the failing tests**

```python
NOW = datetime(2026, 11, 23, 21, 0, tzinfo=UTC)

def test_parse_zero2w():
    h = parse_probe(fixture("probe_zero2w.txt"), now=NOW)
    assert h.temp_c == pytest.approx(47.2, abs=0.05)
    assert (h.load1, h.cores, h.disk_pct) == (0.02, 4, 46)
    assert h.mem_pct == pytest.approx(50.7, abs=0.1)
    assert h.throttle == Throttle(False, False, False, False)
    assert h.model == "Raspberry Pi Zero 2 W Rev 1.0" and h.error is None

def test_parse_missing_keys_are_none():
    h = parse_probe(fixture("probe_no_vcgencmd.txt"), now=NOW)
    assert h.throttle is None and h.model is None and h.temp_c == 52.0

def test_parse_garbage_and_empty():
    assert parse_probe("temp_milli=hot\nloadavg=x y z", now=NOW).temp_c is None
    assert parse_probe("", now=NOW).error == "empty probe output"

def test_decode_throttled():
    assert decode_throttled("0x50005") == Throttle(True, True, True, True)
    assert decode_throttled("0x50000") == Throttle(False, False, True, True)
    assert decode_throttled("nope") == Throttle(False, False, False, False)

def test_verdicts():  # build Boards with make_board(online=..., health=..., service=...)
    assert verdict(make_board(online=False), now=NOW) is Verdict.DOWN
    assert verdict(make_board(error="refused"), now=NOW) is Verdict.UNREACHABLE
    assert verdict(make_board(error="timeout", rebooting_since=NOW - timedelta(seconds=60)), now=NOW) is Verdict.REBOOTING
    assert verdict(make_board(error="timeout", rebooting_since=NOW - timedelta(seconds=200)), now=NOW) is Verdict.UNREACHABLE
    assert verdict(make_board(fixture_name="probe_service_inactive.txt", service="kiosk"), now=NOW) is Verdict.USELESS
    assert verdict(make_board(fixture_name="probe_service_inactive.txt", service=None), now=NOW) is Verdict.OK
    assert verdict(make_board(temp_milli=72000), now=NOW) is Verdict.WARN
    assert verdict(make_board(throttled="0x4"), now=NOW) is Verdict.WARN
    assert verdict(make_board(throttled="0x40000"), now=NOW) is Verdict.OK  # only "ever"

def test_rank_worst_first_and_longest_down_first():
    a = make_board("a", online=False, last_seen=NOW - timedelta(days=4))
    b = make_board("b", online=False, last_seen=NOW - timedelta(days=168))
    c = make_board("c"); d = make_board("d", temp_milli=75000)
    assert [x.name for x in rank_boards([c, a, d, b], now=NOW)] == ["b", "a", "d", "c"]

def test_select_boards(status_fixture):
    # fixture: linux, windows, macOS peers; config ignores one linux, then only_listed
    ...assert names == expected for default, ignore, and only_listed cases
```

`make_board` is a test helper in `tests/test_fleet.py` that builds a `Peer` (via `Peer.from_json`) and a `BoardHealth` from fixture text with overrides. For `test_select_boards`, build the `Status` inline from three peer dicts rather than editing `status.json`.

- [ ] **Step 3: Run** `uv run --extra dev pytest tests/test_fleet.py -q`. Expected: FAIL (module missing).
- [ ] **Step 4: Implement** `tailtop/data/fleet.py` (no Textual imports). `mem_pct = 100 × (total − avail) / total`.
- [ ] **Step 5: Run** the file's tests. Expected: all pass. Then a manual check: `tailscale ssh boarduser@greenhouse sh -s -- tailprobe < <(python -c "from tailtop.data.fleet import PROBE_SCRIPT; print(PROBE_SCRIPT)")` prints key=value lines that `parse_probe` turns into a `BoardHealth` with no `None` fields except as expected. If greenhouse is offline, say so in the task report.
- [ ] **Step 6: Commit** `git commit -m "feat(fleet): probe script, parser and verdicts"`

---

### Task 4: FleetPoller

**Files:**
- Create: `tailtop/data/fleet_poller.py`
- Test: `tests/test_fleet_poller.py`

**Interfaces:**
- Consumes: Task 2 `FleetConfig`; Task 3 `PROBE_SCRIPT`, `parse_probe`, `Board`, `select_boards`, `BoardHealth`.
- Produces:
  - `class ProbeError(Exception)` with `.message: str`.
  - `ProbeRunner = Callable[[str, str | None, str | None], Awaitable[str]]`: `(host, user, service) -> stdout`, raises `ProbeError` on failure.
  - `def ssh_probe_runner(binary: str = "tailscale", timeout: float = 10.0) -> ProbeRunner`: runs `[binary, "ssh", f"{user}@{host}" if user else host, "sh", "-s", "--", service or ""]` with `PROBE_SCRIPT` on stdin. Kills the process on timeout and raises `ProbeError("timeout after 10s")`. Non-zero exit with stderr containing `failed to look up local user` or `does not permit` raises `ProbeError("unreachable · set user in fleet.toml")`; other failures raise `ProbeError(<last stderr line>)`. A non-zero exit that still printed `hostname=` is treated as success (one probe line may fail).
  - `class FleetHistory`: `record(name: str, temp_c: float | None, load1: float | None) -> None`; `temps(name) -> list[float]`; `loads(name) -> list[float]`; deque `maxlen=60`; `None` values are skipped.
  - `class FleetPoller(runner: ProbeRunner, get_status: Callable[[], Status | None], config: FleetConfig, on_update: Callable[[list[Board]], None], *, interval: float | None = None, concurrency: int = 4, clock: Callable[[], datetime] = lambda: datetime.now(UTC))` with:
    - `boards: dict[str, Board]`, `history: FleetHistory`, `_task: asyncio.Task | None` (same pattern as `Poller`)
    - `start() -> None`, `async stop() -> None` (cancels the loop and in-flight probes), `probe_now(name: str | None = None) -> None`, `mark_rebooting(name: str) -> None`
    - `async cycle() -> None`: one pass, public for tests. Reads `get_status()`; if `None`, returns. Builds boards via `select_boards`; offline boards get `health=None`; online boards are probed under an `asyncio.Semaphore(concurrency)`; `ProbeError` gives `BoardHealth(..., error=msg)` with all numbers `None`; updates `state_since` when the verdict changes; records history; calls `on_update(rank_boards(...))`.
    - Loop interval is `config.interval` unless `interval` is passed. While any board is rebooting, that board is re-probed every 15 s.

- [ ] **Step 1: Write the failing tests** with a fake runner and a hand-built `Status`

```python
async def test_offline_boards_not_probed(): ...assert calls == ["plant"]
async def test_concurrency_capped_at_4():  # 8 online boards, runner tracks max in-flight via a counter and asyncio.sleep(0.01)
    ...assert max_in_flight == 4
async def test_probe_error_becomes_unreachable():  # runner raises ProbeError("unreachable · set user in fleet.toml")
    ...assert board.health.error == "unreachable · set user in fleet.toml" and board.health.temp_c is None
async def test_board_going_offline_drops_numbers():  # cycle 1 online with health, cycle 2 offline
    ...assert boards["plant"].health is None
async def test_on_update_gets_ranked_list(): ...assert [b.name for b in updates[-1]] == ["slow", "plant"]
async def test_history_bounded_at_60(): ...assert len(poller.history.temps("plant")) == 60
async def test_stop_cancels_inflight():  # runner awaits an Event that never fires
    poller.start(); await asyncio.sleep(0.01); await poller.stop()
    ...assert runner_task_was_cancelled
async def test_ssh_runner_maps_refused_user(tmp_path):  # fake binary: a shell script in tmp_path printing the stderr and exit 255
    ...with pytest.raises(ProbeError, match="set user in fleet.toml")
async def test_ssh_runner_timeout(tmp_path):  # fake binary that sleeps 5; runner timeout=0.2
    ...with pytest.raises(ProbeError, match="timeout")
```

- [ ] **Step 2: Run** `uv run --extra dev pytest tests/test_fleet_poller.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** `tailtop/data/fleet_poller.py`, following `tailtop/data/poller.py` (wake event, cancellation re-raised).
- [ ] **Step 4: Run** the file, then the full suite. Expected: all pass.
- [ ] **Step 5: Commit** `git commit -m "feat(fleet): FleetPoller with injected probe runner"`

---

### Task 5: Demo fleet

**Files:**
- Modify: `tailtop/data/demo.py`
- Test: `tests/test_fleet_poller.py` (one test)

**Interfaces:**
- Consumes: Tasks 1 to 4.
- Produces: eight extra demo peers with `os="linux"`, named `clock-hall`, `clock-desk`, `clock-round`, `clock-square`, `eink-bed`, `eink-kitchen`, `plant-monitor`, `tv-board`; `def demo_fleet_config() -> FleetConfig` (`only_listed=True`, user `demo`; services: `clock-desk`, `clock-round`, `clock-square` → `superclock`; `eink-bed`, `eink-kitchen` → `inkypi`; `plant-monitor` → `plantd`; `clock-hall` and `tv-board` have none); `def demo_probe_runner(seed: int = 7) -> ProbeRunner` that returns canned `key=value` text with drifting temperature. States: `clock-round` and `eink-bed` offline (last seen 41 d and 117 d ago), `tv-board` raises `ProbeError("timeout after 10s")`, `eink-kitchen` returns `service=inactive`, `clock-square` returns 74 °C and `throttled=0x50005`, the other three ok.

- [ ] **Step 1: Write the failing test**

```python
async def test_demo_fleet_covers_every_state():
    client = DemoClient(); status = await client.status()
    poller = FleetPoller(demo_probe_runner(), lambda: status, demo_fleet_config(), updates.append)
    await poller.cycle()
    verdicts = {verdict(b, now=...) for b in updates[-1]}
    assert {Verdict.DOWN, Verdict.UNREACHABLE, Verdict.USELESS, Verdict.WARN, Verdict.OK} <= verdicts
```

- [ ] **Step 2: Run** it. Expected: FAIL.
- [ ] **Step 3: Implement** in `demo.py`.
- [ ] **Step 4: Run** the full suite. Expected: all pass, including `test_app.py` (which uses the JSON fixture, not the demo).
- [ ] **Step 5: Commit** `git commit -m "feat(demo): synthetic fleet in every state"`

---

### Task 6: Fleet mode UI and app wiring

**Files:**
- Create: `tailtop/modes/fleet.py`, `tailtop/widgets/fleet_table.py`, `tailtop/widgets/fleet_detail.py`, `tailtop/themes/fleet.tcss`
- Modify: `tailtop/app.py` (`CSS_PATH`, `BINDINGS`, `MODE_ORDER`, `compose`, `__init__`, `action_cycle_mode`, `action_refresh`, `action_help`, `main`), `tailtop/widgets/status_bar.py` (`_MODE_LABEL["fleet"] = ("FLEET", "#7fd88f")`)
- Test: `tests/test_fleet_app.py`

**Interfaces:**
- Consumes: Tasks 2 to 5.
- Produces:
  - `TailtopApp.__init__(client=None, auto_poll=True, splash=None, fleet_runner: ProbeRunner | None = None, fleet_config: FleetConfig | None = None)`. Defaults: `ssh_probe_runner(self.client._binary)` and `load_fleet_config()`. Config errors become one `notify(..., severity="error")` on mount. In `main`, `--demo` passes `demo_probe_runner()` and `demo_fleet_config()`.
  - `TailtopApp.fleet: FleetPoller` (created in `__init__`, `get_status=lambda: self.status`, `on_update=self._on_fleet`)
  - `TailtopApp.switch_mode(name: str) -> None`: the body of today's `action_cycle_mode` after choosing the name; also `self.fleet.start()` when entering `"fleet"` and `self.run_worker(self.fleet.stop())` when leaving it. `action_cycle_mode` calls it.
  - Bindings `1`, `2`, `3`, `4` → `switch_mode("comfort" | "cockpit" | "observatory" | "fleet")`.
  - `MODE_ORDER = ["comfort", "cockpit", "observatory", "fleet"]`
  - `action_refresh` also calls `self.fleet.probe_now()` when the mode is Fleet.
  - `FleetMode(ModeView)`, `cadence = 5.0`, `update_fleet(boards: list[Board], history: FleetHistory, now: datetime) -> None`, `selected_board() -> Board | None`. `update_data(status, rates)` only refreshes the header counts. Widgets: five summary `Static`s (`#fleet-boards`, `#fleet-down`, `#fleet-useless`, `#fleet-hottest`, `#fleet-disk`), `FleetTable` (a `DataTable`, cursor type row, columns board/state/since/temp/load/mem/disk; keeps the cursor on the same board name across updates), `FleetDetail` (model, memory, uptime, service with ●/○, temp and load sparklines via `tailtop.state.sparkline`, throttle text, "last probe Ns ago", warnings, the config path when unreachable because of the user).
  - State text and colour class per row: `down` / `unreachable` / `rebooting` / `useless` / `warn` / `ok` → CSS classes `-down`, `-unreachable`, … in `fleet.tcss` (red for down and useless, amber for unreachable, rebooting and warn, default for ok). Missing numbers render as `–`. "since" renders as `168d`, `5h`, `12m`.
  - Footer text: `R restart service  B reboot  s ssh  r probe now  1-4 mode  ? help  q quit`.

- [ ] **Step 1: Write the failing tests** (demo client, demo runner, demo config, `auto_poll=False`; feed status with `app._on_status(await client.status())`, then `await app.fleet.cycle()`)

```python
async def test_number_keys_switch_modes(): press "4" → app.active_mode == "fleet"; press "1" → "comfort"
async def test_tab_cycles_through_fleet(): four tabs return to comfort, third tab lands on observatory, fourth on fleet
async def test_fleet_table_worst_first(): first row's board == "eink-bed" (117 d down), last rows are ok
async def test_missing_numbers_render_dash(): row for "clock-round" shows "–" in temp/load/mem/disk
async def test_leaving_fleet_stops_poller(): press "4", then "1"; await pilot.pause(); assert app.fleet._task is None or app.fleet._task.done()
async def test_cursor_kept_across_updates(): move cursor to "plant-monitor", run cycle() again, selected_board().name == "plant-monitor"
```

Also update `tests/test_app.py::test_tab_cycles_modes` to expect `fleet` after `observatory`.

- [ ] **Step 2: Run** `uv run --extra dev pytest tests/test_fleet_app.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the widgets, mode, CSS and app wiring.
- [ ] **Step 4: Run** the full suite. Expected: all pass.
- [ ] **Step 5: Look at it:** `uv run tailtop --demo`, press `4`, and save a screenshot of the Fleet view at 180×50 and at 100×30 (Textual `app.save_screenshot()` in a pilot script under the scratchpad is fine). Confirm the summary boxes, table and detail pane don't overlap at either size. Note what you saw in the task report.
- [ ] **Step 6: Commit** `git commit -m "feat(fleet): Fleet mode view and mode switching"`

---

### Task 7: Fixes and SSH user

**Files:**
- Modify: `tailtop/modes/fleet.py` (bindings `R`, `B`), `tailtop/app.py` (`action_fleet_restart`, `action_fleet_reboot`, `action_ssh`)
- Test: `tests/test_fleet_app.py`

**Interfaces:**
- Consumes: Task 6 `FleetMode.selected_board()`, `FleetPoller.probe_now`, `FleetPoller.mark_rebooting`, `FleetConfig.user_for`.
- Produces:
  - `def fix_command(binary: str, board: Board, user: str | None, kind: Literal["restart", "reboot"]) -> list[str]` in `tailtop/data/fleet.py`. It returns the exact argv from Global Constraints, with `-t`.
  - `TailtopApp.action_fleet_restart()` and `action_fleet_reboot()` (both `@work`). Guard first. Restart needs an online board with a service; reboot needs an online board. On failure: `notify("<board>: no service set in fleet.toml", severity="warning")` or `notify("<board> is offline", severity="warning")`, with no confirm. Then `ConfirmScreen(f"Run on {name}?\n\n{' '.join(argv)}\n\nYou'll type the sudo password on {name}.", confirm_label="Restart service" | "Reboot")`. On yes: `with self.suspend(): subprocess.run(argv, check=False)`. Afterwards: restart → `self.fleet.probe_now(name)`; reboot → `self.fleet.mark_rebooting(name)`.
  - `FleetMode` bindings: `Binding("R", "app.fleet_restart", "Restart service")`, `Binding("B", "app.fleet_reboot", "Reboot")`.
  - `action_ssh`: in Fleet mode, the target is the selected board, and the user comes from `fleet_config.user_for(name)`, giving `user@host` when set. In other modes nothing changes.
  - The subprocess call goes through `self._handover(argv: list[str]) -> None` (wraps `suspend` and `subprocess.run`), so tests can monkeypatch it.

- [ ] **Step 1: Write the failing tests** (monkeypatch `app._handover` to record argv)

```python
async def test_restart_without_service_warns_no_confirm(): select "clock-hall" (no service in demo config), press "R"
    ...assert handover_calls == [] and not isinstance(app.screen, ConfirmScreen)
async def test_reboot_offline_warns(): select "eink-bed", press "B" → handover_calls == [], no ConfirmScreen
async def test_restart_confirm_shows_board_and_command(): select "plant-monitor", press "R"
    ...assert "plant-monitor" in question and "sudo systemctl restart" in question
async def test_restart_yes_hands_over_exact_argv(): press "R" then "y"
    ...assert handover_calls == [["tailscale", "ssh", "-t", "demo@plant-monitor", "sudo", "systemctl", "restart", "plantd"]]
async def test_reboot_yes_marks_rebooting(): press "B", "y"; await app.fleet.cycle() with the runner raising ProbeError for that board
    ...assert verdict(board, now=...) is Verdict.REBOOTING
async def test_ssh_in_fleet_uses_board_user(): press "s"
    ...assert handover_calls[-1] == ["tailscale", "ssh", "demo@plant-monitor"]
def test_fix_command_exact():
    assert fix_command("tailscale", board, "boarduser", "reboot") == ["tailscale", "ssh", "-t", "boarduser@fastclock", "sudo", "systemctl", "reboot"]
```

Demo service names come from Task 5 (`plant-monitor` → `plantd`, `clock-hall` has none).

- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement.** `action_ssh` also switches to `_handover`.
- [ ] **Step 4: Run** the full suite. Expected: all pass.
- [ ] **Step 5: Commit** `git commit -m "feat(fleet): restart and reboot fixes behind confirm"`

---

### Task 8: Docs and live check

**Files:**
- Modify: `README.md` (Modes table gets a Fleet row; a "Fleet" section with keys `1`-`4`, `R`, `B`, the config path, `fleet.example.toml`, and the sudo-password handover; requirements note "Tailscale SSH to the boards")
- Modify: `tailtop/app.py` `action_help` text to include `1-4 modes · R restart · B reboot`

- [ ] **Step 1: Update** the README and help text. No em dashes or exclamation marks in prose.
- [ ] **Step 2: Live check** against the real tailnet, read-only: create a scratch config outside the repo (`~/.config/tailtop/fleet.toml` only if it doesn't exist; otherwise leave it alone and use a temp path through `TailtopApp(fleet_config=...)` in a pilot script). Run one `FleetPoller.cycle()` with `ssh_probe_runner()` and print each board's name, verdict and since. Expected: the boards Tailscale shows offline appear as `down` with matching day counts, and greenhouse as `ok` or `useless` with real numbers. Do not press `R` or `B` against real boards.
- [ ] **Step 3: Run** `uv run --extra dev pytest -q`. Expected: all pass, about 37 + 35 tests.
- [ ] **Step 4: Commit** `git commit -m "docs(fleet): README section and help text"`
