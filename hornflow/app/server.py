"""The local host (M4): a standard-library HTTP server for the UI and its API.

Deliberately small and dependency-free.  It does three things:

* serves the run's `viewer/` folder as static files (the same offline page the
  snapshot mode uses);
* exposes the action surface in `hornflow.app.actions` as JSON;
* never lets a request name a filesystem path - only a *definition name*, a *run
  id* or an *export sub-directory*, each resolved through `safe_under()`.

Run it with::

    python3 -m hornflow.app --run-dir runs/<run_id>

It binds ``127.0.0.1`` by default: this is a local design tool, not a service.
"""

from __future__ import annotations

import json
import mimetypes
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from .actions import ApiError, AppActions, safe_under

MAX_BODY = 256 * 1024


class _Handler(BaseHTTPRequestHandler):
    server_version = "HornFlow/1.0"
    actions: AppActions = None          # set on the subclass by create_server

    # ------------------------------------------------------------- plumbing
    def log_message(self, fmt, *args):                 # quieter, still useful
        sys.stderr.write("[hornflow-app] %s - %s\n" % (self.address_string(),
                                                       fmt % args))

    def _json(self, obj, status: int = 200) -> None:
        body = (json.dumps(obj, sort_keys=True, default=str) + "\n").encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > MAX_BODY:
            raise ApiError("body_too_large",
                           f"request body over {MAX_BODY} bytes", status=413)
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise ApiError("bad_json",
                           f"the request body is not JSON: {exc}") from None
        if not isinstance(data, dict):
            raise ApiError("bad_json", "the request body must be a JSON object")
        return data

    # --------------------------------------------------------------- routes
    def do_GET(self):                                  # noqa: N802 - stdlib name
        path = urlparse(self.path).path
        try:
            return self._handle_get(path)
        except ApiError as exc:
            return self._json(exc.to_dict(), exc.status)
        except Exception as exc:                        # noqa: BLE001
            self.log_message("error %s: %s", path, exc)
            return self._fault()

    def do_POST(self):                                 # noqa: N802 - stdlib name
        path = urlparse(self.path).path
        try:
            return self._handle_post(path)
        except ApiError as exc:
            return self._json(exc.to_dict(), exc.status)
        except Exception as exc:                        # noqa: BLE001
            self.log_message("error %s: %s", path, exc)
            return self._fault()

    def _fault(self):
        # never leak a traceback to the UI; the server log keeps the detail
        return self._json({"error": {
            "code": "internal",
            "message": "the server hit an internal error; see the server log"}}, 500)

    def _handle_get(self, path: str):
        if path == "/api/health":
            return self._json({"ok": True, "root": str(self.actions.root)})
        if path == "/api/view":
            return self._json(self.actions.view())
        if path == "/api/progress":
            return self._json(self.actions.progress())
        if path == "/api/definitions":
            return self._json({"definitions": self.actions.brief.definitions()})
        if path == "/api/runs":
            return self._json({"runs": self.actions.runs(),
                               "current": (self.actions.run_dir.name
                                           if self.actions.run_dir else None)})
        return self._static(path)

    def _handle_post(self, path: str):
        body = self._read_body()
        if path == "/api/brief":
            out = self.actions.save_draft(body.get("values") or body)
        elif path == "/api/brief/freeze":
            out = self.actions.freeze(body.get("values") or body)
        elif path == "/api/run":
            out = self.actions.start_run(body.get("definition"))
        elif path == "/api/import":
            out = self.actions.import_vips(subdir=body.get("subdir"),
                                           tolerance_db=body.get("tolerance_db")
                                           or 6.0)
        elif path == "/api/decision":
            out = self.actions.decision(kind=body.get("kind"),
                                        reason=body.get("reason"),
                                        note=body.get("note", ""),
                                        actor=body.get("actor"))
        elif path == "/api/select":
            out = dict(self.actions.select_run(body.get("run_id")))
            out["view"] = self.actions.view()
        else:
            raise ApiError("unknown_endpoint", f"no such endpoint {path}",
                           status=404)
        return self._json(out)

    def _doc_root(self):
        """The folder static files come from - resolved per request.

        It must not be cached: starting a run changes which run is current, and a
        cached root would keep serving the previous run's page.
        """
        run_dir = getattr(self.actions, "run_dir", None)
        if run_dir is None:
            return None
        cand = Path(run_dir) / "deliverables"
        return cand if cand.is_dir() else Path(run_dir)

    # --------------------------------------------------------------- static
    def _static(self, path: str) -> None:
        root = self._doc_root()
        if root is None:
            raise ApiError("no_document_root", "there is no run to serve",
                           status=404)
        rel = unquote(path).lstrip("/")
        if rel in ("", "index.html"):
            rel = "viewer/viewer.html"
        try:
            target = safe_under(root, *[p for p in rel.split("/") if p])
        except ApiError:
            return self._json({"error": {"code": "path_rejected",
                                         "message": "not an allowed path"}}, 400)
        if target.is_dir():
            target = target / "index.html"
        if not target.is_file():
            return self._json({"error": {"code": "not_found",
                                         "message": f"no such file: {rel}"}}, 404)
        data = target.read_bytes()
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/json",
                                                  "application/javascript"):
            ctype += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def create_server(actions: AppActions, *, host: str = "127.0.0.1", port: int = 0):
    """Build (but do not start) the server.  ``port=0`` picks a free port."""
    handler = type("HornFlowHandler", (_Handler,), {"actions": actions})
    httpd = ThreadingHTTPServer((host, int(port)), handler)
    httpd.daemon_threads = True
    return httpd


def serve(actions: AppActions, *, host: str = "127.0.0.1", port: int = 8765,
          open_browser: bool = False, printer=print) -> int:
    httpd = create_server(actions, host=host, port=port)
    bound_host, bound_port = httpd.server_address[:2]
    url = f"http://{bound_host}:{bound_port}/viewer/viewer.html?tab=workflow"
    printer(f"serving {bound_host}:{bound_port}")
    if actions.run_dir:
        printer(f"run:     {actions.run_dir}")
    printer(f"open:    {url}")
    if actions.run_dir is None:
        printer("(no run yet - answer the brief in the page and start one, or open "
                "an existing run with --run-dir)")
    printer("stop with Ctrl-C")
    if open_browser:
        import webbrowser

        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        printer("\nstopping")
    finally:
        httpd.server_close()
    return 0


