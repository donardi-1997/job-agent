from __future__ import annotations

import argparse

from job_agent.enhanced_dashboard import run_dashboard


def main() -> None:
	parser = argparse.ArgumentParser(description="Run Job Agent locally")
	parser.add_argument("--host", default="127.0.0.1", help="Dashboard host (default: 127.0.0.1)")
	parser.add_argument("--port", default=8765, type=int, help="Dashboard port (default: 8765)")
	parser.add_argument("--no-browser", action="store_true", help="Do not open the browser automatically")
	args = parser.parse_args()

	run_dashboard(host=args.host, port=args.port, open_browser=not args.no_browser)


if __name__ == "__main__":
	main()
