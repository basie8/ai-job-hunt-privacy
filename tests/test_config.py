import unittest

from investment_pipeline.config import (
    ANALYST,
    EXECUTOR,
    HAIKU_4_5,
    REPORTER,
    RISK_MANAGER,
    DEFAULT_MODEL_TIERS,
    resolve_model_tiers,
)


class ModelTiering(unittest.TestCase):
    def test_default_assignment_puts_the_expensive_models_where_judgement_is(self):
        self.assertEqual(DEFAULT_MODEL_TIERS[ANALYST].model_id, "claude-opus-5")
        self.assertEqual(DEFAULT_MODEL_TIERS[RISK_MANAGER].model_id, "claude-opus-5")
        self.assertEqual(DEFAULT_MODEL_TIERS[RISK_MANAGER].effort, "max")
        self.assertEqual(DEFAULT_MODEL_TIERS[EXECUTOR].model_id, "claude-sonnet-5")
        self.assertEqual(DEFAULT_MODEL_TIERS[REPORTER].model_id, "claude-haiku-4-5")

    def test_haiku_carries_no_effort_or_thinking_field(self):
        # Haiku 4.5 rejects output_config.effort and uses the older thinking form.
        self.assertIsNone(HAIKU_4_5.effort)
        self.assertIsNone(HAIKU_4_5.thinking)
        self.assertIsNone(HAIKU_4_5.output_config())

    def test_env_override_promotes_a_stage(self):
        tiers = resolve_model_tiers(env={"PIPELINE_MODEL_EXECUTOR": "claude-opus-5"})
        self.assertEqual(tiers[EXECUTOR].model_id, "claude-opus-5")
        self.assertEqual(tiers[EXECUTOR].effort, "low")  # the stage's effort intent survives

    def test_promoting_into_haiku_drops_effort(self):
        tiers = resolve_model_tiers(env={"PIPELINE_MODEL_ANALYST": "claude-haiku-4-5"})
        self.assertIsNone(tiers[ANALYST].effort)

    def test_explicit_override_beats_the_environment(self):
        tiers = resolve_model_tiers(
            overrides={EXECUTOR: "claude-haiku-4-5"},
            env={"PIPELINE_MODEL_EXECUTOR": "claude-opus-5"},
        )
        self.assertEqual(tiers[EXECUTOR].model_id, "claude-haiku-4-5")

    def test_unknown_model_id_is_rejected(self):
        with self.assertRaises(ValueError):
            resolve_model_tiers(env={"PIPELINE_MODEL_ANALYST": "gpt-fake"})


if __name__ == "__main__":
    unittest.main()
