import json
import unittest
from unittest.mock import AsyncMock, patch

from app.models.course_factory import AgentStatus, UnitStatus, WorkflowStatus
from app.services.course_factory_service import (
    AlignmentResult,
    ArchitectResult,
    ArchitectUnit,
    ContentResult,
    CourseFactoryService,
    InquiryResult,
    LearningObjectivesResult,
    StandardsResult,
)
from app.models.course_factory import (
    ContentItem,
    CourseObjective,
    EssentialQuestion,
    LessonObjective,
    Standard,
)


def summary():
    return {
        "activity_summary": "Completed the assigned design task.",
        "decision_summary": "Selected the artifacts that align most directly.",
        "output_summary": "Created validated structured output.",
    }


def result_for(model, payload):
    unit_id = payload.get("unit", {}).get("unit_id", "U01")
    if model is ArchitectResult:
        return ArchitectResult(
            **summary(),
            course_context="A coherent astronomy course.",
            standards_source_summary="Use NGSS where applicable.",
            course_objectives=[CourseObjective(objective_id="CO1", objective_text="Analyze astronomical systems.")],
            units=[ArchitectUnit(unit_id=f"U{i:02d}", unit_title=f"Unit {i}", unit_description="Sequenced unit.") for i in range(1, 9)],
        )
    if model is StandardsResult:
        return StandardsResult(**summary(), standards_addressed=[Standard(standard_id=f"{unit_id}-STD", description="Analyze data.", source="NGSS")])
    if model is AlignmentResult:
        return AlignmentResult(**summary(), course_level_objectives=[CourseObjective(objective_id="CO1", objective_text="Ignored replacement text")])
    if model is InquiryResult:
        return InquiryResult(**summary(), essential_questions=[EssentialQuestion(question_id=f"{unit_id}-EQ1", question_text="How do models shape explanations?")])
    if model is LearningObjectivesResult:
        return LearningObjectivesResult(**summary(), lesson_level_objectives=[LessonObjective(objective_id=f"{unit_id}-LO1", objective_text="Students will be able to analyze a model.")])
    if model is ContentResult:
        return ContentResult(**summary(), content=[ContentItem(content_id=f"{unit_id}-C1", label="Scientific models", category="concept", supports_objective_ids=[f"{unit_id}-LO1"])])
    raise AssertionError(f"Unexpected model: {model}")


async def collect(service):
    return [event async for event in service.stream_course("Astronomy")]


def event_payload(event):
    return json.loads(event.split("data: ", 1)[1])


class CourseFactoryServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_runs_each_unit_through_all_five_agents_with_cumulative_context(self):
        calls = []

        async def fake_call(instructions, input_payload, result_model, max_tokens=4000):
            calls.append((result_model, input_payload))
            return result_for(result_model, input_payload)

        with patch("app.services.course_factory_service._call_agent", new=AsyncMock(side_effect=fake_call)):
            events = await collect(CourseFactoryService())

        complete = event_payload(events[-1])
        course = complete["course"]
        self.assertEqual(course["workflow"]["status"], WorkflowStatus.COMPLETE.value)
        self.assertEqual(len(course["units"]), 8)
        self.assertEqual(len(calls), 41)
        for unit in course["units"]:
            self.assertEqual(unit["status"], UnitStatus.COMPLETE.value)
            self.assertEqual([agent["status"] for agent in unit["agents"]], [AgentStatus.COMPLETE.value] * 5)
            self.assertTrue(unit["scope_sequence"]["standards_addressed"])
            self.assertTrue(unit["scope_sequence"]["course_level_objectives"])
            self.assertTrue(unit["scope_sequence"]["essential_questions"])
            self.assertTrue(unit["scope_sequence"]["lesson_level_objectives"])
            self.assertTrue(unit["scope_sequence"]["content"])
            self.assertEqual(len(unit["handoffs"]), 5)
            self.assertTrue(all(agent["decision_summary"] for agent in unit["agents"]))

        content_call = next(payload for model, payload in calls if model is ContentResult)
        completed = content_call["completed_scope_sequence"]
        self.assertTrue(completed["standards_addressed"])
        self.assertTrue(completed["course_level_objectives"])
        self.assertTrue(completed["essential_questions"])
        self.assertTrue(completed["lesson_level_objectives"])

        state_events = [event_payload(event) for event in events if event.startswith("event: state")]
        self.assertGreater(len(state_events), 40)
        architect_working = state_events[0]["course"]
        self.assertEqual(architect_working["course_architect"]["status"], AgentStatus.WORKING.value)
        active_agent_snapshots = [
            state["course"] for state in state_events
            if state["course"]["workflow"]["current_agent"] == "standards_analyst"
        ]
        self.assertTrue(any(
            snapshot["units"][0]["agents"][0]["status"] == AgentStatus.RECEIVING_INPUT.value
            for snapshot in active_agent_snapshots
        ))
        self.assertTrue(any(
            snapshot["units"][0]["agents"][0]["status"] == AgentStatus.WORKING.value
            for snapshot in active_agent_snapshots
        ))

    async def test_failure_marks_only_active_agent_and_preserves_upstream_work(self):
        async def fake_call(instructions, input_payload, result_model, max_tokens=4000):
            if result_model is InquiryResult:
                raise RuntimeError("Inquiry service unavailable")
            return result_for(result_model, input_payload)

        with patch("app.services.course_factory_service._call_agent", new=AsyncMock(side_effect=fake_call)):
            events = await collect(CourseFactoryService())

        error = event_payload(events[-1])
        course = error["course"]
        first = course["units"][0]
        self.assertEqual(course["workflow"]["status"], WorkflowStatus.ERROR.value)
        self.assertEqual(first["status"], UnitStatus.ERROR.value)
        self.assertEqual([agent["status"] for agent in first["agents"]], [
            AgentStatus.COMPLETE.value,
            AgentStatus.COMPLETE.value,
            AgentStatus.ERROR.value,
            AgentStatus.WAITING.value,
            AgentStatus.WAITING.value,
        ])
        self.assertTrue(first["scope_sequence"]["standards_addressed"])
        self.assertTrue(first["scope_sequence"]["course_level_objectives"])
        self.assertFalse(first["scope_sequence"]["lesson_level_objectives"])


if __name__ == "__main__":
    unittest.main()
