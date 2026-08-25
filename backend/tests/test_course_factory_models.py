import unittest

from app.models.course_factory import (
    AgentDisplay,
    AgentStatus,
    CourseWorkflow,
    ScopeSequenceUnit,
    WorkflowAgent,
)


class CourseWorkflowModelTests(unittest.TestCase):
    def test_defaults_create_empty_phase_one_workflow_state(self):
        course = CourseWorkflow(
            subject="Astronomy",
            units=[ScopeSequenceUnit(unit_id="U01", unit_title="Exploring the Sky")],
        )

        payload = course.model_dump(mode="json")

        self.assertEqual(payload["schema_version"], "1.0")
        self.assertEqual(payload["workflow"]["max_revision_cycles"], 2)
        self.assertEqual(payload["units"][0]["scope_sequence"]["content"], [])
        self.assertEqual(payload["units"][0]["agents"], [])
        self.assertIsNone(payload["units"][0]["reviewer_feedback"])

    def test_agent_display_keeps_summary_and_structured_output_separate(self):
        display = AgentDisplay(
            agent_name=WorkflowAgent.STANDARDS_ANALYST,
            status=AgentStatus.COMPLETE,
            input_summary="Unit context and standards catalog.",
            activity_summary="Matched standards to the unit.",
            decision_summary="Selected two directly addressed standards.",
            output_summary="Two standards selected.",
            structured_output={"standard_ids": ["SCI.1", "SCI.2"]},
        )

        self.assertEqual(display.output_summary, "Two standards selected.")
        self.assertEqual(display.structured_output["standard_ids"], ["SCI.1", "SCI.2"])


if __name__ == "__main__":
    unittest.main()
