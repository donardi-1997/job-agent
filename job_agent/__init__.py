"""Computrabajo job-search agent built on top of browser-use."""

from __future__ import annotations

import os

__all__ = ["__version__", "zero_cost_enabled", "enforce_zero_cost_policy"]

__version__ = "0.1.0"

_FALSE_VALUES = {"0", "false", "no", "off"}


def zero_cost_enabled() -> bool:
    """Return whether paid AI/API usage is forbidden for this process.

    Job Agent is a personal local-first application, so zero-cost mode is the
    default. Paid AI can only be enabled explicitly before importing ``job_agent``
    by setting ``JOB_AGENT_ZERO_COST=0`` (the CLI exposes this as
    ``--allow-paid-ai``).
    """

    return os.getenv("JOB_AGENT_ZERO_COST", "1").strip().casefold() not in _FALSE_VALUES


def enforce_zero_cost_policy() -> bool:
    """Apply the process-wide no-paid-AI invariant when zero-cost mode is active.

    The existing collectors/preparers already check these feature flags before
    invoking Browser Use AI. For defense in depth, the Browser Use API key is also
    shadowed with an empty process value, so later ``load_dotenv()`` calls cannot
    silently re-enable paid requests from a local ``.env`` file.
    """

    enabled = zero_cost_enabled()
    if not enabled:
        return False

    os.environ["JOB_AGENT_ZERO_COST"] = "1"
    os.environ["JOB_AGENT_SEARCH_AI_FALLBACK"] = "0"
    os.environ["JOB_AGENT_QUESTION_LLM"] = "0"
    os.environ["JOB_AGENT_APPLICATION_AI_FALLBACK"] = "0"
    os.environ["BROWSER_USE_API_KEY"] = ""
    return True


# Make direct imports safe too, not only launches through run_job_agent.py.
enforce_zero_cost_policy()
