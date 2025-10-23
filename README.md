# local-proxy-strava-heatmap

A lightweight local HTTP proxy to use the Strava heatmap as XYZ tiles in QGIS, ArcGIS and other GIS software.

It offers a terminal menu for source, activity and color, plus CLI and environment settings for unattended use. The default source is the server at `89.168.43.214:9192`; Nakarte is an optional alternative.

> This project is intended for educational and personal use. Respect the terms of service of Strava and the upstream service.

## Install

Download and extract the release archive, open a terminal in the `local-proxy-strava-heatmap` directory, and run:

```bash
python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Python 3.9 or newer is required. Flask and Requests are required. Questionary provides the arrow-key menu; when it is unavailable, the program uses a numbered menu instead. Install dependencies with the **same Python interpreter** you use to run `lpsh.py`.

## Run

```bash
python lpsh.py
```

In a terminal, an arrow-key menu lets you choose the **source**, activity and color before the server starts. If Questionary is not installed, enter the displayed number or press Enter for the default. Ctrl+C cancels. The selected activity and color apply to the short `/heatmap/{z}/{x}/{y}.png` URL. Options supplied with `--source`, `--activity` or `--color` are not asked again. In a non-interactive environment, the menu is skipped automatically; use `--no-menu` to skip it in a terminal too. Environment-variable defaults are shown in the menu and can be changed there.

The default binds to `127.0.0.1:5000`, uses activity `all`, color `bluered`, and enables a disk cache in `./cache`. The **direct** source fetches tiles from `http://89.168.43.214:9192/identified/globalheat` with `v=19` and remains the default. The **nakarte** source uses `https://proxy.nakarte.me/https/content-a.strava.com/identified/globalheat` without `v`, adding `Referer: https://nakarte.me/`. Both are externally hosted services whose availability and operators are outside this project. The proxy does not host Strava data itself. You can also supply a custom base URL with `--upstream`.

To select Nakarte directly, run `python lpsh.py --source nakarte --activity all --color hot --no-menu`. To return to the default source, run `python lpsh.py` and keep the first source selected in the menu.

The direct source provides tiles through zoom **16**. Requests at zoom 17 and above returned 404 in tests on 26 September 2026. The proxy therefore rejects coordinates above zoom 16 by default for either source. Set the maximum zoom of your GIS XYZ layer to 16; the GIS can still zoom the map display, but it cannot fetch additional heatmap detail beyond the source resolution. If a source offers more detail, raise the limit with `--max-zoom`.

Add this XYZ URL to your GIS:

```text
http://127.0.0.1:5000/heatmap/{z}/{x}/{y}.png
```

You can also select activity and color directly in the URL, so multiple heatmap layers can coexist without running multiple proxy instances:

```text
http://127.0.0.1:5000/heatmap/ride/hot/{z}/{x}/{y}.png
http://127.0.0.1:5000/heatmap/run/blue/{z}/{x}/{y}.png
```

Check a known tile after starting the server with the default `all / bluered` layer:

```bash
curl -fL -o tile.png -D headers.txt \
  'http://127.0.0.1:5000/heatmap/all/bluered/14/8423/5363.png'
file tile.png
```

The returned file should be a 256×256 PNG with visible heatmap lines. Check `headers.txt` for `X-LPSH-Cache: MISS` on the first download and `HIT` on a repeat request. A transparent PNG with `X-LPSH-Cache: ERROR` indicates an upstream failure; the default `transparent` mode returns HTTP 200 for that fallback, so `curl -f` alone is not an adequate health check. Start with `--error-mode http` if you prefer HTTP 502/504 on upstream failures.

Supported activities: `all`, `run`, `ride`, `winter`, `water`.

Supported colors: `hot`, `blue`, `bluered`, `purple`, `gray`.

## CLI options

```bash
python lpsh.py --activity ride --color purple --port 5000
python lpsh.py --host 0.0.0.0 --cache-ttl 86400
python lpsh.py --no-cache
python lpsh.py --source nakarte --activity all --color hot --no-menu
python lpsh.py --no-menu --activity ride --color purple
python lpsh.py --error-mode http --log-level DEBUG
python lpsh.py --upstream https://strava-heatmap.tiles.freemap.sk --upstream-version ''
python lpsh.py --help
```

The Freemap example uses its older URL format; it only works while that external service is available. The `--upstream-version ''` argument removes `v` from its requests.

Useful options:

| Option | Default | Description |
|---|---:|---|
| `--activity` | `all` | Default activity for the compatibility endpoint |
| `--color` | `bluered` | Default color for the compatibility endpoint |
| `--host` | `127.0.0.1` | Bind address; use `0.0.0.0` only if LAN access is required |
| `--port` | `5000` | HTTP port |
| `--tile-size` | `256` | Tile size (`256` or `512`) |
| `--max-zoom` | `16` | Maximum accepted XYZ zoom; raise only for a source with higher-resolution tiles |
| `--cache-dir` | `cache` | Disk cache directory |
| `--cache-ttl` | `86400` | Cache lifetime in seconds; `0` means no expiry |
| `--no-cache` | off | Disable disk cache |
| `--error-mode` | `transparent` | Return a transparent PNG on upstream errors; `http` returns 502/504 |
| `--no-menu` | off | Skip the source, activity and color menu |
| `--source` | `direct` | Built-in source: `direct` or `nakarte` |
| `--upstream` | from source | Override with a custom base URL before `/activity/color/z/x/y.png` |
| `--upstream-version` | from source | Override the `v` query parameter (`19` for direct, omitted for nakarte) |
| `--debug` | off | Enable Flask debug mode explicitly |

## Environment variables

All main options can also be configured using environment variables:

```text
LPSH_ACTIVITY=ride
LPSH_COLOR=bluered
LPSH_SOURCE=direct
LPSH_HOST=127.0.0.1
LPSH_PORT=5000
LPSH_TILE_SIZE=256
LPSH_MAX_ZOOM=16
LPSH_CACHE_DIR=cache
LPSH_CACHE_TTL=86400
LPSH_NO_CACHE=false
LPSH_ERROR_MODE=transparent
LPSH_LOG_LEVEL=INFO
```

CLI arguments take precedence over environment variables where applicable. Optional `LPSH_UPSTREAM` and `LPSH_UPSTREAM_VERSION` override the selected source's URL and version. If a custom upstream is set, the source menu is skipped.

For unattended runs, set `LPSH_SOURCE`, `LPSH_ACTIVITY` and `LPSH_COLOR` as desired; the menu is automatically skipped without a terminal. The WSGI `app` can also be imported without triggering a prompt.

## Diagnostic endpoints

```text
GET /health
GET /stats
GET /
```

`/health` reports the current default layer and cache status. `/stats` reports request, cache and upstream counters.

Tile responses expose `X-LPSH-Cache` with `HIT`, `MISS`, or `ERROR`.

## Production/LAN usage

Flask's built-in server is suitable for local development and light personal use. Do not expose debug mode to a network. If you bind to `0.0.0.0`, ensure your firewall only permits trusted clients.

## Release scope

This release serves XYZ tiles through external heatmap sources; it does not generate or store Strava data. Source availability and authentication rules may change independently of this project. The default zoom limit is 16, matching the tested source resolution. No Python package is published; install from the release archive using the commands above.
