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
        return "LESSON DATA:\nTopic: Introduction to Quadratic Equations\nGoal: Understand the standard form ax^2 + bx + c = 0."
    return "LESSON DATA:\nTopic: General Math Review\nGoal: Practice core skills."

# Register them
registry.register("demoUserProfile", demo_user_profile)
registry.register("demoLessonData", demo_lesson_data)
