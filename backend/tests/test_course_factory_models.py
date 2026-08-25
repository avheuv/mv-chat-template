import unittest
from unittest.mock import patch

from pydantic import BaseModel

from app.models.course_factory import (
    AgentDisplay,
    AgentStatus,
    CourseWorkflow,
    ScopeSequenceUnit,
    WorkflowAgent,
)
from app.models.course_factory import (
    AlignmentAgentOutput,
    ContentItem,
    ContentPlannerOutput,
    CourseArchitectOutput,
    CourseObjective,
    EssentialQuestion,
    InquiryDesignerOutput,
    LessonObjective,
    LearningObjectiveDesignerOutput,
    Standard,
    StandardsAnalystOutput,
    UnitPlan,
)
from app.services.course_factory_service import CourseFactoryService


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


class CourseFactoryOrchestrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_each_unit_receives_outputs_from_all_previous_agents(self):
        calls = []

        async def fake_call(agent, inputs, output_model):
            calls.append((agent, inputs, output_model))
            artifacts: dict[WorkflowAgent, BaseModel] = {
                WorkflowAgent.COURSE_ARCHITECT: CourseArchitectOutput(
                    course_context="A sequenced astronomy course.",
                    course_objectives=[CourseObjective(
                        objective_id="CO1",
                        objective_text="Analyze astronomical systems.",
                    )],
                    units=[
                        UnitPlan(
                            unit_id=f"U{index:02d}",
                            unit_title=f"Unit {index}",
                            unit_description=f"Astronomy topic {index}.",
                        )
                        for index in range(1, 9)
                    ],
                ),
                WorkflowAgent.STANDARDS_ANALYST: StandardsAnalystOutput(
                    standards_source_summary="No authoritative source supplied; provisional competency.",
                    standards=[Standard(standard_id="PROV-1", description="Analyze systems.")],
                ),
                WorkflowAgent.ALIGNMENT_AGENT: AlignmentAgentOutput(
                    course_level_objectives=[CourseObjective(
                        objective_id="CO1",
                        objective_text="Analyze astronomical systems.",
                    )],
                ),
                WorkflowAgent.INQUIRY_DESIGNER: InquiryDesignerOutput(
                    essential_questions=[EssentialQuestion(
                        question_id="EQ1",
                        question_text="How do models change what we can observe?",
                    )],
                ),
                WorkflowAgent.LEARNING_OBJECTIVE_DESIGNER: LearningObjectiveDesignerOutput(
                    lesson_level_objectives=[
                        LessonObjective(
                            objective_id=f"LO{index}",
                            lesson_id=f"L{index}",
                            lesson_title=f"Lesson {index}",
                            objective_text=f"Students will be able to analyze model {index}.",
                        )
                        for index in range(1, 4)
                    ],
                ),
                WorkflowAgent.CONTENT_PLANNER: ContentPlannerOutput(
                    content=[ContentItem(
                        content_id="C1",
                        label="Astronomical models",
                        category="concept",
                        supports_objective_ids=["LO1", "LO2", "LO3"],
                    )],
                ),
            }
            artifact = artifacts[agent]
            return AgentDisplay(
                agent_name=agent,
                status=AgentStatus.COMPLETE,
                input_summary="Prior structured artifacts.",
                activity_summary="Completed assigned design task.",
                decision_summary="Selected aligned material.",
                output_summary="Produced structured output.",
                structured_output=artifact.model_dump(mode="json"),
            ), artifact

        with patch("app.services.course_factory_service._call_agent", side_effect=fake_call):
            events = [event async for event in CourseFactoryService().stream_course("Astronomy")]

        complete = next(event for event in events if event.startswith("event: complete"))
        payload = __import__("json").loads(complete.split("data: ", 1)[1])
        course = payload["course"]

        self.assertEqual(len(calls), 41)
        self.assertEqual(len(course["units"]), 8)
        self.assertEqual(len(course["units"][0]["agents"]), 5)
        self.assertEqual(len(course["units"][0]["handoffs"]), 5)
        self.assertEqual(len(course["units"][0]["lessons"]), 3)
        self.assertEqual(course["units"][0]["scope_sequence"]["content"][0]["content_id"], "C1")

        alignment_input = calls[2][1]["scope_sequence_so_far"]
        inquiry_input = calls[3][1]["scope_sequence_so_far"]
        content_input = calls[5][1]["scope_sequence_so_far"]
        self.assertEqual(alignment_input["standards_addressed"][0]["standard_id"], "PROV-1")
        self.assertEqual(inquiry_input["course_level_objectives"][0]["objective_id"], "CO1")
        self.assertEqual(len(content_input["lesson_level_objectives"]), 3)


if __name__ == "__main__":
    unittest.main()
