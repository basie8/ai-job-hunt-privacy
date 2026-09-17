"""The four stages call the Anthropic API directly and need a key of their own.

A Claude Code session authenticates through the subscription and does not expose
one inside the sandbox, so a scheduled run has credentials for the agent driving
it and none for the pipeline it invokes. That is not obvious, and the SDK makes
it less so: it constructs happily without a key and raises TypeError from inside
_validate_headers on the first request.
"""

import os
import subprocess
import sys
import unittest

from gold_trader.cli import CREDENTIALS_REMEDY, _has_credentials


class Detection(unittest.TestCase):
    def test_a_client_with_no_credential_is_detected(self):
        self.assertFalse(_has_credentials(_Fake(api_key=None, auth_token=None)))

    def test_an_api_key_counts(self):
        self.assertTrue(_has_credentials(_Fake(api_key="sk-ant-x", auth_token=None)))

    def test_an_auth_token_counts(self):
        # The SDK accepts either; checking only for a key would refuse a run
        # that would actually have worked.
        self.assertTrue(_has_credentials(_Fake(api_key=None, auth_token="tok")))

    def test_the_wrapper_is_unwrapped_to_find_the_real_client(self):
        self.assertTrue(_has_credentials(_Wrapper(_Fake(api_key="sk-ant-x"))))

    def test_the_real_sdk_constructs_without_credentials(self):
        # The behaviour the guard exists for. If a future SDK starts raising at
        # construction instead, this fails and the guard can move.
        anthropic = _sdk_or_skip()
        env = {k: v for k, v in os.environ.items()
               if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
        code = ("import anthropic;c=anthropic.Anthropic();"
                "print('constructed', bool(getattr(c,'api_key',None)))")
        result = subprocess.run([sys.executable, "-c", code], env=env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("constructed False", result.stdout)
        del anthropic


class TheRemedy(unittest.TestCase):
    def test_it_names_both_ways_to_supply_a_credential(self):
        self.assertIn("ANTHROPIC_API_KEY", CREDENTIALS_REMEDY)
        self.assertIn("ANTHROPIC_AUTH_TOKEN", CREDENTIALS_REMEDY)

    def test_it_says_a_session_login_does_not_count(self):
        # The single most confusing part: the agent is authenticated and the
        # pipeline it runs is not.
        self.assertIn("subscription login does not satisfy this", CREDENTIALS_REMEDY)

    def test_it_names_what_still_works_without_a_key(self):
        # Most of the system does not call a model. Saying so stops a missing
        # key reading as "everything is down".
        for command in ("resolve", "status", "learn", "runs", "dashboard"):
            self.assertIn(command, CREDENTIALS_REMEDY)

    def test_it_points_at_the_documentation(self):
        self.assertIn("RUNTIME.md", CREDENTIALS_REMEDY)


class EndToEnd(unittest.TestCase):
    def test_signal_exits_three_and_names_the_remedy(self):
        _sdk_or_skip()
        env = {k: v for k, v in os.environ.items()
               if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
        repo = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        result = subprocess.run(
            [sys.executable, "-m", "gold_trader", "signal", "--csv-dir", "data/"],
            cwd=repo, env=env, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 3, result.stderr[-800:])
        self.assertIn("No Anthropic API credentials", result.stderr)
        # It must fail fast, before a stack trace from library internals.
        self.assertNotIn("_validate_headers", result.stderr)


class _Fake:
    def __init__(self, api_key=None, auth_token=None):
        self.api_key, self.auth_token = api_key, auth_token


class _Wrapper:
    def __init__(self, inner):
        self._client = inner


def _sdk_or_skip():
    try:
        import anthropic
    except ImportError:
        raise unittest.SkipTest("anthropic SDK not installed in this environment")
    return anthropic


if __name__ == "__main__":
    unittest.main()
