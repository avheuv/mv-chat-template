import json
from typing import Callable, Awaitable, Dict, Any, Optional

# A Save Handler function takes a session_id, user_id, prototype_id, and the structured data
SaveHandlerFunc = Callable[[str, str, str, Dict[str, Any]], Awaitable[None]]

class SaveHandlerRegistry:
    def __init__(self):
        self._handlers: Dict[str, SaveHandlerFunc] = {}

    def register(self, name: str, handler: SaveHandlerFunc):
        self._handlers[name] = handler

    def get(self, name: str) -> Optional[SaveHandlerFunc]:
        return self._handlers.get(name)

registry = SaveHandlerRegistry()

# ---------------------------------------------------------
# Sample Demo Save Handlers
# ---------------------------------------------------------

async def default_artifact_save(session_id: str, user_id: str, prototype_id: str, data: Dict[str, Any]):
    """
    A simple save handler that persists the output to Firestore as an artifact.
    """
    from app.services.firestore_service import firestore_service

    artifact_id = f"{session_id}-artifact"
    payload = {
        "user_id": user_id,
        "prototype_id": prototype_id,
        "session_id": session_id,
        "data": data
    }

    # Simple direct to firestore. We use simple dict for now,
    # but in a real app, you would use firestore_service correctly
    if firestore_service.db:
        from google.cloud import firestore
        payload["created_at"] = firestore.SERVER_TIMESTAMP
        await firestore_service.set_document("artifacts", artifact_id, payload)
        print(f"Artifact {artifact_id} saved successfully.")
    else:
        # Mock timestamp for local dev without firestore
        import datetime
        payload["created_at"] = datetime.datetime.now().isoformat()
        print(f"Firestore disabled. Would have saved artifact: {json.dumps(payload)}")

async def update_user_profile(session_id: str, user_id: str, prototype_id: str, data: Dict[str, Any]):
    """
    A demo save handler that updates a user's profile based on structured chat output.
    """
    from app.services.firestore_service import firestore_service

    # Create a copy so we don't mutate the original dictionary which is
    # returned to the frontend and serialized by FastAPI.
    payload = data.copy()

    if firestore_service.db:
        from google.cloud import firestore
        payload["updated_at"] = firestore.SERVER_TIMESTAMP
        await firestore_service.set_document("users", user_id, payload)
        print(f"User profile for {user_id} updated.")
    else:
        import datetime
        payload["updated_at"] = datetime.datetime.now().isoformat()
        print(f"Firestore disabled. Would have updated user {user_id} with: {json.dumps(payload)}")

# Register them
registry.register("defaultArtifactSave", default_artifact_save)
registry.register("updateUserProfile", update_user_profile)
