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
    parser.add_argument(
        "--smoke-test-job",
        default=None,
        metavar="JOB_ID|auto",
        help="Run one safe Computrabajo application smoke test for JOB_ID, or auto-select the best eligible job.",
    )
    parser.add_argument(
        "--smoke-report-dir",
        default="data/smoke-tests",
        help="Directory for smoke-test JSON reports (default: data/smoke-tests).",
    )
    args = parser.parse_args()

    if args.smoke_test_job is not None and args.allow_paid_ai:
        parser.error("--smoke-test-job cannot be combined with --allow-paid-ai; smoke tests are always zero-cost.")

    # Cost policy must be resolved before importing job_agent. Smoke tests always
    # force zero-cost independently of the normal dashboard flag.
    os.environ["JOB_AGENT_ZERO_COST"] = "0" if args.allow_paid_ai else "1"
    if args.smoke_test_job is not None:
        os.environ["JOB_AGENT_ZERO_COST"] = "1"

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

    if args.smoke_test_job is not None:
        from job_agent.computrabajo.smoke_test import run_smoke_test, select_smoke_job_id

        raw_target = str(args.smoke_test_job).strip().casefold()
        if raw_target == "auto":
            job_id = select_smoke_job_id()
            print(f"Smoke target auto-selected: job {job_id}.")
        else:
            try:
                job_id = int(raw_target)
            except ValueError:
                parser.error("--smoke-test-job must be a positive JOB_ID or 'auto'.")
            if job_id <= 0:
                parser.error("--smoke-test-job must be a positive JOB_ID or 'auto'.")

        report, output_path = run_smoke_test(
            job_id,
            report_dir=args.smoke_report_dir,
        )
        coverage = report["coverage"]
        result = report["result"]
        print("Computrabajo smoke test completed safely: no final submission action was triggered.")
        print(
            "Fields: "
            f"{coverage['observed_fields']} observed, "
            f"{coverage['resolved_fields']} resolved, "
            f"{coverage['unresolved_fields']} unresolved."
        )
        if result["ready_to_submit"]:
            print("Result: form reached the final submission boundary and stopped before submit.")
        elif result["blocked_reason"]:
            print(f"Result: blocked safely — {result['blocked_reason']}")
        elif result["fallback_reason"]:
            print(f"Result: incomplete — {result['fallback_reason']}")
        else:
            print("Result: smoke inspection completed without a final-submit boundary.")
        print(f"Report: {output_path}")
        return

    # Import after cleanup so dashboard singletons are created against clean data.
    from job_agent.sync_dashboard import run_dashboard

    run_dashboard(host=args.host, port=args.port, open_browser=not args.no_browser)


if __name__ == "__main__":
    main()
