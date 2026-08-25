from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class AgentStatus(str, Enum):
    WAITING = "waiting"
    RECEIVING_INPUT = "receiving_input"
    WORKING = "working"
    COMPLETE = "complete"
    REVISION_REQUESTED = "revision_requested"
    REVISING = "revising"
    APPROVED = "approved"
    ERROR = "error"


class UnitStatus(str, Enum):
    WAITING = "waiting"
    IN_PROGRESS = "in_progress"
    IN_REVIEW = "in_review"
    REVISION_REQUESTED = "revision_requested"
    APPROVED = "approved"
    ERROR = "error"


class WorkflowStatus(str, Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    ERROR = "error"


class WorkflowAgent(str, Enum):
    COURSE_ARCHITECT = "course_architect"
    STANDARDS_ANALYST = "standards_analyst"
    ALIGNMENT_AGENT = "alignment_agent"
    INQUIRY_DESIGNER = "inquiry_designer"
    LEARNING_OBJECTIVE_DESIGNER = "learning_objective_designer"
    CONTENT_PLANNER = "content_planner"
    ALIGNMENT_REVIEWER = "alignment_reviewer"


class Standard(BaseModel):
    standard_id: str
    description: str
    source: Optional[str] = None


class CourseObjective(BaseModel):
    objective_id: str
    objective_text: str


class EssentialQuestion(BaseModel):
    question_id: str
    question_text: str


class LessonObjective(BaseModel):
    objective_id: str
    objective_text: str
    lesson_id: Optional[str] = None
    lesson_title: Optional[str] = None


class ContentItem(BaseModel):
    content_id: str
    label: str
    category: Optional[str] = None
    supports_objective_ids: List[str] = Field(default_factory=list)


class ScopeSequenceColumns(BaseModel):
    standards_addressed: List[Standard] = Field(default_factory=list)
    course_level_objectives: List[CourseObjective] = Field(default_factory=list)
    essential_questions: List[EssentialQuestion] = Field(default_factory=list)
    lesson_level_objectives: List[LessonObjective] = Field(default_factory=list)
    content: List[ContentItem] = Field(default_factory=list)


class AgentDisplay(BaseModel):
    """UI-safe agent information; never stores hidden model reasoning."""

    agent_name: WorkflowAgent
    status: AgentStatus = AgentStatus.WAITING
    input_summary: str = ""
    activity_summary: str = ""
    decision_summary: str = ""
    output_summary: str = ""
    structured_output: Dict[str, Any] = Field(default_factory=dict)
    error_message: Optional[str] = None


class AgentResponse(BaseModel):
    """Validated public response shared by every specialized model call."""

    input_summary: str
    activity_summary: str
    decision_summary: str
    output_summary: str
    structured_output: Dict[str, Any]


class UnitPlan(BaseModel):
    unit_id: str
    unit_title: str
    unit_description: str


class CourseArchitectOutput(BaseModel):
    course_context: str
    course_objectives: List[CourseObjective]
    units: List[UnitPlan] = Field(min_length=8, max_length=8)


class StandardsAnalystOutput(BaseModel):
    standards_source_summary: str
    standards: List[Standard]


class AlignmentAgentOutput(BaseModel):
    course_level_objectives: List[CourseObjective]


class InquiryDesignerOutput(BaseModel):
    essential_questions: List[EssentialQuestion]


class LearningObjectiveDesignerOutput(BaseModel):
    lesson_level_objectives: List[LessonObjective]


class ContentPlannerOutput(BaseModel):
    content: List[ContentItem]


class Handoff(BaseModel):
    handoff_id: str
    from_agent: WorkflowAgent
    to_agent: WorkflowAgent
    unit_id: Optional[str] = None
    artifact_summary: str
    artifact_keys: List[str] = Field(default_factory=list)
    status: str = "pending"


class RevisionRequest(BaseModel):
    request_id: str
    requested_by: WorkflowAgent = WorkflowAgent.ALIGNMENT_REVIEWER
    target_agent: WorkflowAgent
    issue_summary: str
    requested_change: str
    status: str = "open"
    cycle: int = 1


class ReviewerFeedback(BaseModel):
    approved: bool = False
    summary: str = ""
    alignment_issues: List[str] = Field(default_factory=list)
    revision_request: Optional[RevisionRequest] = None


class LearningObjective(BaseModel):
    objective_id: str
    objective_text: str


class Activation(BaseModel):
    activation_id: str
    activation_text: str


class CourseLesson(BaseModel):
    lesson_id: str
    lesson_title: str
    learning_objective: LearningObjective
    activation: Activation


class ScopeSequenceUnit(BaseModel):
    unit_id: str
    unit_title: str
    unit_description: str = ""
    lessons: List[CourseLesson] = Field(default_factory=list)
    scope_sequence: ScopeSequenceColumns = Field(default_factory=ScopeSequenceColumns)
    agents: List[AgentDisplay] = Field(default_factory=list)
    handoffs: List[Handoff] = Field(default_factory=list)
    reviewer_feedback: Optional[ReviewerFeedback] = None
    revision_count: int = 0
    status: UnitStatus = UnitStatus.WAITING


class CourseWorkflowState(BaseModel):
    status: WorkflowStatus = WorkflowStatus.NOT_STARTED
    current_unit_id: Optional[str] = None
    current_agent: Optional[WorkflowAgent] = None
    max_revision_cycles: int = Field(default=2, ge=0)


class CourseWorkflow(BaseModel):
    schema_version: str = "1.0"
    subject: str
    course_context: str = ""
    standards_source_summary: str = ""
    course_objectives: List[CourseObjective] = Field(default_factory=list)
    units: List[ScopeSequenceUnit] = Field(default_factory=list)
    course_architect: Optional[AgentDisplay] = None
    handoffs: List[Handoff] = Field(default_factory=list)
    workflow: CourseWorkflowState = Field(default_factory=CourseWorkflowState)
