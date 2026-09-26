"""Local proxy for Strava heatmap XYZ tiles."""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import socket
import struct
import sys
import threading
import time
import zlib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Optional

import requests
from flask import Flask, Response, jsonify

__version__ = "0.1.6"

ACTIVITIES = ("all", "run", "ride", "winter", "water")
COLORS = ("hot", "blue", "bluered", "purple", "gray")
DEFAULT_UPSTREAM = "http://89.168.43.214:9192/identified/globalheat"
DEFAULT_UPSTREAM_VERSION = "19"
NAKARTE_UPSTREAM = "https://proxy.nakarte.me/https/content-a.strava.com/identified/globalheat"
SOURCES = {
    "direct": (DEFAULT_UPSTREAM, DEFAULT_UPSTREAM_VERSION, None),
    "nakarte": (NAKARTE_UPSTREAM, "", "https://nakarte.me/"),
}
DEFAULT_USER_AGENT = f"local-proxy-strava-heatmap/{__version__}"

logger = logging.getLogger("lpsh")


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    payload = kind + data
    return struct.pack(">I", len(data)) + payload + struct.pack(">I", zlib.crc32(payload) & 0xFFFFFFFF)


def make_empty_tile(size: int = 256) -> bytes:
    """Create a valid fully-transparent RGBA PNG using only the standard library."""
    if size <= 0:
        raise ValueError("tile size must be positive")
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    # PNG scanlines: filter byte 0 + RGBA zeros for every pixel.
    raw = (b"\x00" + (b"\x00" * (size * 4))) * size
    return signature + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"IDAT", zlib.compress(raw, 9)) + _png_chunk(b"IEND", b"")


@dataclass(frozen=True)
class Config:
    activity: str = "all"
    color: str = "bluered"
    host: str = "127.0.0.1"
    port: int = 5000
    tile_size: int = 256
    max_zoom: int = 16
    cache_dir: Optional[Path] = Path("cache")
    cache_ttl: int = 86400
    connect_timeout: float = 3.05
    read_timeout: float = 10.0
    error_mode: str = "transparent"
    upstream: str = DEFAULT_UPSTREAM
    upstream_version: str = DEFAULT_UPSTREAM_VERSION
    referer: Optional[str] = None


class Stats:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.started_at = time.time()
        self.values = {
            "requests": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "upstream_downloads": 0,
            "upstream_errors": 0,
            "invalid_requests": 0,
        }

    def inc(self, key: str) -> None:
        with self._lock:
            self.values[key] += 1

    def snapshot(self) -> dict:
        with self._lock:
            data = dict(self.values)
        data["uptime_seconds"] = round(time.time() - self.started_at, 3)
        return data


def create_session(config: Optional[Config] = None) -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "image/png,image/*;q=0.8,*/*;q=0.5",
        }
    )
    if config is not None and config.referer:
        session.headers["Referer"] = config.referer
    return session


def is_valid_xyz(z: int, x: int, y: int, max_zoom: int) -> bool:
    if z < 0 or z > max_zoom:
        return False
    limit = 1 << z
    return 0 <= x < limit and 0 <= y < limit


def cache_path(config: Config, activity: str, color: str, z: int, x: int, y: int) -> Optional[Path]:
    if config.cache_dir is None:
        return None
    source = hashlib.sha256(f"{config.upstream}|{config.upstream_version}".encode()).hexdigest()[:16]
    return config.cache_dir / source / activity / color / str(config.tile_size) / str(z) / str(x) / f"{y}.png"


def read_cache(path: Optional[Path], ttl: int) -> Optional[bytes]:
    if path is None:
        return None
    try:
        if not path.is_file():
            return None
        if ttl > 0 and time.time() - path.stat().st_mtime > ttl:
            path.unlink()
            return None
        return path.read_bytes()
    except OSError as exc:
        logger.warning("Unable to read cache file %s: %s", path, exc)
        return None


def write_cache(path: Optional[Path], data: bytes) -> None:
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(path.suffix + f".{threading.get_ident()}.tmp")
        temp_path.write_bytes(data)
        os.replace(temp_path, path)
    except OSError as exc:
        logger.warning("Unable to write cache file %s: %s", path, exc)


def tile_response(data: bytes, *, cache_status: str, status: int = 200) -> Response:
    response = Response(data, status=status, content_type="image/png")
    response.headers["Cache-Control"] = "no-store" if cache_status == "ERROR" else "public, max-age=3600"
    response.headers["X-LPSH-Cache"] = cache_status
    return response


def create_app(config: Optional[Config] = None, session: Optional[requests.Session] = None) -> Flask:
    config = config or Config()
    session = session or create_session(config)
    stats = Stats()
    empty_tile = make_empty_tile(config.tile_size)

    app = Flask(__name__)
    app.config["LPSH_CONFIG"] = config
    app.extensions["lpsh_session"] = session
    app.extensions["lpsh_stats"] = stats

    @app.after_request
    def add_headers(response: Response) -> Response:
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["X-LPSH-Version"] = __version__
        return response

    def serve_tile(activity: str, color: str, z: int, x: int, y: int) -> Response:
        stats.inc("requests")

        if activity not in ACTIVITIES or color not in COLORS:
            stats.inc("invalid_requests")
            return jsonify(error="invalid activity or color", activities=ACTIVITIES, colors=COLORS), 404

        if not is_valid_xyz(z, x, y, config.max_zoom):
            stats.inc("invalid_requests")
            return jsonify(error="invalid XYZ tile coordinates"), 404

        path = cache_path(config, activity, color, z, x, y)
        cached = read_cache(path, config.cache_ttl)
        if cached is not None:
            stats.inc("cache_hits")
            logger.debug("Cache hit z=%s x=%s y=%s activity=%s color=%s", z, x, y, activity, color)
            return tile_response(cached, cache_status="HIT")

        stats.inc("cache_misses")
        url = f"{config.upstream.rstrip('/')}/{activity}/{color}/{z}/{x}/{y}.png"
        params = {"px": config.tile_size}
        if config.upstream_version:
            params["v"] = config.upstream_version

        try:
            upstream = session.get(
                url,
                params=params,
                timeout=(config.connect_timeout, config.read_timeout),
            )
            if upstream.status_code == 404:
                logger.debug("Upstream 404 for %s", url)
                return tile_response(empty_tile, cache_status="ERROR")
            upstream.raise_for_status()
            if not upstream.content.startswith(b"\x89PNG\r\n\x1a\n"):
                raise requests.RequestException("upstream did not return a PNG")

            data = upstream.content
            stats.inc("upstream_downloads")
            write_cache(path, data)
            logger.debug("Downloaded z=%s x=%s y=%s activity=%s color=%s", z, x, y, activity, color)
            return tile_response(data, cache_status="MISS")

        except requests.Timeout as exc:
            stats.inc("upstream_errors")
            logger.warning("Upstream timeout for z=%s x=%s y=%s: %s", z, x, y, exc)
            if config.error_mode == "http":
                return jsonify(error="upstream timeout"), 504
            return tile_response(empty_tile, cache_status="ERROR")
        except requests.RequestException as exc:
            stats.inc("upstream_errors")
            logger.warning("Upstream error for z=%s x=%s y=%s: %s", z, x, y, exc)
            if config.error_mode == "http":
                return jsonify(error="upstream error"), 502
            return tile_response(empty_tile, cache_status="ERROR")

    @app.get("/heatmap/<int:z>/<int:x>/<int:y>.png")
    def heatmap_default(z: int, x: int, y: int) -> Response:
        return serve_tile(config.activity, config.color, z, x, y)

    @app.get("/heatmap/<activity>/<color>/<int:z>/<int:x>/<int:y>.png")
    def heatmap_dynamic(activity: str, color: str, z: int, x: int, y: int) -> Response:
        return serve_tile(activity, color, z, x, y)

    @app.get("/health")
    def health() -> Response:
        return jsonify(
            status="ok",
            version=__version__,
            activity=config.activity,
            color=config.color,
            tile_size=config.tile_size,
            cache_enabled=config.cache_dir is not None,
        )

    @app.get("/stats")
    def stats_endpoint() -> Response:
        return jsonify(stats.snapshot())

    @app.get("/")
    def index() -> Response:
        host = config.host if config.host not in ("0.0.0.0", "::") else "127.0.0.1"
        base = f"http://{host}:{config.port}"
        return jsonify(
            name="local-proxy-strava-heatmap",
            version=__version__,
            default_xyz=f"{base}/heatmap/{{z}}/{{x}}/{{y}}.png",
            dynamic_xyz=f"{base}/heatmap/{{activity}}/{{color}}/{{z}}/{{x}}/{{y}}.png",
            activities=ACTIVITIES,
            colors=COLORS,
        )

    return app


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local proxy for Strava heatmap XYZ tiles")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--activity", choices=ACTIVITIES, default=os.getenv("LPSH_ACTIVITY", "all"))
    parser.add_argument("--color", choices=COLORS, default=os.getenv("LPSH_COLOR", "bluered"))
    parser.add_argument("--host", default=os.getenv("LPSH_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("LPSH_PORT", "5000")))
    parser.add_argument("--tile-size", type=int, choices=(256, 512), default=int(os.getenv("LPSH_TILE_SIZE", "256")))
    parser.add_argument("--max-zoom", type=int, default=int(os.getenv("LPSH_MAX_ZOOM", "16")))
    parser.add_argument("--cache-dir", default=os.getenv("LPSH_CACHE_DIR", "cache"))
    parser.add_argument("--cache-ttl", type=int, default=int(os.getenv("LPSH_CACHE_TTL", "86400")))
    parser.add_argument("--no-cache", action="store_true", default=env_bool("LPSH_NO_CACHE"))
    parser.add_argument("--connect-timeout", type=float, default=float(os.getenv("LPSH_CONNECT_TIMEOUT", "3.05")))
    parser.add_argument("--read-timeout", type=float, default=float(os.getenv("LPSH_READ_TIMEOUT", "10")))
    parser.add_argument("--error-mode", choices=("transparent", "http"), default=os.getenv("LPSH_ERROR_MODE", "transparent"))
    parser.add_argument("--source", choices=SOURCES, default=os.getenv("LPSH_SOURCE", "direct"), help="upstream preset (direct or nakarte)")
    parser.add_argument("--upstream", default=os.getenv("LPSH_UPSTREAM"), help="custom base URL before /activity/color/z/x/y.png")
    parser.add_argument("--upstream-version", default=os.getenv("LPSH_UPSTREAM_VERSION"), help="override the source's v query parameter; empty string omits it")
    parser.add_argument("--no-menu", action="store_true", help="skip the interactive activity and color selection")
    parser.add_argument("--debug", action="store_true", default=env_bool("LPSH_DEBUG"))
    parser.add_argument("--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR"), default=os.getenv("LPSH_LOG_LEVEL", "INFO"))
    return parser.parse_args(argv)


def choose_numbered(title: str, options: list[tuple[str, str]], default: str) -> str:
    """Fallback menu for Python environments without Questionary."""
    print(f"  {title}")
    for index, (label, value) in enumerate(options, 1):
        marker = " (predefinito)" if value == default else ""
        print(f"    {index}. {label}{marker}")
    while True:
        try:
            answer = input("  Numero (Invio per il predefinito): ").strip()
        except (EOFError, KeyboardInterrupt):
            raise SystemExit(130) from None
        if not answer:
            return default
        if answer.isdecimal() and 1 <= int(answer) <= len(options):
            return options[int(answer) - 1][1]
        print(f"  Inserisci un numero da 1 a {len(options)}.")


def choose_runtime_options(args: argparse.Namespace, argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Show a terminal menu only for values not supplied explicitly on the CLI."""
    if args.no_menu or not (sys.stdin.isatty() and sys.stdout.isatty()):
        return args

    try:
        import questionary
    except ImportError:
        questionary = None

    supplied = sys.argv[1:] if argv is None else argv

    def specified(option: str) -> bool:
        return any(value == option or value.startswith(option + "=") for value in supplied)

    style = questionary.Style([
        ("qmark", "fg:cyan bold"),
        ("question", "bold"),
        ("pointer", "fg:cyan bold"),
        ("highlighted", "fg:cyan bold"),
        ("selected", "fg:green"),
    ]) if questionary is not None else None
    print("\n  STRAVA HEATMAP  ·  Configurazione")
    print("  Usa ↑/↓ e Invio per scegliere; Ctrl+C per uscire.\n" if questionary else
          "  Scegli un numero e premi Invio; Ctrl+C per uscire.\n")

    if not specified("--source") and not specified("--upstream") and not os.getenv("LPSH_UPSTREAM"):
        sources = [("Server predefinito · 89.168.43.214", "direct"),
                   ("Nakarte · proxy.nakarte.me", "nakarte")]
        args.source = (questionary.select(
            "Sorgente",
            choices=[questionary.Choice(label, value=value) for label, value in sources],
            default=args.source,
            instruction="(↑/↓, Invio)",
            style=style,
        ).ask() if questionary else choose_numbered("Sorgente", sources, args.source))
        if args.source is None:
            raise SystemExit(130)

    if not specified("--activity"):
        activities = [
            ("Tutte · all", "all"),
            ("Corsa · run", "run"),
            ("Bici · ride", "ride"),
            ("Sport invernali · winter", "winter"),
            ("Sport acquatici · water", "water"),
        ]
        args.activity = (questionary.select(
            "Attività",
            choices=[questionary.Choice(label, value=value) for label, value in activities],
            default=args.activity,
            instruction="(↑/↓, Invio)",
            style=style,
        ).ask() if questionary else choose_numbered("Attività", activities, args.activity))
        if args.activity is None:
            raise SystemExit(130)

    if not specified("--color"):
        args.color = (questionary.select(
            "Colore",
            choices=[questionary.Choice(color, value=color) for color in COLORS],
            default=args.color,
            instruction="(↑/↓, Invio)",
            style=style,
        ).ask() if questionary else choose_numbered("Colore", [(color, color) for color in COLORS], args.color))
        if args.color is None:
            raise SystemExit(130)

    print(f"\n  Layer selezionato: {args.activity} / {args.color} · sorgente: {args.source}\n")
    return args


def config_from_args(args: argparse.Namespace) -> Config:
    if not (1 <= args.port <= 65535):
        raise SystemExit("--port must be between 1 and 65535")
    if args.max_zoom < 0:
        raise SystemExit("--max-zoom must be >= 0")
    if args.cache_ttl < 0:
        raise SystemExit("--cache-ttl must be >= 0")
    if args.connect_timeout <= 0 or args.read_timeout <= 0:
        raise SystemExit("timeouts must be > 0")
    preset_upstream, preset_version, preset_referer = SOURCES[args.source]
    upstream = args.upstream if args.upstream is not None else preset_upstream
    if not upstream.startswith(("http://", "https://")):
        raise SystemExit("--upstream must be an http:// or https:// URL")

    return Config(
        activity=args.activity,
        color=args.color,
        host=args.host,
        port=args.port,
        tile_size=args.tile_size,
        max_zoom=args.max_zoom,
        cache_dir=None if args.no_cache else Path(args.cache_dir).expanduser(),
        cache_ttl=args.cache_ttl,
        connect_timeout=args.connect_timeout,
        read_timeout=args.read_timeout,
        error_mode=args.error_mode,
        upstream=upstream,
        upstream_version=args.upstream_version if args.upstream_version is not None else preset_version,
        referer=preset_referer if args.upstream is None else None,
    )


def available_port(host: str, port: int) -> bool:
    """Check whether the HTTP server can bind to this address."""
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    try:
        with socket.socket(family, socket.SOCK_STREAM) as sock:
            sock.bind((host, port))
        return True
    except OSError:
        return False


# WSGI-compatible application with safe non-interactive defaults.
app = create_app()


def main(argv: Optional[list[str]] = None) -> None:
    args = parse_args(argv)
    args = choose_runtime_options(args, argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = config_from_args(args)
    cli_args = argv if argv is not None else sys.argv[1:]
    explicit_port = any(arg == "--port" or arg.startswith("--port=") for arg in cli_args)
    if config.port == 5000 and not explicit_port and "LPSH_PORT" not in os.environ:
        if not available_port(config.host, config.port):
            for port in range(5001, 5011):
                if available_port(config.host, port):
                    logger.warning("Port 5000 is in use; using port %s instead", port)
                    config = replace(config, port=port)
                    break
            else:
                raise SystemExit("Ports 5000–5010 are in use; specify an available port with --port")
    runtime_app = create_app(config)
    display_host = "127.0.0.1" if config.host in ("0.0.0.0", "::") else config.host
    logger.info("XYZ URL: http://%s:%s/heatmap/{z}/{x}/{y}.png", display_host, config.port)

    logger.info(
        "Starting local-proxy-strava-heatmap %s on %s:%s (activity=%s, color=%s, cache=%s)",
        __version__,
        config.host,
        config.port,
        config.activity,
        config.color,
        config.cache_dir if config.cache_dir is not None else "disabled",
    )
    runtime_app.run(
        host=config.host,
        port=config.port,
        debug=args.debug,
        use_reloader=False,
    )


if __name__ == "__main__":
    main()
