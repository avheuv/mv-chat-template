from typing import Callable, Awaitable, Dict, Any, Optional

# A Context Builder function takes a dict of dynamic inputs and a session_id
# and returns a string that will be injected into the system prompt.
ContextBuilderFunc = Callable[[Dict[str, str], str], Awaitable[str]]

class ContextBuilderRegistry:
    def __init__(self):
        self._builders: Dict[str, ContextBuilderFunc] = {}

    def register(self, name: str, builder: ContextBuilderFunc):
        self._builders[name] = builder

    def get(self, name: str) -> Optional[ContextBuilderFunc]:
        return self._builders.get(name)

registry = ContextBuilderRegistry()

# ---------------------------------------------------------
# Sample Demo Context Builders
# ---------------------------------------------------------

async def demo_user_profile(inputs: Dict[str, str], session_id: str) -> str:
    """
    A demo builder that returns fake student profile data.
    In a real app, this would use Firestore or an API to fetch real data.
    """
    user_id = inputs.get("user_id", "unknown")
    if user_id == "student-123":
        return "STUDENT PROFILE:\nName: Alex\nGrade: 10\nFavorite Subject: Science\nStruggling with: Algebra"
    return f"STUDENT PROFILE:\nName: Unknown Student (ID: {user_id})\nGrade: N/A\nNotes: No profile data found."

async def demo_lesson_data(inputs: Dict[str, str], session_id: str) -> str:
    """
    A demo builder that returns fake lesson data based on a lesson_code.
    """
    lesson_code = inputs.get("lesson_code", "default")
    if lesson_code == "quadratics":
        return "LESSON DATA:\nTopic: Introduction to Quadratic Equations\nGoal: Understand the standard form ax^2 + bx + c = 0.\n\nVIDEO RESOURCE:\nTitle: Intro to Quadratics\nURL: https://example.com/quadratics"
    if lesson_code == "biology":
        return "LESSON DATA:\nTopic: Cell Structure\nGoal: Understand the function of the mitochondria.\n\nVIDEO RESOURCE:\nTitle: The Powerhouse of the Cell\nURL: https://example.com/mitochondria"
    return "LESSON DATA:\nTopic: General Math Review\nGoal: Practice core skills."

async def fetch_student_interests(inputs: Dict[str, str], session_id: str) -> str:
    """
    Fetches the student profile from Firestore (saved by the profile_builder).
    """
    from app.services.firestore_service import firestore_service
    user_id = inputs.get("user_id", "unknown")

    if firestore_service.db:
        doc = await firestore_service.get_document("users", user_id)
        if doc and "interests" in doc:
            interests_list = ", ".join(doc.get("interests", []))
            summary = doc.get("summary", "")
            return f"STUDENT INTERESTS:\nInterests: {interests_list}\nSummary: {summary}"
        # If the DB is connected but the user has no profile yet, return empty
        # to ensure the AI doesn't hallucinate mock interests for a new user.
        return "STUDENT INTERESTS:\nNo existing interests found. This is a new student."

    # Fallback/Mock only if Firestore is completely disabled/missing
    return f"STUDENT INTERESTS:\nInterests: video games, soccer\nSummary: {user_id} likes playing sports and gaming."

async def fetch_lesson_data(inputs: Dict[str, str], session_id: str) -> str:
    """
    Fetches the lesson data from Firestore using the lesson_code.
    """
    from app.services.firestore_service import firestore_service
    lesson_code = inputs.get("lesson_code", "default")

    if firestore_service.db:
        doc = await firestore_service.get_document("lesson_topics", lesson_code)
        if doc:
            title = doc.get("title", "Unknown Lesson")
            objectives = doc.get("objectives", "No objectives provided.")
            result_text = f"LESSON DATA:\nTopic: {title}\nGoal: {objectives}"

            # Inject video resource if present
            video = doc.get("video")
            if video and isinstance(video, dict):
                v_title = video.get("title", "Unknown Title")
                v_url = video.get("url", "")
                result_text += f"\n\nVIDEO RESOURCE:\nTitle: {v_title}\nURL: {v_url}"

            return result_text

    # Fallback if Firestore is not available
    return await demo_lesson_data(inputs, session_id)

async def identify_primary_misconception(inputs: Dict[str, str], session_id: str) -> str:
    """Use GPT-5.4 to identify the most instructionally important misconception."""
    from app.services.llm_service import llm_service

    lesson_data = await fetch_lesson_data(inputs, session_id)
    misconception = await llm_service.generate_primary_misconception(lesson_data)
    return f"PRIMARY MISCONCEPTION (MODEL-IDENTIFIED):\n{misconception}"

# Register them
registry.register("demoUserProfile", demo_user_profile)
registry.register("demoLessonData", demo_lesson_data)
registry.register("fetchStudentInterests", fetch_student_interests)
registry.register("fetchLessonData", fetch_lesson_data)
registry.register("identifyPrimaryMisconception", identify_primary_misconception)
