import json
from typing import Any, AsyncGenerator, Dict, List

from openai import AsyncOpenAI

from app.core.config import settings
from app.models.course_factory import (
    Activation,
    AgentDisplay,
    AgentStatus,
    CourseLesson,
    CourseWorkflow,
    CourseWorkflowState,
    LearningObjective,
    ScopeSequenceUnit,
    UnitStatus,
    WorkflowAgent,
    WorkflowStatus,
)

client = AsyncOpenAI(api_key=settings.openai_api_key)

DEFAULT_MODEL = "gpt-5.4-mini"


def _json_event(event_type: str, payload: Dict[str, Any]) -> str:
    return f"event: {event_type}\ndata: {json.dumps(payload)}\n\n"


def _parse_json(content: str, fallback: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return json.loads(content or "{}")
    except json.JSONDecodeError:
        return fallback


async def _call_agent(agent_name: str, instructions: str, user_prompt: str, max_tokens: int = 4000) -> Dict[str, Any]:
    if not settings.openai_api_key:
        raise RuntimeError("OpenAI API key is not configured")

    response = await client.chat.completions.create(
        model=DEFAULT_MODEL,
        messages=[
            {"role": "system", "content": instructions},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        max_completion_tokens=max_tokens,
    )
    return _parse_json(response.choices[0].message.content or "{}", {"agent": agent_name})


class CourseFactoryService:
    async def stream_course(self, subject: str) -> AsyncGenerator[str, None]:
        clean_subject = subject.strip()
        if not clean_subject:
            yield _json_event("error", {"message": "Subject is required."})
            return

        try:
            yield _json_event("log", {"message": f"Course Factory received the subject: {clean_subject}."})

            yield _json_event("log", {"message": "Course Architect is creating the 8-unit course structure."})
            architect = await _call_agent(
                "Course Architect",
                (
                    "You are the Course Architect. Create the overall course structure. "
                    "Create exactly 8 units, ordered from foundational concepts to advanced applications. "
                    "Create a title and one concise description for each unit. Do not create lessons, "
                    "learning objectives, or activations. Return only JSON: "
                    "{\"units\":[{\"unit_id\":\"U01\",\"unit_title\":\"...\",\"unit_description\":\"...\"}]}"
                ),
                f"Create the unit structure for a course about {clean_subject}.",
            )
            units = architect.get("units", [])[:8]

            yield _json_event("log", {"message": "Lesson Planner is adding exactly 3 lessons to each unit."})
            lessons_data = await _call_agent(
                "Lesson Planner",
                (
                    "You are the Lesson Planner. Create exactly 3 lessons for each provided unit. "
                    "Lessons must align with the unit, be specific, student-facing, and appropriate for an online course. "
                    "Do not create objectives or activations. Return only JSON: "
                    "{\"lessons\":[{\"unit_id\":\"U01\",\"lesson_id\":\"U01-L01\",\"lesson_title\":\"...\"}]}"
                ),
                json.dumps({"subject": clean_subject, "units": units}),
            )
            lessons = lessons_data.get("lessons", [])

            yield _json_event("log", {"message": "Objective Writer is writing one measurable objective for each lesson."})
            objectives_data = await _call_agent(
                "Objective Writer",
                (
                    "You are the Objective Writer. Create exactly 1 learning objective per lesson. "
                    "Use measurable verbs such as explain, compare, classify, calculate, evaluate, predict, interpret, or analyze. "
                    "Avoid understand, know, learn, appreciate, and explore. Objectives must align directly with lesson titles. "
                    "Return only JSON: {\"objectives\":[{\"lesson_id\":\"U01-L01\",\"objective_id\":\"U01-L01-O01\",\"objective_text\":\"...\"}]}"
                ),
                json.dumps({"subject": clean_subject, "units": units, "lessons": lessons}),
            )
            objectives = objectives_data.get("objectives", [])

            yield _json_event("log", {"message": "Activation Writer is creating one short curiosity-building activation for each lesson."})
            activations_data = await _call_agent(
                "Activation Writer",
                (
                    "You are the Activation Writer. Create exactly 1 activation for each lesson. "
                    "Each activation must be a puzzle, scenario, provocative question, misconception challenge, or prediction task. "
                    "Keep each activation under 75 words. Do not provide the answer. Create curiosity and relevance. "
                    "Return only JSON: {\"activations\":[{\"lesson_id\":\"U01-L01\",\"activation_id\":\"U01-L01-A01\",\"activation_text\":\"...\"}]}"
                ),
                json.dumps({"subject": clean_subject, "units": units, "lessons": lessons}),
            )
            activations = activations_data.get("activations", [])

            yield _json_event("log", {"message": "Course Factory is assembling the final nested course outline."})
            objective_by_lesson = {item.get("lesson_id"): item for item in objectives}
            activation_by_lesson = {item.get("lesson_id"): item for item in activations}
            lessons_by_unit: Dict[str, List[Dict[str, Any]]] = {}
            for lesson_index, lesson in enumerate(lessons, start=1):
                lesson_id = lesson.get("lesson_id") or f"LESSON-{lesson_index:02d}"
                objective = objective_by_lesson.get(lesson_id) or {}
                activation = activation_by_lesson.get(lesson_id) or {}
                lessons_by_unit.setdefault(lesson.get("unit_id", ""), []).append({
                    "lesson_id": lesson_id,
                    "lesson_title": lesson.get("lesson_title") or "Untitled Lesson",
                    "learning_objective": {
                        "objective_id": objective.get("objective_id") or f"{lesson_id}-O01",
                        "objective_text": objective.get("objective_text")
                        or "Analyze the core ideas introduced in this lesson.",
                    },
                    "activation": {
                        "activation_id": activation.get("activation_id") or f"{lesson_id}-A01",
                        "activation_text": activation.get("activation_text")
                        or "What surprising question could reveal why this lesson matters?",
                    },
                })

            workflow_units = []
            for index, unit in enumerate(units, start=1):
                unit_id = unit.get("unit_id") or f"U{index:02d}"
                unit_lessons = [
                    CourseLesson(
                        lesson_id=lesson["lesson_id"],
                        lesson_title=lesson["lesson_title"],
                        learning_objective=LearningObjective(**lesson["learning_objective"]),
                        activation=Activation(**lesson["activation"]),
                    )
                    for lesson in lessons_by_unit.get(unit.get("unit_id", ""), [])[:3]
                ]
                workflow_units.append(ScopeSequenceUnit(
                    unit_id=unit_id,
                    unit_title=unit.get("unit_title") or "Untitled Unit",
                    unit_description=unit.get("unit_description") or "",
                    lessons=unit_lessons,
                    agents=[
                        AgentDisplay(agent_name=agent)
                        for agent in (
                            WorkflowAgent.STANDARDS_ANALYST,
                            WorkflowAgent.ALIGNMENT_AGENT,
                            WorkflowAgent.INQUIRY_DESIGNER,
                            WorkflowAgent.LEARNING_OBJECTIVE_DESIGNER,
                            WorkflowAgent.CONTENT_PLANNER,
                            WorkflowAgent.ALIGNMENT_REVIEWER,
                        )
                    ],
                    status=UnitStatus.WAITING,
                ))

            course = CourseWorkflow(
                subject=clean_subject,
                course_context=f"An eight-unit course about {clean_subject}.",
                units=workflow_units,
                course_architect=AgentDisplay(
                    agent_name=WorkflowAgent.COURSE_ARCHITECT,
                    status=AgentStatus.COMPLETE,
                    input_summary=f"Requested course subject: {clean_subject}.",
                    activity_summary="Organized the course into eight sequenced units.",
                    decision_summary="Sequenced foundational concepts before advanced applications.",
                    output_summary=f"Created {len(workflow_units)} unit titles and descriptions.",
                    structured_output={"unit_ids": [unit.unit_id for unit in workflow_units]},
                ),
                workflow=CourseWorkflowState(status=WorkflowStatus.COMPLETE),
            )
            yield _json_event("complete", {
                "course": course.model_dump(mode="json"),
                "message": "Course outline complete.",
            })
        except Exception as exc:
            yield _json_event("error", {"message": str(exc)})


course_factory_service = CourseFactoryService()
