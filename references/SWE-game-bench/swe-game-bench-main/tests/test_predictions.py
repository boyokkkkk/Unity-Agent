import unittest

from swe_game_bench.predictions import PredictionRecord, resolve_metadata


def record(line_no: int, *, temperature: str | None) -> PredictionRecord:
    return PredictionRecord(
        instance_id="fungus-879",
        run_id=line_no,
        model_patch="",
        agent="test-agent",
        model="test-model",
        temperature=temperature,
        line_no=line_no,
    )


class PredictionMetadataTests(unittest.TestCase):
    def test_temperature_may_be_omitted_from_official_submission(self) -> None:
        metadata = resolve_metadata(
            [record(1, temperature=None), record(2, temperature=None)]
        )

        self.assertIsNone(metadata.temperature)

    def test_temperature_must_be_consistent_when_present(self) -> None:
        with self.assertRaisesRegex(ValueError, "temperature must be consistent"):
            resolve_metadata(
                [record(1, temperature="0.4"), record(2, temperature="0.8")]
            )

    def test_temperature_cannot_be_present_on_only_some_rows(self) -> None:
        with self.assertRaisesRegex(
            ValueError, "temperature must be present on every JSONL row or omitted"
        ):
            resolve_metadata(
                [record(1, temperature="0.4"), record(2, temperature=None)]
            )

    def test_temperature_override_can_describe_an_omitted_value(self) -> None:
        metadata = resolve_metadata(
            [record(1, temperature=None), record(2, temperature=None)],
            temperature_override="0.4",
        )

        self.assertEqual(metadata.temperature, "0.4")

    def test_agent_and_model_remain_required(self) -> None:
        missing_agent = PredictionRecord(
            instance_id="fungus-879",
            run_id=1,
            model_patch="",
            agent=None,
            model="test-model",
            temperature=None,
            line_no=1,
        )

        with self.assertRaisesRegex(ValueError, "agent is missing"):
            resolve_metadata([missing_agent])


if __name__ == "__main__":
    unittest.main()
