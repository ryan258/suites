"""Local web server and JSON REST API for the Ryan Project Suites control plane."""

from __future__ import annotations

import http.server
import json
import socketserver
import traceback
import urllib.parse
from pathlib import Path
from typing import Any

from .ai import AIError, get_ai_status, request_assistance
from .contracts import CONTRACTS, ContractError, generate_sample, validate_contract
from .chains import ChainError, run_chain
from .engine_actions import (
    EngineActionError,
    argument_redaction_policy,
    get_action_spec,
    list_actions,
    redact_sensitive_arguments,
    run_action,
)
from .registry import (
    SUITES_ROOT,
    build_evidence_ownership_index,
    declared_evidence_owner,
    get_dependency_graph,
    get_live_drift_report,
    get_portfolio_summary,
    get_project,
    get_suite,
    get_wave_evidence_status,
    load_ledger,
    load_nested_ledger,
    load_suites,
    validate_registry,
)
from .waves import WaveRunner, classify_wave_spec

WEB_DIR = Path(__file__).resolve().parent / "web"
MAX_JSON_BODY_BYTES = 1_048_576
LOOPBACK_HOSTNAMES = frozenset({"localhost", "127.0.0.1", "::1"})
DOCUMENTS = {
    "project-bible": SUITES_ROOT / "docs" / "PROJECT-BIBLE.md",
    "migration-program": SUITES_ROOT / "docs" / "MIGRATION-PROGRAM.md",
    "recovery-standard": SUITES_ROOT / "docs" / "RECOVERY-STANDARD.md",
    "roadmap": SUITES_ROOT / "docs" / "ROADMAP.md",
}


class RequestBodyError(ValueError):
    """Client request-body failure with an intentional HTTP response status."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def _is_loopback_host_header(value: str | None) -> bool:
    """Validate the HTTP Host grammar subset accepted by this loopback-only server."""
    if not isinstance(value, str) or not value or any(
        ord(character) < 33 or ord(character) == 127 for character in value
    ):
        return False
    try:
        parsed = urllib.parse.urlsplit(f"//{value}")
        # Accessing port is itself validation: malformed and out-of-range values raise.
        parsed.port
    except ValueError:
        return False
    return (
        parsed.hostname in LOOPBACK_HOSTNAMES
        and parsed.username is None
        and parsed.password is None
        and not parsed.path
        and not parsed.query
        and not parsed.fragment
    )


class PortfolioAPIHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP request handler providing REST API endpoints and serving static UI assets."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress noisy standard request logging in test/daemon mode
        pass

    def end_headers(self) -> None:
        """Apply a browser-safe local policy to API and static responses alike."""
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
        )
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; connect-src 'self'; img-src 'self' data:; "
            "object-src 'none'; frame-ancestors 'none'; base-uri 'none'; "
            "form-action 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'",
        )
        super().end_headers()

    def _send_json(self, status: int, data: Any) -> None:
        try:
            body = json.dumps(data, indent=2, allow_nan=False).encode("utf-8")
        except (TypeError, ValueError):
            status = 500
            body = b'{"error":"Response could not be encoded as strict JSON"}'
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
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
            return json.loads(
                raw.decode("utf-8"),
                parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
            )
        except UnicodeDecodeError:
            raise RequestBodyError(400, "Request body must be UTF-8 JSON") from None
        except json.JSONDecodeError as error:
            raise RequestBodyError(400, f"Invalid JSON syntax: {error.msg}") from None
        except ValueError:
            raise RequestBodyError(400, "Invalid JSON syntax: non-finite numbers are not allowed") from None

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

    def _reject_untrusted_donor_scan(self) -> bool:
        """Refuse a cross-origin GET that would spawn donor git across the portfolio.

        Loopback binding and the Host check stop DNS rebinding, but neither stops a page the
        operator merely *visits* from issuing `fetch("http://127.0.0.1:8383/api/drift")`. The
        response is CORS-blocked, so nothing leaks -- but the scan still runs, and it is ~4s
        of git subprocesses across every donor checkout on a threaded server with no rate
        limit. Reads that only touch loaded manifests stay open; these two do not.
        """
        if self._execution_request_is_trusted():
            return False
        self._send_json(403, {"error": "cross-origin live donor scans are refused"})
        return True

    def _request_host_is_loopback(self) -> bool:
        """Reject DNS-rebinding: a non-loopback Host means the request was aimed here by name."""
        return _is_loopback_host_header(self.headers.get("Host"))

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
                proj_name = urllib.parse.unquote(path.removeprefix("/api/projects/"))
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
                if self._reject_untrusted_donor_scan():
                    return
                self._send_json(200, get_live_drift_report())
            elif path == "/api/graph":
                self._send_json(200, get_dependency_graph())
            elif path == "/api/validate":
                fast = query.get("fast", ["false"])[0].lower() in ("true", "1")
                if not fast and self._reject_untrusted_donor_scan():
                    return
                report = validate_registry(check_live=not fast)
                self._send_json(200, {"ok": report.ok, "errors": report.errors, "warnings": report.warnings})
            elif path == "/api/ai/status":
                try:
                    self._send_json(200, get_ai_status())
                except AIError as error:
                    self._send_json(error.http_status, {"ok": False, "error": error.as_dict()})
            elif path == "/api/security-policy":
                self._send_json(200, {"argument_redaction": argument_redaction_policy()})
            elif path == "/api/docs":
                self._send_json(200, [
                    {"id": document_id, "name": document_path.stem.replace("-", " ").title()}
                    for document_id, document_path in sorted(DOCUMENTS.items())
                ])
            elif path.startswith("/api/docs/"):
                document_id = urllib.parse.unquote(path.removeprefix("/api/docs/"))
                document_path = DOCUMENTS.get(document_id)
                if not document_path or not document_path.is_file():
                    self._send_json(404, {"error": "Document not found"})
                    return
                self._send_json(200, {
                    "id": document_id,
                    "name": document_path.name,
                    "content": document_path.read_text(encoding="utf-8"),
                })
            elif path == "/api/engines":
                self._send_json(200, list_actions())
            elif path.startswith("/api/engines/"):
                suite_id = urllib.parse.unquote(path[len("/api/engines/"):]).strip("/")
                try:
                    self._send_json(200, list_actions(suite_id))
                except EngineActionError as exc:
                    self._send_json(404, {"error": str(exc)})
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
                # Return manifest-backed definitions with current receipt validation, without
                # launching any live wave runner from a GET request.
                suites = load_suites()
                ownership_index = build_evidence_ownership_index(suites)
                payload = []
                for s in suites.values():
                    s_id = s.get("id", "")
                    for w in s.get("waves", []):
                        w_id = w.get("id", "")
                        w_status = w.get("status", "specified")
                        evidence_status = get_wave_evidence_status(s_id, w, ownership_index)
                        manifest_complete = w_status == "complete"
                        is_passed = manifest_complete and evidence_status["evidence_valid"]
                        has_runner = WaveRunner.has_runner(s_id, w_id)
                        exec_kind = (
                            classify_wave_spec(w, has_runner=has_runner)
                            if evidence_status["evidence_valid"] or not manifest_complete
                            else "unverifiable_evidence"
                        )
                        claim = w.get("recovery_claim", {}) or {}
                        payload.append({
                            "suite_id": s_id,
                            "wave_id": w_id,
                            "order": w.get("order", 0),
                            "status": w_status,
                            "manifest_complete": manifest_complete,
                            "objective": w.get("objective", ""),
                            "acceptance": w.get("acceptance", ""),
                            "passed": is_passed,
                            "evidence_valid": evidence_status["evidence_valid"],
                            "evidence_errors": evidence_status["evidence_errors"],
                            "claim_kind": claim.get("kind"),
                            "claim_level": claim.get("level"),
                            # The registry knows exactly which live run each completed wave
                            # still owes. Dropping it here left the dashboard able to report
                            # "42 follow-ups remain" with no way to see any of them.
                            "runtime_followup": w.get("runtime_followup", ""),
                            # Whether a deeper run is even runnable is a property of the
                            # runner, and only the backend can see it. Without this the
                            # browser had to guess, and it guessed `--full` for every wave.
                            "runtime_followup_command": WaveRunner.full_depth_command(s_id, w_id),
                            "verification_depth": "retained_receipt" if is_passed else "none",
                            "runner_available": has_runner,
                            "execution_kind": exec_kind,
                            "message": f"Wave {w_id}: {w.get('objective', '')}",
                            "evidence_path": evidence_status["evidence_path"],
                        })
                self._send_json(200, payload)
            elif path.startswith("/api/evidence"):
                # Read evidence file from query
                file_param = query.get("file", [""])[0]
                if not file_param:
                    self._send_json(400, {"error": "Missing 'file' query parameter"})
                    return
                requested = Path(file_param)
                target_file = requested.resolve() if requested.is_absolute() else (SUITES_ROOT / requested).resolve()
                owner = declared_evidence_owner(target_file)
                if not target_file.is_file() or owner is None:
                    self._send_json(404, {"error": "Evidence file not found or outside evidence scope"})
                    return
                content = target_file.read_text(encoding="utf-8")
                self._send_json(200, {"path": str(target_file), "content": content})
            else:
                self._send_json(404, {"error": f"Unknown endpoint: {path}"})
        except Exception:
            traceback.print_exc()
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
            elif path == "/api/ai/assist":
                if not self._execution_request_is_trusted():
                    self._send_json(403, {"error": "cross-origin AI execution is refused"})
                    return
                body = self._read_json_body()
                if not isinstance(body, dict):
                    self._send_json(400, {"error": "AI request body must be a JSON object"})
                    return
                try:
                    result = request_assistance(
                        body.get("prompt"),
                        suite_id=body.get("suite_id"),
                        role=body.get("role", "orchestrator"),
                        context=body.get("context"),
                        history=body.get("history"),
                    )
                except AIError as error:
                    self._send_json(error.http_status, {"ok": False, "error": error.as_dict()})
                    return
                self._send_json(200, result)
            elif path == "/api/chains/run":
                if not self._execution_request_is_trusted():
                    self._send_json(403, {"error": "cross-origin chain execution is refused"})
                    return
                body = self._read_json_body()
                steps = body.get("steps") if isinstance(body, dict) else body
                try:
                    self._send_json(200, run_chain(steps))
                except ChainError as exc:
                    self._send_json(400, exc.as_dict())
            elif path.startswith("/api/engines/") and path.endswith("/run"):
                if not self._execution_request_is_trusted():
                    self._send_json(403, {"error": "cross-origin engine execution is refused"})
                    return
                parts = [urllib.parse.unquote(part) for part in path[len("/api/engines/"):-len("/run")].split("/") if part]
                if len(parts) != 2:
                    self._send_json(404, {"error": "expected /api/engines/<suite>/<action>/run"})
                    return
                suite_id, action = parts
                arguments = self._read_json_body()
                if arguments is None:
                    arguments = {}
                try:
                    result = run_action(suite_id, action, arguments)
                except EngineActionError as exc:
                    self._send_json(400, {"error": str(exc)})
                    return
                except Exception as exc:  # engine raised on its own inputs
                    self._send_json(422, {"error": f"{type(exc).__name__}: {exc}", "suite": suite_id, "action": action})
                    return
                action_spec = get_action_spec(suite_id, action)
                self._send_json(200, {
                    "suite": suite_id,
                    "action": action,
                    "arguments": redact_sensitive_arguments(arguments),
                    "emits": action_spec["emits"],
                    "output_kind": action_spec["output_kind"],
                    "result": result,
                })
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
                # A gate outcome alone does not say how much the wave claims to have shown,
                # so the run result carries the promotion level the caller should display
                # beside it.
                ran_suite = get_suite(suite_id) or {}
                ran_wave = next(
                    (w for w in ran_suite.get("waves", []) if w.get("id") == wave_id), {}
                )
                self._send_json(status_code, {
                    "suite_id": res.suite_id,
                    "wave_id": res.wave_id,
                    "passed": res.passed,
                    "prototype_passed": res.prototype_passed,
                    "execution_kind": res.execution_kind,
                    "claim_kind": res.claim_kind,
                    "claim_level": res.claim_level,
                    "runtime_followup": ran_wave.get("runtime_followup", ""),
                    "message": res.message,
                    "record_requested": record_param,
                    "recorded": res.record_status == "recorded",
                    "record_status": res.record_status,
                    "record_request_succeeded": not record_param or res.record_status == "recorded",
                    "record_note": res.record_note,
                    "evidence_path": res.evidence_path,
                    "data": res.data,
                })
            else:
                self._send_json(404, {"error": f"Unknown POST endpoint: {path}"})
        except RequestBodyError as error:
            self._send_json(error.status, {"error": str(error)})
        except Exception:
            traceback.print_exc()
            self._send_json(500, {"error": "Internal server error"})


class ThreadedPortfolioServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


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
