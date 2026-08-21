"""Local web server and JSON REST API for the Ryan Project Suites control plane."""

from __future__ import annotations

import http.server
import json
import socketserver
import urllib.parse
from pathlib import Path
from typing import Any

from .contracts import CONTRACTS, ContractError, generate_sample, validate_contract
from .registry import (
    SUITES_ROOT,
    get_dependency_graph,
    get_live_drift_report,
    get_portfolio_summary,
    get_project,
    get_suite,
    load_ledger,
    load_nested_ledger,
    load_suites,
    validate_registry,
)
from .waves import WaveRunner

WEB_DIR = Path(__file__).resolve().parent / "web"
MAX_JSON_BODY_BYTES = 1_048_576
LOOPBACK_HOSTNAMES = frozenset({"localhost", "127.0.0.1", "::1"})


class RequestBodyError(ValueError):
    """Client request-body failure with an intentional HTTP response status."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


class PortfolioAPIHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP request handler providing REST API endpoints and serving static UI assets."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress noisy standard request logging in test/daemon mode
        pass

    def _send_json(self, status: int, data: Any) -> None:
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> Any:
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            return {}
        try:
            length = int(raw_length)
        except (TypeError, ValueError):
            raise RequestBodyError(400, "Content-Length must be a non-negative integer") from None
        if length < 0:
            raise RequestBodyError(400, "Content-Length must be a non-negative integer")
        if length > MAX_JSON_BODY_BYTES:
            raise RequestBodyError(
                413,
                f"JSON request body exceeds the {MAX_JSON_BODY_BYTES}-byte limit",
            )
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        if len(raw) != length:
            raise RequestBodyError(400, "Request body ended before Content-Length bytes were received")
        try:
            return json.loads(raw.decode("utf-8"))
        except UnicodeDecodeError:
            raise RequestBodyError(400, "Request body must be UTF-8 JSON") from None
        except json.JSONDecodeError as error:
            raise RequestBodyError(400, f"Invalid JSON syntax: {error.msg}") from None

    def _execution_request_is_trusted(self) -> bool:
        """Reject browser cross-origin execution while retaining headerless API clients."""
        fetch_site = self.headers.get("Sec-Fetch-Site")
        if fetch_site not in (None, "same-origin"):
            return False
        origin = self.headers.get("Origin")
        if origin is None:
            return True
        host = self.headers.get("Host")
        return bool(host and origin.rstrip("/") == f"http://{host}")

    def _request_host_is_loopback(self) -> bool:
        """Reject DNS-rebinding: a non-loopback Host means the request was aimed here by name."""
        hostname = urllib.parse.urlsplit(f"//{self.headers.get('Host') or ''}").hostname
        return hostname in LOOPBACK_HOSTNAMES

    def _reject_non_loopback_host(self) -> bool:
        if self._request_host_is_loopback():
            return False
        self._send_json(403, {"error": "requests must address this server as a loopback host"})
        return True

    def do_OPTIONS(self) -> None:
        if self._reject_non_loopback_host():
            return
        self.send_response(204)
        self.end_headers()

    def do_GET(self) -> None:
        if self._reject_non_loopback_host():
            return
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        query = urllib.parse.parse_qs(parsed.query)

        if path.startswith("/api"):
            self._handle_api_get(path, query)
            return

        # Serve static assets from WEB_DIR
        if path == "" or path == "/":
            self.path = "/index.html"
        super().do_GET()

    def _handle_api_get(self, path: str, query: dict[str, list[str]]) -> None:
        try:
            if path == "/api/summary":
                self._send_json(200, get_portfolio_summary())
            elif path == "/api/suites":
                self._send_json(200, list(load_suites().values()))
            elif path.startswith("/api/suites/"):
                suite_id = path.removeprefix("/api/suites/")
                if not suite_id or "/" in suite_id:
                    self._send_json(404, {"error": f"Unknown endpoint: {path}"})
                    return
                suite = get_suite(suite_id)
                if suite:
                    self._send_json(200, suite)
                else:
                    self._send_json(404, {"error": f"Suite '{suite_id}' not found"})
            elif path == "/api/projects":
                ledger = load_ledger()
                self._send_json(200, ledger.get("projects", []))
            elif path.startswith("/api/projects/"):
                proj_name = path.removeprefix("/api/projects/")
                if not proj_name or "/" in proj_name:
                    self._send_json(404, {"error": f"Unknown endpoint: {path}"})
                    return
                proj = get_project(proj_name)
                if proj:
                    self._send_json(200, proj)
                else:
                    self._send_json(404, {"error": f"Project '{proj_name}' not found"})
            elif path == "/api/nested":
                nested = load_nested_ledger()
                self._send_json(200, nested.get("repositories", []))
            elif path == "/api/drift":
                self._send_json(200, get_live_drift_report())
            elif path == "/api/graph":
                self._send_json(200, get_dependency_graph())
            elif path == "/api/validate":
                report = validate_registry(check_live=True)
                self._send_json(200, {"ok": report.ok, "errors": report.errors, "warnings": report.warnings})
            elif path == "/api/contracts":
                specs = {
                    k: {
                        "name": k,
                        "description": v.description,
                        "required": sorted(v.required),
                        "list_fields": sorted(v.list_fields),
                        "mapping_fields": sorted(v.mapping_fields),
                        "enums": {ek: sorted(ev) for ek, ev in (v.enums or {}).items()},
                    }
                    for k, v in CONTRACTS.items()
                }
                self._send_json(200, specs)
            elif path.startswith("/api/contracts/") and path.endswith("/sample"):
                parts = path.split("/")
                if len(parts) != 5 or not parts[3]:
                    self._send_json(404, {"error": f"Unknown endpoint: {path}"})
                    return
                contract_name = parts[3]
                try:
                    sample = generate_sample(contract_name)
                    self._send_json(200, sample)
                except ContractError as exc:
                    self._send_json(400, {"error": str(exc)})
            elif path == "/api/waves":
                run_live = query.get("run", ["false"])[0].lower() in ("true", "1")
                if run_live:
                    self._send_json(405, {"error": "Live wave execution requires the POST run endpoint"})
                    return
                # Return instant manifest-backed wave definitions and cached status (<2ms response)
                suites = load_suites()
                payload = []
                for s in suites.values():
                    s_id = s.get("id", "")
                    for w in s.get("waves", []):
                        w_id = w.get("id", "")
                        w_status = w.get("status", "specified")
                        ev_rel = w.get("evidence", "")
                        ev_file = SUITES_ROOT / ev_rel if ev_rel else None
                        has_ev = bool(ev_file and ev_file.is_file())
                        is_passed = (w_status == "complete")
                        method_name = f"_run_{s_id.replace('-', '_')}_{w_id.lower()}"
                        has_runner = hasattr(WaveRunner, method_name)
                        claim_kind = w.get("recovery_claim", {}).get("kind")
                        if is_passed and claim_kind == "runtime":
                            exec_kind = "verified_runtime_recovery"
                        elif is_passed:
                            exec_kind = "verified_analysis"
                        else:
                            exec_kind = "prototype_check" if has_runner else "unintegrated_specification"
                        payload.append({
                            "suite_id": s_id,
                            "wave_id": w_id,
                            "order": w.get("order", 0),
                            "status": w_status,
                            "objective": w.get("objective", ""),
                            "acceptance": w.get("acceptance", ""),
                            "passed": is_passed,
                            "runner_available": has_runner,
                            "execution_kind": exec_kind,
                            "message": f"Wave {w_id}: {w.get('objective', '')}",
                            "evidence_path": str(ev_file) if has_ev else None,
                        })
                self._send_json(200, payload)
            elif path.startswith("/api/evidence"):
                # Read evidence file from query
                file_param = query.get("file", [""])[0]
                if not file_param:
                    self._send_json(400, {"error": "Missing 'file' query parameter"})
                    return
                # Sanitize file path
                clean_path = Path(file_param)
                if not clean_path.is_absolute():
                    target_file = (SUITES_ROOT / clean_path).resolve()
                else:
                    target_file = clean_path.resolve()

                root_resolved = SUITES_ROOT.resolve()
                if (
                    not target_file.is_file()
                    or not target_file.is_relative_to(root_resolved)
                    or "evidence" not in target_file.relative_to(root_resolved).parts
                ):
                    self._send_json(404, {"error": "Evidence file not found or outside evidence scope"})
                    return
                content = target_file.read_text(encoding="utf-8")
                self._send_json(200, {"path": str(target_file), "content": content})
            else:
                self._send_json(404, {"error": f"Unknown endpoint: {path}"})
        except Exception:
            self._send_json(500, {"error": "Internal server error"})

    def do_POST(self) -> None:
        if self._reject_non_loopback_host():
            return
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")

        try:
            if path.startswith("/api/contracts/") and path.endswith("/validate"):
                parts = path.split("/")
                if len(parts) != 5 or not parts[3]:
                    self._send_json(404, {"error": f"Unknown POST endpoint: {path}"})
                    return
                contract_name = parts[3]
                body = self._read_json_body()
                try:
                    validated = validate_contract(contract_name, body)
                    self._send_json(200, {"ok": True, "validated": validated})
                except ContractError as exc:
                    self._send_json(400, {"ok": False, "error": str(exc)})
            elif path.startswith("/api/waves/") and path.endswith("/run"):
                parts = path.split("/")
                if len(parts) != 6 or not parts[3] or not parts[4]:
                    self._send_json(404, {"error": f"Unknown POST endpoint: {path}"})
                    return
                suite_id = parts[3]
                wave_id = parts[4]
                query_params = urllib.parse.parse_qs(parsed.query)
                record_param = query_params.get("record", ["false"])[0].lower() in ("true", "1")
                # Loopback binding does not stop another site blind-POSTing here. Execution
                # itself launches local subprocesses, even when evidence recording is disabled.
                if not self._execution_request_is_trusted():
                    self._send_json(403, {"error": "cross-origin wave execution is refused"})
                    return
                full_param = query_params.get("full", ["false"])[0].lower() in ("true", "1")
                # Ephemeral execution by default; only mutate evidence files on explicit record request
                res = WaveRunner.run_wave(suite_id, wave_id, write_evidence=record_param, full=full_param)
                status_code = 404 if res.execution_kind == "error" else 200
                self._send_json(status_code, {
                    "suite_id": res.suite_id,
                    "wave_id": res.wave_id,
                    "passed": res.passed,
                    "prototype_passed": res.prototype_passed,
                    "execution_kind": res.execution_kind,
                    "message": res.message,
                    "record_requested": record_param,
                    "recorded": res.evidence_path is not None,
                    "evidence_path": res.evidence_path,
                    "data": res.data,
                })
            else:
                self._send_json(404, {"error": f"Unknown POST endpoint: {path}"})
        except RequestBodyError as error:
            self._send_json(error.status, {"error": str(error)})
        except Exception:
            self._send_json(500, {"error": "Internal server error"})


class ThreadedPortfolioServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True


def create_server(port: int = 8383) -> socketserver.TCPServer:
    """Create a configured multi-threaded HTTP server for the portfolio control plane."""
    server = ThreadedPortfolioServer(("127.0.0.1", port), PortfolioAPIHandler)
    return server


def serve(port: int = 8383) -> None:
    """Start local web server loop."""
    server = create_server(port)
    print(f"Ryan Project Suites Dashboard serving at http://localhost:{port}/")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping dashboard server...")
    finally:
        server.server_close()
