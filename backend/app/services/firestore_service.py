import os
from google.cloud import firestore
from app.core.config import settings
from typing import Optional, Dict, Any, List

class FirestoreService:
    def __init__(self):
        try:
            # If standard GOOGLE_APPLICATION_CREDENTIALS is not set but explicitly provided in settings:
            if settings.google_application_credentials and not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = settings.google_application_credentials

            self.db = firestore.AsyncClient()
        except Exception as e:
            print(f"Failed to initialize Firestore: {e}")
            self.db = None

    async def get_document(self, collection: str, doc_id: str) -> Optional[Dict[str, Any]]:
        if not self.db: return None
        doc_ref = self.db.collection(collection).document(doc_id)
        doc = await doc_ref.get()
        if doc.exists:
            data = doc.to_dict()
            data["id"] = doc.id
            return data
        return None

    async def get_prototype_overrides(self, prototype_id: str, default_prompt: str, default_model: str) -> Dict[str, str]:
        overrides = {
            "systemPrompt": default_prompt,
            "model": default_model
        }

        if not self.db: return overrides
        doc_ref = self.db.collection("prompts").document(prototype_id)
        doc = await doc_ref.get()

        if doc.exists:
            data = doc.to_dict()
            if data:
                if data.get("systemPrompt"):
                    overrides["systemPrompt"] = data.get("systemPrompt")
                if data.get("model"):
                    overrides["model"] = data.get("model")
            return overrides

        # If it doesn't exist, create it automatically with the defaults to guide the user
        await self.set_document("prompts", prototype_id, {
            "systemPrompt": default_prompt,
            "model": default_model,
            "_note": "Edit systemPrompt or model here to override the YAML config without redeploying."
        })
        return overrides

    async def set_document(self, collection: str, doc_id: str, data: Dict[str, Any]):
        if not self.db: return
        doc_ref = self.db.collection(collection).document(doc_id)
        await doc_ref.set(data, merge=True)

    async def get_collection(self, collection: str) -> List[Dict[str, Any]]:
        if not self.db: return []
        docs = self.db.collection(collection).stream()
        results = []
        async for doc in docs:
            data = doc.to_dict()
            data["id"] = doc.id
            results.append(data)
        return results

firestore_service = FirestoreService()