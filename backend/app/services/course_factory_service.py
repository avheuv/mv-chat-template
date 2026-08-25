import json
from typing import Any, AsyncGenerator, Dict, List, Type, TypeVar
from uuid import uuid4

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from app.core.config import settings
from app.models.course_factory import (
    AgentDisplay,
    AgentStatus,
    ContentItem,
    CourseObjective,
    CourseWorkflow,
    CourseWorkflowState,
    EssentialQuestion,
    Handoff,
    LessonObjective,
    ScopeSequenceUnit,
    Standard,
    UnitStatus,
    WorkflowAgent,
    WorkflowStatus,
)

DEFAULT_MODEL = "gpt-5.4-mini"
UNIT_AGENTS = (
    WorkflowAgent.STANDARDS_ANALYST,
    WorkflowAgent.ALIGNMENT_AGENT,
    WorkflowAgent.INQUIRY_DESIGNER,
    WorkflowAgent.LEARNING_OBJECTIVE_DESIGNER,
    WorkflowAgent.CONTENT_PLANNER,
)
AGENT_LABELS = {
    WorkflowAgent.COURSE_ARCHITECT: "Course Architect",
    WorkflowAgent.STANDARDS_ANALYST: "Standards Analyst",
    WorkflowAgent.ALIGNMENT_AGENT: "Alignment Agent",
    WorkflowAgent.INQUIRY_DESIGNER: "Inquiry Designer",
    WorkflowAgent.LEARNING_OBJECTIVE_DESIGNER: "Learning Objective Designer",
    WorkflowAgent.CONTENT_PLANNER: "Content Planner",
}


class AgentSummary(BaseModel):
    activity_summary: str
    decision_summary: str
    output_summary: str


class ArchitectUnit(BaseModel):
    unit_id: str
    unit_title: str
    unit_description: str


class ArchitectResult(AgentSummary):
    course_context: str
    standards_source_summary: str
    course_objectives: List[CourseObjective] = Field(min_length=1)
    units: List[ArchitectUnit] = Field(min_length=1)


class StandardsResult(AgentSummary):
    standards_addressed: List[Standard] = Field(min_length=1)


class AlignmentResult(AgentSummary):
    course_level_objectives: List[CourseObjective] = Field(min_length=1)


class InquiryResult(AgentSummary):
    essential_questions: List[EssentialQuestion] = Field(min_length=1)


class LearningObjectivesResult(AgentSummary):
    lesson_level_objectives: List[LessonObjective] = Field(min_length=1)


class ContentResult(AgentSummary):
    content: List[ContentItem] = Field(min_length=1)


AgentResult = TypeVar("AgentResult", bound=BaseModel)


def _json_event(event_type: str, payload: Dict[str, Any]) -> str:
    return f"event: {event_type}\ndata: {json.dumps(payload)}\n\n"


def _state_event(course: CourseWorkflow, message: str) -> str:
    """Stream a UI-safe workflow snapshot; agent summaries never contain private reasoning."""
    return _json_event("state", {
        "course": course.model_dump(mode="json"),
        "message": message,
    })


async def _call_agent(
    instructions: str,
    input_payload: Dict[str, Any],
    result_model: Type[AgentResult],
    max_tokens: int = 4000,
) -> AgentResult:
    """Call one instructional-design agent and validate its JSON before handoff."""
    if not settings.openai_api_key:
        raise RuntimeError("OpenAI API key is not configured")

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    response = await client.chat.completions.parse(
        model=DEFAULT_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    instructions
                    + " Summaries must be concise, displayable explanations; do not include private reasoning."
                ),
            },
            {"role": "user", "content": json.dumps(input_payload)},
        ],
        response_format=result_model,
        max_completion_tokens=max_tokens,
    )
    message = response.choices[0].message
    if message.parsed is None:
        refusal = getattr(message, "refusal", None)
        raise RuntimeError(refusal or "Agent returned no validated structured output.")
    return message.parsed


def _agent_display(unit: ScopeSequenceUnit, agent: WorkflowAgent) -> AgentDisplay:
    return next(display for display in unit.agents if display.agent_name == agent)


def _structured_context(course: CourseWorkflow, unit: ScopeSequenceUnit) -> Dict[str, Any]:
    """Create the cumulative, explicit handoff payload for the next unit agent."""
    return {
        "course": {
            "subject": course.subject,
            "course_context": course.course_context,
            "standards_source_summary": course.standards_source_summary,
            "course_objectives": [item.model_dump(mode="json") for item in course.course_objectives],
        },
        "unit": {
            "unit_id": unit.unit_id,
            "unit_title": unit.unit_title,
            "unit_description": unit.unit_description,
        },
        "completed_scope_sequence": unit.scope_sequence.model_dump(mode="json"),
    }


def _summary_for_input(course: CourseWorkflow, unit: ScopeSequenceUnit, agent: WorkflowAgent) -> str:
    upstream = {
        WorkflowAgent.STANDARDS_ANALYST: "course and unit context plus the standards-source guidance",
        WorkflowAgent.ALIGNMENT_AGENT: "course objectives and the selected unit standards",
        WorkflowAgent.INQUIRY_DESIGNER: "selected standards and aligned course objectives",
        WorkflowAgent.LEARNING_OBJECTIVE_DESIGNER: "standards, aligned objectives, and essential questions",
        WorkflowAgent.CONTENT_PLANNER: "all upstream artifacts including lesson-level objectives",
    }[agent]
    return f"{unit.unit_id} ({unit.unit_title}): {upstream} for {course.subject}."


def _record_handoff(
    course: CourseWorkflow,
    unit: ScopeSequenceUnit,
    from_agent: WorkflowAgent,
    to_agent: WorkflowAgent,
    artifact_keys: List[str],
) -> None:
    handoff = Handoff(
        handoff_id=str(uuid4()),
        from_agent=from_agent,
        to_agent=to_agent,
        unit_id=unit.unit_id,
        artifact_summary=f"Passed {', '.join(artifact_keys)} for {unit.unit_title}.",
        artifact_keys=artifact_keys,
        status="complete",
    )
    unit.handoffs.append(handoff)
    course.handoffs.append(handoff)


class CourseFactoryService:
    async def _run_unit_agent(
        self,
        course: CourseWorkflow,
        unit: ScopeSequenceUnit,
        agent: WorkflowAgent,
    ) -> None:
        display = _agent_display(unit, agent)
        display.status = AgentStatus.WORKING
        display.input_summary = _summary_for_input(course, unit, agent)
        display.activity_summary = f"{AGENT_LABELS[agent]} is working on {unit.unit_title}."
        course.workflow.current_unit_id = unit.unit_id
        course.workflow.current_agent = agent

        context = _structured_context(course, unit)
        if agent == WorkflowAgent.STANDARDS_ANALYST:
            result = await _call_agent(
                "You are the Standards Analyst. Select appropriate, recognizable existing standards for this unit. Prefer standards from the supplied source guidance; never invent official codes or wording. If no jurisdiction is specified, identify the framework in source and use accurate framework language.",
                context,
                StandardsResult,
            )
            unit.scope_sequence.standards_addressed = result.standards_addressed
            key = "standards_addressed"
        elif agent == WorkflowAgent.ALIGNMENT_AGENT:
            result = await _call_agent(
                "You are the Alignment Agent. Select only course-level objectives supplied by the Course Architect that substantively align with this unit and its selected standards. Preserve their objective IDs and exact text; do not create new objectives.",
                context,
                AlignmentResult,
            )
            known = {objective.objective_id: objective for objective in course.course_objectives}
            invalid_ids = [item.objective_id for item in result.course_level_objectives if item.objective_id not in known]
            if invalid_ids:
                raise RuntimeError(f"Alignment Agent selected unknown course objective IDs: {', '.join(invalid_ids)}")
            unit.scope_sequence.course_level_objectives = [known[item.objective_id] for item in result.course_level_objectives]
            key = "course_level_objectives"
        elif agent == WorkflowAgent.INQUIRY_DESIGNER:
            result = await _call_agent(
                "You are the Inquiry Designer. Develop meaningful, open-ended conceptual essential questions and important enduring ideas for this unit. Questions must align to upstream standards and objectives and must not merely rewrite objectives as questions.",
                context,
                InquiryResult,
            )
            unit.scope_sequence.essential_questions = result.essential_questions
            key = "essential_questions"
        elif agent == WorkflowAgent.LEARNING_OBJECTIVE_DESIGNER:
            result = await _call_agent(
                "You are the Learning Objective Designer. Create measurable lesson-level objectives using observable student actions and appropriate Bloom's Taxonomy verbs. Prefer 'Students will be able to...' and align every objective to the upstream standards, course objectives, and essential questions.",
                context,
                LearningObjectivesResult,
            )
            unit.scope_sequence.lesson_level_objectives = result.lesson_level_objectives
            key = "lesson_level_objectives"
        else:
            result = await _call_agent(
                "You are the Content Planner. Identify the noun-driven concepts, principles, facts, vocabulary, processes, people, events, ideas, and lesson topics students need to meet the supplied lesson-level objectives. Derive content from the objectives and upstream decisions. Populate supports_objective_ids only with supplied lesson objective IDs.",
                context,
                ContentResult,
            )
            objective_ids = {item.objective_id for item in unit.scope_sequence.lesson_level_objectives}
            unsupported = {
                objective_id
                for item in result.content
                for objective_id in item.supports_objective_ids
                if objective_id not in objective_ids
            }
            if unsupported:
                raise RuntimeError(f"Content Planner referenced unknown lesson objective IDs: {', '.join(sorted(unsupported))}")
            unit.scope_sequence.content = result.content
            key = "content"

        display.status = AgentStatus.COMPLETE
        display.activity_summary = result.activity_summary
        display.decision_summary = result.decision_summary
        display.output_summary = result.output_summary
        display.structured_output = {key: [item.model_dump(mode="json") for item in getattr(result, key)]}

    async def stream_course(self, subject: str) -> AsyncGenerator[str, None]:
        clean_subject = subject.strip()
        if not clean_subject:
            yield _json_event("error", {"message": "Subject is required."})
            return

        course = CourseWorkflow(
            subject=clean_subject,
            workflow=CourseWorkflowState(status=WorkflowStatus.IN_PROGRESS, current_agent=WorkflowAgent.COURSE_ARCHITECT),
            course_architect=AgentDisplay(
                agent_name=WorkflowAgent.COURSE_ARCHITECT,
                status=AgentStatus.WORKING,
                input_summary=f"Requested course: {clean_subject}.",
                activity_summary="Interpreting the request and sequencing the course.",
            ),
        )
        active_display = course.course_architect
        active_unit = None

        try:
            yield _state_event(course, "Course Architect is designing the course structure.")
            architect = await _call_agent(
                "You are the Course Architect. Interpret the requested course and create exactly 8 logically sequenced units from foundations to application. Establish concise course-level context, a practical standards-source strategy, and measurable course-level objectives. Do not create unit Scope & Sequence columns; downstream specialists do that.",
                {"requested_course": clean_subject, "required_unit_count": 8},
                ArchitectResult,
            )
            if len(architect.units) != 8:
                raise RuntimeError(f"Course Architect must return exactly 8 units; received {len(architect.units)}.")
            if len({unit.unit_id for unit in architect.units}) != len(architect.units):
                raise RuntimeError("Course Architect returned duplicate unit IDs.")

            course.course_context = architect.course_context
            course.standards_source_summary = architect.standards_source_summary
            course.course_objectives = architect.course_objectives
            course.units = [
                ScopeSequenceUnit(
                    unit_id=item.unit_id,
                    unit_title=item.unit_title,
                    unit_description=item.unit_description,
                    agents=[AgentDisplay(agent_name=agent) for agent in UNIT_AGENTS],
                )
                for item in architect.units
            ]
            active_display.status = AgentStatus.COMPLETE
            active_display.activity_summary = architect.activity_summary
            active_display.decision_summary = architect.decision_summary
            active_display.output_summary = architect.output_summary
            active_display.structured_output = {
                "course_context": course.course_context,
                "standards_source_summary": course.standards_source_summary,
                "course_objectives": [item.model_dump(mode="json") for item in course.course_objectives],
                "units": [item.model_dump(mode="json") for item in architect.units],
            }
            yield _state_event(course, f"Course Architect created {len(course.units)} units.")

            for unit_index, unit in enumerate(course.units):
                active_unit = unit
                unit.status = UnitStatus.IN_PROGRESS
                course.workflow.current_unit_id = unit.unit_id
                previous_agent = WorkflowAgent.COURSE_ARCHITECT
                previous_keys = ["course_context", "course_objectives", "units"]
                for agent in UNIT_AGENTS:
                    _record_handoff(course, unit, previous_agent, agent, previous_keys)
                    active_display = _agent_display(unit, agent)
                    active_display.status = AgentStatus.RECEIVING_INPUT
                    active_display.input_summary = _summary_for_input(course, unit, agent)
                    active_display.activity_summary = f"Preparing to work on {unit.unit_title}."
                    course.workflow.current_agent = agent
                    yield _state_event(
                        course,
                        f"Orchestrator passed the next artifact to {AGENT_LABELS[agent]} for Unit {unit_index + 1} of {len(course.units)}.",
                    )
                    active_display.status = AgentStatus.WORKING
                    active_display.activity_summary = f"{AGENT_LABELS[agent]} is working on {unit.unit_title}."
                    yield _state_event(course, f"{AGENT_LABELS[agent]} is working on {unit.unit_title}.")
                    await self._run_unit_agent(course, unit, agent)
                    yield _state_event(course, f"{AGENT_LABELS[agent]} completed its work on {unit.unit_title}.")
                    previous_agent = agent
                    previous_keys = list(active_display.structured_output)
                unit.status = UnitStatus.COMPLETE
                yield _state_event(course, f"Unit {unit_index + 1} of {len(course.units)} is complete.")

            course.workflow.status = WorkflowStatus.COMPLETE
            course.workflow.current_unit_id = None
            course.workflow.current_agent = None
            yield _json_event("complete", {
                "course": course.model_dump(mode="json"),
                "message": "Scope & Sequence workflow complete.",
            })
        except Exception as exc:
            course.workflow.status = WorkflowStatus.ERROR
            if active_display is not None:
                active_display.status = AgentStatus.ERROR
                active_display.error_message = str(exc)
            if active_unit is not None:
                active_unit.status = UnitStatus.ERROR
            yield _json_event("error", {
                "message": str(exc),
                "course": course.model_dump(mode="json"),
            })


course_factory_service = CourseFactoryService()
