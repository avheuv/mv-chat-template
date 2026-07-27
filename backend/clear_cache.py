import asyncio
from app.services.firestore_service import firestore_service

async def run():
    if firestore_service.db:
        await firestore_service.db.collection("prompts").document("meryl").delete()
        print("Deleted meryl prompts from firestore so they will regenerate from YAML")

if __name__ == "__main__":
    asyncio.run(run())
