import json
from typing import Any, AsyncGenerator, Dict, List, Tuple, Type

from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from app.core.config import settings
from app.models.course_factory import (
    Activation,
    AgentDisplay,
    AgentResponse,
    AgentStatus,
    AlignmentAgentOutput,
    ContentPlannerOutput,
    CourseArchitectOutput,
    CourseLesson,
    CourseWorkflow,
    CourseWorkflowState,
    Handoff,
    InquiryDesignerOutput,
    LearningObjective,
    LearningObjectiveDesignerOutput,
    ScopeSequenceUnit,
    StandardsAnalystOutput,
    UnitStatus,
    WorkflowAgent,
    WorkflowStatus,
)
from app.services.course_factory_prompts import build_agent_instructions

DEFAULT_MODEL = "gpt-5.4-mini"
UNIT_AGENT_SEQUENCE: Tuple[WorkflowAgent, ...] = (
    WorkflowAgent.STANDARDS_ANALYST,
    WorkflowAgent.ALIGNMENT_AGENT,
    WorkflowAgent.INQUIRY_DESIGNER,
    WorkflowAgent.LEARNING_OBJECTIVE_DESIGNER,
    WorkflowAgent.CONTENT_PLANNER,
)
AGENT_OUTPUT_MODELS: Dict[WorkflowAgent, Type[BaseModel]] = {
    WorkflowAgent.COURSE_ARCHITECT: CourseArchitectOutput,
    WorkflowAgent.STANDARDS_ANALYST: StandardsAnalystOutput,
    WorkflowAgent.ALIGNMENT_AGENT: AlignmentAgentOutput,
    WorkflowAgent.INQUIRY_DESIGNER: InquiryDesignerOutput,
    WorkflowAgent.LEARNING_OBJECTIVE_DESIGNER: LearningObjectiveDesignerOutput,
    WorkflowAgent.CONTENT_PLANNER: ContentPlannerOutput,
}


def _json_event(event_type: str, payload: Dict[str, Any]) -> str:
    return f"event: {event_type}\ndata: {json.dumps(payload)}\n\n"


def _agent_label(agent: WorkflowAgent) -> str:
    return agent.value.replace("_", " ").title()


async def _call_agent(
    agent: WorkflowAgent,
    inputs: Dict[str, Any],
    output_model: Type[BaseModel],
    max_tokens: int = 4000,
) -> Tuple[AgentDisplay, BaseModel]:
    """Call one agent and validate both its public summaries and instructional artifact."""
    if not settings.openai_api_key:
        raise RuntimeError("OpenAI API key is not configured")

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    response = await client.chat.completions.create(
        model=DEFAULT_MODEL,
        messages=[
            {
                "role": "system",
                "content": build_agent_instructions(
                    agent,
                    json.dumps(output_model.model_json_schema()),
                ),
            },
            {"role": "user", "content": json.dumps(inputs)},
        ],
        response_format={"type": "json_object"},
        max_completion_tokens=max_tokens,
    )
    try:
        raw = json.loads(response.choices[0].message.content or "{}")
        envelope = AgentResponse.model_validate(raw)
        artifact = output_model.model_validate(envelope.structured_output)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise RuntimeError(f"{_agent_label(agent)} returned an invalid structured response: {exc}") from exc

    display = AgentDisplay(
        agent_name=agent,
        status=AgentStatus.COMPLETE,
        input_summary=envelope.input_summary,
        activity_summary=envelope.activity_summary,
        decision_summary=envelope.decision_summary,
        output_summary=envelope.output_summary,
        structured_output=artifact.model_dump(mode="json"),
    )
    return display, artifact


def _handoff(
    unit_id: str,
    from_agent: WorkflowAgent,
    to_agent: WorkflowAgent,
    artifact_keys: List[str],
    index: int,
) -> Handoff:
    return Handoff(
        handoff_id=f"{unit_id}-H{index:02d}",
        unit_id=unit_id,
        from_agent=from_agent,
        to_agent=to_agent,
        artifact_summary=f"{_agent_label(from_agent)} output plus unit and course context.",
        artifact_keys=artifact_keys,
        status="complete",
    )


def _compatibility_lessons(unit: ScopeSequenceUnit) -> List[CourseLesson]:
    """Keep the current accordion and exports useful until the Phase 4 table replaces them."""
    questions = unit.scope_sequence.essential_questions
    lessons = []
    for index, objective in enumerate(unit.scope_sequence.lesson_level_objectives, start=1):
        lesson_id = objective.lesson_id or f"{unit.unit_id}-L{index:02d}"
        question = questions[(index - 1) % len(questions)].question_text if questions else (
            f"What might make {objective.lesson_title or unit.unit_title} important?"
        )
        lessons.append(CourseLesson(
            lesson_id=lesson_id,
            lesson_title=objective.lesson_title or f"Lesson {index}",
            learning_objective=LearningObjective(
                objective_id=objective.objective_id,
                objective_text=objective.objective_text,
            ),
            activation=Activation(
                activation_id=f"{lesson_id}-A01",
                activation_text=question,
            ),
        ))
    return lessons


class CourseFactoryService:
    async def stream_course(self, subject: str) -> AsyncGenerator[str, None]:
        clean_subject = subject.strip()
        if not clean_subject:
            yield _json_event("error", {"message": "Subject is required."})
            return

        try:
            yield _json_event("log", {"message": f"Course Factory received the subject: {clean_subject}."})
            yield _json_event("log", {"message": "Course Architect is establishing course context, objectives, and units."})
            architect_display, architect_artifact = await _call_agent(
                WorkflowAgent.COURSE_ARCHITECT,
                {"subject": clean_subject},
                CourseArchitectOutput,
            )
            architect = CourseArchitectOutput.model_validate(architect_artifact)

            course = CourseWorkflow(
                subject=clean_subject,
                course_context=architect.course_context,
                course_objectives=architect.course_objectives,
                units=[
                    ScopeSequenceUnit(
                        unit_id=unit.unit_id,
                        unit_title=unit.unit_title,
                        unit_description=unit.unit_description,
                    )
                    for unit in architect.units
                ],
                course_architect=architect_display,
                workflow=CourseWorkflowState(status=WorkflowStatus.IN_PROGRESS),
            )

            for unit in course.units:
                unit.status = UnitStatus.IN_PROGRESS
                course.workflow.current_unit_id = unit.unit_id
                previous_agent = WorkflowAgent.COURSE_ARCHITECT
                previous_keys = ["course_context", "course_objectives", "units"]

                for agent_index, agent in enumerate(UNIT_AGENT_SEQUENCE, start=1):
                    course.workflow.current_agent = agent
                    yield _json_event("log", {
                        "message": f"{_agent_label(agent)} is working on {unit.unit_id}: {unit.unit_title}."
                    })
                    unit.handoffs.append(_handoff(
                        unit.unit_id,
                        previous_agent,
                        agent,
                        previous_keys,
                        agent_index,
                    ))
                    inputs = {
                        "subject": course.subject,
                        "course_context": course.course_context,
                        "course_objectives": [item.model_dump(mode="json") for item in course.course_objectives],
                        "unit": {
                            "unit_id": unit.unit_id,
                            "unit_title": unit.unit_title,
                            "unit_description": unit.unit_description,
                        },
                        "scope_sequence_so_far": unit.scope_sequence.model_dump(mode="json"),
                        "standards_source": None,
                    }
                    display, artifact = await _call_agent(agent, inputs, AGENT_OUTPUT_MODELS[agent])
                    unit.agents.append(display)

                    if isinstance(artifact, StandardsAnalystOutput):
                        unit.scope_sequence.standards_addressed = artifact.standards
                        if not course.standards_source_summary:
                            course.standards_source_summary = artifact.standards_source_summary
                        previous_keys = ["standards_addressed", "standards_source_summary"]
                    elif isinstance(artifact, AlignmentAgentOutput):
                        unit.scope_sequence.course_level_objectives = artifact.course_level_objectives
                        previous_keys = ["standards_addressed", "course_level_objectives"]
                    elif isinstance(artifact, InquiryDesignerOutput):
                        unit.scope_sequence.essential_questions = artifact.essential_questions
                        previous_keys = ["course_level_objectives", "essential_questions"]
                    elif isinstance(artifact, LearningObjectiveDesignerOutput):
                        unit.scope_sequence.lesson_level_objectives = artifact.lesson_level_objectives
                        previous_keys = ["essential_questions", "lesson_level_objectives"]
                    elif isinstance(artifact, ContentPlannerOutput):
                        unit.scope_sequence.content = artifact.content
                        previous_keys = ["lesson_level_objectives", "content"]
                    previous_agent = agent

                unit.lessons = _compatibility_lessons(unit)
                unit.status = UnitStatus.IN_REVIEW

            course.workflow.status = WorkflowStatus.COMPLETE
            course.workflow.current_unit_id = None
            course.workflow.current_agent = None
            yield _json_event("complete", {
                "course": course.model_dump(mode="json"),
                "message": "Sequential Scope & Sequence draft complete. Alignment review is reserved for Phase 5.",
            })
        except Exception as exc:
            yield _json_event("error", {"message": str(exc)})


course_factory_service = CourseFactoryService()
