import unittest

from benchmark_controller.matrix import build_pilot_schedule


class MatrixScheduleTests(unittest.TestCase):
    def test_schedule_contains_each_condition_once(self) -> None:
        schedule = build_pilot_schedule(
            task_id="pilot_greenfield_service_readiness",
            product_id="greenfield",
            seed=20260817,
        )
        self.assertEqual(len(schedule), 18)
        self.assertEqual({item.condition_id for item in schedule}, {
            f"{ade}__{harness}__{agentskit}"
            for ade in {"orca", "agent-orchestrator", "compozy"}
            for harness in {"reference", "openhands-sdk", "mini-swe-agent"}
            for agentskit in {"off", "on"}
        })

    def test_schedule_is_reproducible_and_replicates_expand_runs(self) -> None:
        first = build_pilot_schedule(
            task_id="pilot_greenfield_service_readiness", product_id="greenfield", seed=7, replicate_count=2
        )
        second = build_pilot_schedule(
            task_id="pilot_greenfield_service_readiness", product_id="greenfield", seed=7, replicate_count=2
        )
        self.assertEqual([item.to_dict() for item in first], [item.to_dict() for item in second])
        self.assertEqual(len(first), 36)
        self.assertEqual(len({item.run_id for item in first}), 36)

    def test_non_pilot_task_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "pilot task"):
            build_pilot_schedule(task_id="main_task", product_id="greenfield", seed=1)
