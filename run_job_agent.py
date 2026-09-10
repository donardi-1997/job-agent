from __future__ import annotations

import argparse
import os


def main() -> None:
	parser = argparse.ArgumentParser(description="Run Job Agent locally")
	parser.add_argument("--host", default="127.0.0.1", help="Dashboard host (default: 127.0.0.1)")
	parser.add_argument("--port", default=8765, type=int, help="Dashboard port (default: 8765)")
	parser.add_argument("--no-browser", action="store_true", help="Do not open the browser automatically")
	parser.add_argument(
		"--allow-paid-ai",
		action="store_true",
		help="Explicitly allow paid Browser Use AI fallbacks. Disabled by default.",
	)
	args = parser.parse_args()

	# Cost policy must be resolved before importing job_agent. The package itself
	# enforces the same invariant for direct imports, so paid AI cannot be enabled
	# accidentally by a local .env file while zero-cost mode is active.
	os.environ["JOB_AGENT_ZERO_COST"] = "0" if args.allow_paid_ai else "1"
	from job_agent import enforce_zero_cost_policy

	zero_cost = enforce_zero_cost_policy()
	if zero_cost:
		print("Job Agent ZERO COST: paid Browser Use AI/API calls are disabled.")
	else:
		print("Job Agent paid-AI mode enabled explicitly with --allow-paid-ai.")

	from job_agent.computrabajo.job_validation import purge_invalid_computrabajo_jobs

	removed = purge_invalid_computrabajo_jobs()
	if removed:
		print(f"Job Agent cleaned {removed} invalid Computrabajo error-page record(s).")

	# Import after cleanup so dashboard singletons are created against clean data.
	from job_agent.sync_dashboard import run_dashboard

	run_dashboard(host=args.host, port=args.port, open_browser=not args.no_browser)


if __name__ == "__main__":
	main()
