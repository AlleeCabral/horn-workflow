"""`python3 -m hornflow.app` - start the local host.

    python3 -m hornflow.app --run-dir runs/<run_id>
    python3 -m hornflow.app --base params/horn_jbl_1200b.yaml --open
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .actions import AppActions
from .server import serve


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="python3 -m hornflow.app",
        description="HornFlow local host: the UI plus its API, on 127.0.0.1.")
    p.add_argument("--project", default=".",
                   help="project root (default: the working directory)")
    p.add_argument("--run-dir", default=None,
                   help="the run to open (default: the newest under --run-root)")
    p.add_argument("--run-root", default="runs", help="where runs live")
    p.add_argument("--base", default=None,
                   help="the definition a frozen brief is built on top of")
    p.add_argument("--definitions-dir", default=None,
                   help="where definition files live (default: <project>/params)")
    p.add_argument("--author", default=None, help="recorded on the frozen brief")
    p.add_argument("--host", default="127.0.0.1",
                   help="bind address (default: 127.0.0.1, local only)")
    p.add_argument("--port", type=int, default=8765, help="port (0 picks a free one)")
    p.add_argument("--open", action="store_true", help="open a browser window")
    args = p.parse_args(argv)

    root = Path(args.project).resolve()
    if not root.is_dir():
        p.error(f"--project {args.project!r} is not a directory")
    try:
        actions = AppActions(root, run_root=args.run_root,
                             base_definition=args.base,
                             definitions_dir=args.definitions_dir,
                             run_dir=args.run_dir, author=args.author)
    except FileNotFoundError as exc:
        print(f"hornflow.app: {exc}", file=sys.stderr)
        return 2
    return serve(actions, host=args.host, port=args.port,
                 open_browser=args.open)


if __name__ == "__main__":
    raise SystemExit(main())
