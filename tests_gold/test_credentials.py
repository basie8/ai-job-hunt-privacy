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
        env = _env_without_credentials()
        code = ("import anthropic;c=anthropic.Anthropic();"
                "print('constructed', bool(getattr(c,'api_key',None)))")
        result = subprocess.run([sys.executable, "-c", code], env=env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("constructed False", result.stdout)
        del anthropic


class TheRemedy(unittest.TestCase):
    def test_it_leads_with_the_variable_that_actually_works(self):
        # ANTHROPIC_API_KEY is reserved inside a Claude Code session and is
        # silently dropped. Naming it first would send someone down the exact
        # path that already wasted an evening.
        self.assertIn("Use AURUM_ANTHROPIC_API_KEY, not ANTHROPIC_API_KEY",
                      CREDENTIALS_REMEDY)
        self.assertLess(CREDENTIALS_REMEDY.index("AURUM_ANTHROPIC_API_KEY"),
                        CREDENTIALS_REMEDY.index("console.anthropic.com"))

    def test_it_explains_why_the_obvious_name_fails(self):
        self.assertIn("reserved inside a Claude Code session", CREDENTIALS_REMEDY)

    def test_the_unreserved_name_is_preferred_when_both_are_set(self):
        import os
        from investment_pipeline.llm import credential_source, resolve_api_key

        previous = {k: os.environ.get(k) for k in ("AURUM_ANTHROPIC_API_KEY",
                                                   "ANTHROPIC_API_KEY")}
        os.environ["AURUM_ANTHROPIC_API_KEY"] = "sk-ant-aurum"
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-reserved"
        try:
            self.assertEqual(credential_source(), "AURUM_ANTHROPIC_API_KEY")
            self.assertEqual(resolve_api_key(), "sk-ant-aurum")
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_the_reserved_names_still_work_outside_a_session(self):
        # A local shell, CI, a plain container: there the obvious name is fine.
        import os
        from investment_pipeline.llm import resolve_api_key

        previous = {k: os.environ.get(k) for k in ("AURUM_ANTHROPIC_API_KEY",
                                                   "ANTHROPIC_API_KEY")}
        os.environ.pop("AURUM_ANTHROPIC_API_KEY", None)
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-local"
        try:
            self.assertEqual(resolve_api_key(), "sk-ant-local")
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

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
        env = _env_without_credentials()
        repo = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        result = subprocess.run(
            [sys.executable, "-m", "gold_trader", "signal", "--csv-dir", "data/"],
            cwd=repo, env=env, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 3, result.stderr[-800:])
        self.assertIn("No Anthropic API credentials", result.stderr)
        # It must fail fast, before a stack trace from library internals.
        self.assertNotIn("_validate_headers", result.stderr)


def _env_without_credentials():
    """A child environment with EVERY credential name removed.

    Stripping only the reserved two was a real bug: once
    AURUM_ANTHROPIC_API_KEY existed and was set, this test stopped exercising
    the no-credentials path and started making live API calls, which hung the
    suite for minutes. The list has to come from the code under test, not be
    restated here, or the next variable added reopens the same hole.
    """
    from investment_pipeline.llm import CREDENTIAL_ENV_VARS

    return {k: v for k, v in os.environ.items() if k not in CREDENTIAL_ENV_VARS}


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


class KeyPresentButRefused(unittest.TestCase):
    """A rejected key and a missing key are different problems with
    non-overlapping remedies. On 2026-09-17 a rotation left a dead key in the
    environment and the run reported "no Anthropic credentials" -- sending the
    owner to look for a variable that was already set."""

    def test_the_two_remedies_do_not_say_the_same_thing(self):
        from gold_trader.cli import CREDENTIALS_REMEDY, REJECTED_REMEDY

        self.assertNotEqual(CREDENTIALS_REMEDY, REJECTED_REMEDY)
        self.assertIn("401", REJECTED_REMEDY)
        self.assertIn("No Anthropic API credentials", CREDENTIALS_REMEDY)

    def test_the_rejection_message_says_the_key_is_present(self):
        # The single most important line: stop looking for a missing variable.
        from gold_trader.cli import REJECTED_REMEDY

        self.assertIn("not a missing-variable problem", REJECTED_REMEDY)

    def test_it_names_rotation_first_among_the_causes(self):
        # A container keeps the variables it started with, so a rotation leaves
        # dead keys in every session that was already running.
        from gold_trader.cli import REJECTED_REMEDY

        self.assertIn("revoked or rotated", REJECTED_REMEDY)
        self.assertLess(REJECTED_REMEDY.index("revoked or rotated"),
                        REJECTED_REMEDY.index("character missing"))

    def test_it_says_what_is_working(self):
        # Otherwise a 401 reads as "everything is broken" at a glance.
        from gold_trader.cli import REJECTED_REMEDY

        self.assertIn("the key was found, the client was built", REJECTED_REMEDY)

    def test_an_auth_stage_error_exits_five_not_three(self):
        # Distinct exit codes so the Routine can tell them apart without
        # parsing prose: 3 = no key, 5 = key refused.
        import argparse
        from unittest import mock

        from gold_trader import cli
        from investment_pipeline.llm import StageError

        args = argparse.Namespace(csv_dir="data/", json=None, json_out=False,
                                  state_dir=None, journal=None, account=None,
                                  risk_pct=None)
        with mock.patch.object(cli, "run_signal",
                               side_effect=StageError("analyst: authentication failed: 401")), \
             mock.patch.object(cli, "_has_credentials", return_value=True):
            self.assertEqual(cli.cmd_signal(args), 5)

    def test_a_non_auth_stage_error_exits_six(self):
        import argparse
        from unittest import mock

        from gold_trader import cli
        from investment_pipeline.llm import StageError

        args = argparse.Namespace(csv_dir="data/", json=None, json_out=False,
                                  state_dir=None, journal=None, account=None,
                                  risk_pct=None)
        with mock.patch.object(cli, "run_signal",
                               side_effect=StageError("executor: schema mismatch")), \
             mock.patch.object(cli, "_has_credentials", return_value=True):
            self.assertEqual(cli.cmd_signal(args), 6)

    def test_a_stage_error_never_surfaces_as_a_traceback(self):
        import argparse
        import io
        from contextlib import redirect_stderr
        from unittest import mock

        from gold_trader import cli
        from investment_pipeline.llm import StageError

        args = argparse.Namespace(csv_dir="data/", json=None, json_out=False,
                                  state_dir=None, journal=None, account=None,
                                  risk_pct=None)
        buffer = io.StringIO()
        with mock.patch.object(cli, "run_signal",
                               side_effect=StageError("analyst: authentication failed: 401")), \
             mock.patch.object(cli, "_has_credentials", return_value=True), \
             redirect_stderr(buffer):
            cli.cmd_signal(args)
        self.assertNotIn("Traceback", buffer.getvalue())
        self.assertIn("401", buffer.getvalue())


class VerifyingTheKeyWithoutAScheduledRun(unittest.TestCase):
    """Finding out whether the key works used to cost a whole Routine run.

    On 2026-09-18 the only way to learn what a Routine container held was to
    fire one, have it push a heartbeat, and read the commit -- ten minutes to
    answer a question the container could answer in one second. `credentials`
    is that second.
    """

    def test_no_variable_set_is_reported_as_absent(self):
        from investment_pipeline.llm import ABSENT, verify_key

        with _no_credentials():
            check = verify_key(client=_Models(None), probe=True)
        self.assertEqual(check.status, ABSENT)
        self.assertFalse(check.ok)

    def test_an_accepted_key_is_valid(self):
        from investment_pipeline.llm import VALID, verify_key

        with _a_credential("sk-ant-test-value"):
            check = verify_key(client=_Models(None), probe=True)
        self.assertEqual(check.status, VALID)
        self.assertTrue(check.ok)
        self.assertEqual(check.source, "AURUM_ANTHROPIC_API_KEY")

    def test_a_401_is_refused_not_absent(self):
        # The whole point. A present-but-dead key reported as "no credentials"
        # sends the reader hunting for a variable that is already set.
        from investment_pipeline.llm import REFUSED, verify_key

        with _a_credential("sk-ant-dead"):
            check = verify_key(client=_Models(_Status(401)), probe=True)
        self.assertEqual(check.status, REFUSED)
        self.assertIn("not a missing-variable problem", check.detail)

    def test_a_network_failure_is_not_reported_as_a_bad_key(self):
        # An unreachable API says nothing about the key. Calling it refused
        # would start a key rotation to fix a dropped connection.
        from investment_pipeline.llm import UNREACHABLE, verify_key

        with _a_credential("sk-ant-fine"):
            check = verify_key(client=_Models(OSError("connection reset")), probe=True)
        self.assertEqual(check.status, UNREACHABLE)
        self.assertIn("unjudged", check.detail)

    def test_a_403_is_not_an_authentication_failure(self):
        from investment_pipeline.llm import UNREACHABLE, verify_key

        with _a_credential("sk-ant-fine"):
            check = verify_key(client=_Models(_Status(403)), probe=True)
        self.assertEqual(check.status, UNREACHABLE)

    def test_it_reports_the_length_and_never_the_value(self):
        # A diagnostic that echoes a secret turns a support question into a
        # rotation. That has already happened once in this project.
        from investment_pipeline.llm import verify_key

        secret = "sk-ant-this-must-never-appear"
        with _a_credential(secret):
            check = verify_key(client=_Models(None), probe=True)
        rendered = check.render()
        self.assertIn(str(len(secret)), rendered)
        self.assertNotIn(secret, rendered)
        self.assertNotIn(secret, repr(check))

    def test_probing_can_be_switched_off(self):
        from investment_pipeline.llm import UNCHECKED, verify_key

        with _a_credential("sk-ant-x"):
            check = verify_key(client=_Exploding(), probe=False)
        self.assertEqual(check.status, UNCHECKED)

    def test_the_check_is_free(self):
        # models.list is authenticated and bills nothing. A messages request
        # would work too and cost money, and a diagnostic that costs money is
        # one people stop running.
        from investment_pipeline.llm import verify_key

        models = _Models(None)
        with _a_credential("sk-ant-x"):
            verify_key(client=models, probe=True)
        self.assertEqual(models.calls, 1)


class TheCredentialsCommand(unittest.TestCase):
    def test_exit_codes_match_signal(self):
        # 3 = nothing set, 5 = set but refused -- so a Routine can branch on
        # the code without reading prose.
        import argparse
        from unittest import mock

        from gold_trader import cli
        from investment_pipeline.llm import ABSENT, CredentialCheck, REFUSED, VALID

        args = argparse.Namespace(no_probe=False, json_out=True)
        for status, expected in ((ABSENT, 3), (REFUSED, 5), (VALID, 0)):
            with mock.patch("investment_pipeline.llm.verify_key",
                            return_value=CredentialCheck(status=status, source="X")):
                self.assertEqual(cli.cmd_credentials(args), expected, status)


class _Models:
    """A stand-in for the SDK client, exercising only what verify_key uses."""

    def __init__(self, raises):
        self._raises, self.calls = raises, 0
        self.models = self

    def list(self, limit=None):
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        return []


class _Exploding:
    @property
    def models(self):
        raise AssertionError("verify_key must not touch the network when probe=False")


class _Status(Exception):
    def __init__(self, code):
        super().__init__(f"HTTP {code}")
        self.status_code = code


class _no_credentials:
    def __enter__(self):
        from investment_pipeline.llm import CREDENTIAL_ENV_VARS

        self._saved = {k: os.environ.pop(k, None) for k in CREDENTIAL_ENV_VARS}
        return self

    def __exit__(self, *exc):
        for key, value in self._saved.items():
            if value is not None:
                os.environ[key] = value
        return False


class _a_credential(_no_credentials):
    def __init__(self, value):
        self._value = value

    def __enter__(self):
        super().__enter__()
        os.environ["AURUM_ANTHROPIC_API_KEY"] = self._value
        return self

    def __exit__(self, *exc):
        os.environ.pop("AURUM_ANTHROPIC_API_KEY", None)
        return super().__exit__(*exc)
