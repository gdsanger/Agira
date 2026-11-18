"""Provider interface for the agent queue worker.

The worker (``run_claude_worker``) owns everything that is independent of the
coding agent: branch/PR handling, the epic chain, merge, orphan recovery,
timeouts and the review parser/apply. Everything that depends on *which* CLI is
driven sits behind :class:`AgentProvider`:

* command line (``build_args``) and child environment incl. credentials
  (``build_env``),
* the CLI's output stream (``parse_stream``),
* error classification (``is_limit_error``, ``is_auth_error``,
  ``parse_limit_reset``, ``limit_detail``, ``auth_error_message``),
* checkout preparation such as trust/permission files (``prepare_checkout``),
* the mapping of a stored model slug to the CLI's model id (``model_id``).

Adding a provider means: subclass :class:`AgentProvider`, implement these
methods and register it in :data:`providers.PROVIDERS`. The worker core needs
no change. Prompt and review text stay in the worker; they are passed to the
CLI via stdin, which every provider is expected to read.
"""

from __future__ import annotations


def save_progress(job, text, extra_fields=None):
    """Persist the job's "current step" line (plus any other changed fields)."""
    job.progress_text = (text or '')[:2000]
    fields = ['progress_text'] + (extra_fields or [])
    job.save(update_fields=fields)


class AgentProvider:
    """Everything the worker needs from one coding-agent CLI."""

    #: Registry key, see ``get_provider``.
    name = ''

    #: Tool names the CLI may use in an implementation run (informational).
    allowed_tools = ''

    def build_args(self, job):
        """argv of the headless CLI run (the prompt travels via stdin)."""
        raise NotImplementedError

    def build_env(self, job, pr_body_file, *, auth_mode, timeout):
        """Child environment for one run, incl. exactly the matching credential."""
        raise NotImplementedError

    def parse_stream(self, job, lines, tools_in_flight=None):
        """Consume the CLI's output lines, updating ``job`` progress as they arrive.

        ``tools_in_flight`` is a set the provider keeps in step with running tool
        calls (the idle watchdog pauses while it is non-empty). Returns a dict
        with ``session_id``, ``result_text``, ``is_error``, ``saw_result`` and
        usage (``num_turns``, ``total_cost_usd``).
        """
        raise NotImplementedError

    def is_limit_error(self, result):
        """True if an errored run hit a usage/subscription limit."""
        raise NotImplementedError

    def is_auth_error(self, result):
        """True if an errored run failed on a broken/expired credential."""
        raise NotImplementedError

    def parse_limit_reset(self, result):
        """Aware datetime of the quota reset, or ``None`` if not derivable."""
        raise NotImplementedError

    def limit_detail(self, result):
        """Short, log-safe detail string for a limit hit."""
        detail = (result.get('result_text') or result.get('stderr') or '').strip()
        return detail[:500]

    def auth_error_message(self, result, job=None):
        """Actionable failure message for a credential problem."""
        raise NotImplementedError

    def prepare_checkout(self, repo_dir, review=False):
        """Write provider-specific files into the checkout (trust, permissions)."""
        raise NotImplementedError

    def model_id(self, slug):
        """Translate a stored model slug into the CLI's model identifier."""
        raise NotImplementedError
