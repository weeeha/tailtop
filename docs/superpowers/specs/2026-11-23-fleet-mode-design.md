# tailtop Fleet mode: a terminal dashboard for the Pis on the tailnet

**Date:** 2026-11-23 · **Owner:** Nick · **Status:** draft for Nick's review · **Branch:** `feat/fleet-mode` (from `origin/main` 0f6e309)

**TL;DR.** A fourth tailtop mode, **Fleet**, that answers "is any board broken, and since when" for the Linux single-board computers on the tailnet, in a dense netwatch-style layout. Online boards are read over passwordless `tailscale ssh` every 30 s while the tab is open; offline boards come from `tailscale status`. Two fixes, restart the board's app service and reboot, run behind a confirm and hand the terminal over so the user types the sudo password. Nothing is installed on the Pis.

## 1. Why

Eight Linux boards drive displays around the apartment (four SuperClock round clocks, two e-ink dashboards, a plant monitor, an Orange Pi TV board). Boards have gone dark for weeks before anyone noticed, and a board can be online yet not doing its job (fleetview README, 2026-09). On 2026-11-23 seven of the eight were offline, last seen 4 to 168 days earlier. Nick installed `netwatch` and wants the same kind of dense terminal dashboard for these boards. tailtop already reads the tailnet in a Textual TUI, so Fleet is a new mode there rather than a new tool.

## 2. Goals, non-goals, anti-goals

**Goals**
- One screen that ranks boards worst first: offline the longest at the top, then online but unhealthy, then healthy.
- For each online board: uptime, CPU temperature, load, memory, root disk use, under-voltage/throttle flags, model, and whether its app service is active ("reachable but useless" when it is not).
- Short history (temperature and load sparklines) for the time the tab has been open.
- Fixes: restart the board's app service, reboot, SSH in. Each behind a confirm.
- Works in `--demo` with a synthetic fleet so it can be screenshotted and tested without the real boards.

**Non-goals (this round)**
- Persistent history, alerts or notifications when tailtop is closed (that is the later shared collector, option C below).
- Deploying code to boards (SuperClock has its own deploy, `me:clocks`).
- E-ink "last refresh" freshness, per-app health endpoints.
- fleetview (the web view).

**Anti-goals**
- Installing anything on the Pis, or storing any password or key in tailtop or its config.
- Fleet polling slowing or blocking the other three modes.
- A fix that runs without the user seeing exactly which board and command it will run.

## 3. Constraints (measured 2026-11-23)

- `tailscale ssh boarduser@greenhouse <cmd>` works with no password. Users `nickv` and `pi` are refused (`failed to look up local user`, `tailnet policy does not permit`).
- `sudo -n true` fails for `boarduser` on greenhouse: sudo needs a password. So fixes cannot run non-interactively.
- greenhouse is a Raspberry Pi Zero 2 W, 416 MB RAM, 4 cores. One SSH round trip printed `hostname`, `uptime`, thermal zone (`47236` = 47.2 °C), `vcgencmd get_throttled` (`throttled=0x0`) and `df -h /` without trouble.
- No running service on greenhouse has an obvious "kiosk" name (running non-system units: `nfs-blkmap`, `rpcbind`, `tailprobe`). The app service cannot be guessed and must be configured per board.
- `tailscale status --json` gives online state, OS and `LastSeen` for every peer. `Peer` (`tailtop/data/models.py`) parses online state and OS but **not** `LastSeen` (only `LastHandshake`), so this work adds a `last_seen` field. `LastSeen`, not `LastHandshake`, is the basis for "down 168d": the handshake can be stale on a peer that is online.
- On 2026-11-23 the tailnet's Linux peers were exactly the eight boards; no Linux servers, containers or VMs.
- tailtop: Python ≥3.13, Textual 1.x, plotext. One `Poller` runs `tailscale status` and hands a `Status` to the active `ModeView` via `update_data(status, rates)`; each mode sets `cadence`. Modes are swapped with a `ContentSwitcher`; `Tab` cycles `MODE_ORDER`. Mutating verbs go through `_run_mutation` (confirm screen); `action_ssh` suspends the TUI and runs `tailscale ssh`.

## 4. Approaches considered

| | How | Trade-off |
|---|---|---|
| **A. SSH from tailtop (picked)** | While Fleet is open, tailtop runs one read-only command per online board over `tailscale ssh` | Nothing to install; smallest build. History only while the tab is open; "down since" still comes from Tailscale's last seen |
| B. Agent on each Pi | A timer on each board writes a health file tailtop reads | History even when unwatched, but an install on 8 boards, 7 of them unreachable now. Dropped |
| C. Shared collector on the Mac | A launchd service samples all boards into SQLite; tailtop and fleetview read it | History and a fleetview data source, but a service to keep alive and about twice the work. Later |

Nick picked **A**. The probe and parsing code lives in its own module (`tailtop/data/fleet.py`) with no Textual imports, so a later collector (C) can reuse it unchanged.

## 5. Design

### 5.1 Which boards

- Default: every peer whose `os` is `linux`, excluding self.
- Optional config file `~/.config/tailtop/fleet.toml` (read with `tomllib`; missing file means defaults):

```toml
[defaults]
user = "boarduser"      # SSH user for every board unless overridden
interval = 30           # seconds between probes while Fleet is open

[boards.greenhouse]
service = "tailprobe"   # systemd unit that means "this board is doing its job"
label = "plant monitor"

[boards.fastclock]
service = "superclock-kiosk"   # example; real unit names are Nick's to fill in

[boards.some-server]
ignore = true
```

- With no `user` set anywhere, probes run as `tailscale ssh <host>` (Tailscale's default user). When a probe fails with "failed to look up local user" or "policy does not permit", the board shows **unreachable · set user in fleet.toml** and the detail pane gives the config path. No user name is hard-coded; the repo ships a commented `fleet.example.toml`, and the README shows it.
- `[defaults] only_listed = true` limits Fleet to boards with a `[boards.<name>]` table, for tailnets where Linux peers include servers or VMs. Default `false`, which fits Nick's tailnet today.
- `service` must match `^[A-Za-z0-9@._:-]+$` (optionally ending `.service`); anything else is rejected at load with a notification, so it can never inject into the remote shell. Host names come from Tailscale, and users from the config under the same regex.
- Unknown keys are ignored; a broken file shows one error notification and falls back to defaults.

### 5.2 Probe

One `tailscale ssh user@host sh -s` per online board, fed a fixed POSIX script on stdin that prints `key=value` lines:

- `hostname`, `/proc/uptime`, `/proc/loadavg`, `nproc`
- `/sys/class/thermal/thermal_zone0/temp`
- `MemTotal` / `MemAvailable` from `/proc/meminfo`
- `df -P /` (used %, size)
- `vcgencmd get_throttled` when present (else empty)
- `/proc/device-tree/model` when present
- `systemctl is-active <service>` when a service is configured

Rules: 10 s timeout per board; at most 4 probes at once (asyncio semaphore); offline boards are never probed; a board that fails shows the error text, not stale numbers. A probe never needs sudo.

Parsing is a pure function `parse_probe(text) -> BoardHealth` with fixture tests. `BoardHealth` is a dataclass: temp °C, load1/5/15, cores, mem used %, disk used %, uptime, throttle flags (decoded bits: under-voltage now / since boot, throttled now / since boot), model, service state, probe error, probed-at time.

### 5.3 Polling

- A second poller, `FleetPoller`, owned by the app, runs only while Fleet is the active mode (start on enter, stop on leave) at `interval` (default 30 s). `r` forces a probe now.
- The existing status poller keeps running as today; Fleet's `cadence` is 5 s so online/offline flips show quickly. `FleetPoller` does not call `tailscale status` itself: each cycle it reads the app's latest `Status` to decide which boards are online, then probes those.
- The probe runner is injected (`FleetPoller(runner=...)`). The real runner shells out to `tailscale ssh`; the demo and the tests pass a fake runner returning canned probe text.
- Fleet keeps a ring buffer per board (temperature and load, 60 samples, about 30 minutes at 30 s) for sparklines. Leaving and returning keeps the buffer for the life of the process.

### 5.4 Health verdict (worst first)

Each board gets one state, sorted in this order, ties by longest in state:

1. **down**: offline in Tailscale. Shows "down 168d" from last seen.
2. **unreachable**: online but the probe failed (refused user, timeout). A board within 3 minutes of a `B` reboot shows **rebooting** here instead.
3. **useless**: online, probe fine, configured service not `active`.
4. **warn**: any of temp ≥ 70 °C, disk ≥ 85 %, mem ≥ 90 %, load1 ≥ 2 × cores, under-voltage or throttled now.
5. **ok**.

"service not set" is shown neutrally, not as a problem. Thresholds are constants in `fleet.py`; my call, adjustable later.

### 5.5 Layout

Netwatch-style dense grid, Fleet's own theme file `themes/fleet.tcss`:

```
 tailtop  1 comfort  2 cockpit  3 observatory  4 fleet                    20:46:51
┌ boards ─────┐┌ down ───────┐┌ useless ────┐┌ hottest ────┐┌ fullest disk ┐
│ 8           ││ 7  slowest  ││ 0           ││ 47°C plant  ││ 46% plant    │
│ 1 up        ││ 168d        ││             ││             ││              │
└─────────────┘└─────────────┘└─────────────┘└─────────────┘└──────────────┘
┌ fleet ─ worst first ───────────────────────────────────┐┌ greenhouse ──────┐
│ board           state    since  temp  load  mem  disk ││ Pi Zero 2 W · 416 MB │
│ slowclock       down     168d    –     –     –    –   ││ up 85d · tailprobe ● │
│ dashboard3eink  down     117d    –     –     –    –   ││ temp ▁▂▂▃▂▂▂ 47°C    │
│ smallclock      down      85d    –     –     –    –   ││ load ▁▁▁▁▂▁▁ 0.02    │
│ …                                                     ││ throttle: none       │
│ greenhouse  ok        85d   47°  0.02  50%  46%   ││ last probe 12s ago   │
└───────────────────────────────────────────────────────┘└──────────────────────┘
 R restart service  B reboot  s ssh  r probe now  tab mode  ? help  q quit
```

- Top row: five summary boxes. Middle: the board table (`DataTable`, row cursor) and a detail pane for the selected board.
- Colour carries state only: down and useless red, unreachable and warn amber, ok default.
- Number keys `1` to `4` jump to a mode (new; `Tab` still cycles). Fleet is added to `MODE_ORDER` last.

### 5.6 Fixes

| Key | Fix | Command handed to the terminal |
|---|---|---|
| `R` | restart service | `tailscale ssh -t user@host sudo systemctl restart <service>` |
| `B` | reboot | `tailscale ssh -t user@host sudo systemctl reboot` |
| `s` | SSH | existing `action_ssh`, now using the board's configured user |

- Each fix first opens the existing `ConfirmScreen` naming the board and the exact command. On yes, the TUI suspends (like `action_ssh`), the user types the sudo password on the board, and the TUI resumes and re-probes that board.
- `R` is disabled with a notice when no service is configured or the board is not online. `B` is disabled when the board is not online.
- Fixes need a terminal handover, which `_run_mutation` (captured, non-interactive) does not do. Fleet gets its own path: `ConfirmScreen` → `suspend()` → `subprocess.run` of the `tailscale ssh -t …` line → resume. `Action` and `_run_mutation` stay unchanged.
- After `R`, re-probe that board at once. After `B`, the board shows **rebooting** (amber) instead of unreachable, and is re-probed every 15 s for up to 3 minutes. If it is still not back, it falls to unreachable.
- Keys: `R` and `B` are bound on the Fleet mode widget, so they exist only while Fleet is active. `r` keeps its app-wide meaning (refresh); in Fleet it also triggers an immediate probe. `s` keeps its meaning; in Fleet it targets the selected board and uses that board's configured user (`tailscale ssh user@host`).
- tailtop never sees, stores or pipes the password.
- Later option, not built now: a per-board sudoers rule for exactly these two commands would let fixes run without the handover.

### 5.7 Demo mode

`--demo` gets a synthetic fleet of eight boards in mixed states (two down for weeks, one unreachable, one useless, one hot and throttled, three ok) with temperatures that drift, so screenshots and tests cover every state.

### 5.8 Tests

- `parse_probe` against fixture outputs: Pi 4, Pi Zero 2 W, no `vcgencmd`, service inactive, garbage input.
- Throttle bit decoding.
- Verdict and sort order, including ties.
- Config loading: missing file, overrides, `ignore`, broken TOML.
- `FleetPoller`: concurrency cap, timeout produces `unreachable`, offline boards skipped, stops when the mode is left.
- App: Fleet in `MODE_ORDER`, number keys, fix keys disabled in the right states, confirm text names board and command (pilot tests with the demo client; no real SSH in tests).

## 6. Decided by Nick

- Lives in tailtop as a fourth mode, not a new tool.
- Watch plus safe fixes (restart service, reboot), not watch only.
- Collection approach A: SSH from tailtop while the tab is open.

## 7. My calls (Nick can override)

- Fixes hand over the terminal for the sudo password instead of storing anything.
- Config file at `~/.config/tailtop/fleet.toml`, optional, with `boarduser` as an example user (not hard-coded).
- 30 s probe interval, 10 s timeout, 4 at once; thresholds in 5.4.
- Number keys 1 to 4 for modes.
- Linux peers are boards by default; Windows and macOS machines are never listed. `only_listed` is there for other tailnets.
- "Down since" uses Tailscale's `LastSeen` (new `Peer.last_seen` field).
- No default SSH user; a refused board says to set one, and a commented example config ships.
- Fleet fixes use their own handover path; `R`/`B` exist only in Fleet; `r` and `s` keep their meaning, adapted to the selected board.
- After a reboot, the board shows "rebooting" for up to 3 minutes.
- Service and user names are validated against a unit-name regex.

## 8. Left to the builder

- Exact widget composition and CSS within the layout in 5.5.
- Sparkline rendering (reuse `tailtop.state.sparkline`).
- How `FleetPoller` hands results to the mode (message or callback), following the `Poller` pattern.
- Real service names per board: Nick fills these in his own config; the repo ships only a commented example.
