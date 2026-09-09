import asyncio

from app.models.teachbot import LearnerProposal
from app.services.teachbot_service import TeachBotService


def base_session(beliefs=None):
    return {"beliefs": beliefs or [], "unresolved_questions": [], "history": []}


def test_untaught_answer_cannot_become_a_belief_without_user_evidence():
    service = TeachBotService()
    session = base_session()
    proposal = LearnerProposal(reply="I happen to know the expert answer.", changes=[{
        "operation": "add", "belief_id": "expert", "statement": "An untaught expert fact",
        "confidence": .9, "evidence": ["assistant:made-up"], "explanation": "I said it"
    }], reply_claims=[{"text": "An untaught expert fact", "kind": "claim", "evidence": []}])
    assert service.apply(session, proposal, "user:1", "turn:1") == []
    assert session["beliefs"] == []
    assert service.detect_leakage(proposal, session, "What is the answer?")


def test_clear_and_incorrect_teaching_changes_only_the_cited_belief_and_persists():
    service = TeachBotService()
    original = {"id": "other", "statement": "Unrelated belief", "confidence": .5, "sources": ["config"]}
    session = base_session([original])
    proposal = LearnerProposal(reply="I learned that false idea.", changes=[{
        "operation": "add", "belief_id": "taught", "statement": "Mitochondria create energy from nothing",
        "confidence": .7, "evidence": ["user:1"], "explanation": "The teacher explicitly explained this"
    }])
    service.apply(session, proposal, "user:1", "turn:1", "Mitochondria create energy from nothing")
    assert session["beliefs"][0]["statement"] == original["statement"]
    assert session["beliefs"][0]["confidence"] == original["confidence"]
    assert session["beliefs"][1]["statement"] == "Mitochondria create energy from nothing"
    assert session["beliefs"][1]["confidence"] == .7


def test_vague_disagreement_cannot_supply_replacement_knowledge():
    service = TeachBotService()
    session = base_session([{"id": "b1", "statement": "Old idea", "confidence": .8, "sources": ["config"]}])
    proposal = LearnerProposal(reply="Now I know the correction.", changes=[{
        "operation": "update", "belief_id": "b1", "statement": "Magically correct replacement",
        "confidence": .9, "evidence": ["user:1"], "explanation": "Teacher disagreed"
    }])
    assert service.apply(session, proposal, "user:1", "turn:1", "That's wrong") == []
    assert session["beliefs"][0]["statement"] == "Old idea"


def test_duplicate_request_snapshot_restore_and_session_isolation(monkeypatch):
    asyncio.run(_duplicate_snapshot_scenario(monkeypatch))


async def _duplicate_snapshot_scenario(monkeypatch):
    service = TeachBotService()
    monkeypatch.setattr("app.services.teachbot_service.firestore_service.get_document", lambda *args: async_none())
    monkeypatch.setattr("app.services.teachbot_service.firestore_service.set_document", lambda *args: async_none())
    async def proposal(*args, **kwargs):
        return {"reply": "I learned it.", "changes": [{"operation": "add", "belief_id": "new", "statement": "Taught fact", "confidence": .6, "evidence": [], "explanation": "taught"}], "unresolved_questions": [], "reply_claims": []}
    # Add the unpredictable generated user evidence ID at call time.
    async def cited(messages, *args):
        user_id = messages[-1]["content"].split("]", 1)[0][1:]
        data = await proposal()
        data["changes"][0]["evidence"] = [user_id]
        return data
    monkeypatch.setattr("app.services.teachbot_service.llm_service.generate_teachbot_proposal", cited)
    first = await service.start("quadratics", "blank_slate")
    second = await service.start("quadratics", "blank_slate")
    snap = await service.snapshot(first["id"], "before")
    result = await service.turn(first["id"], "Here is a fact", "same-request")
    duplicate = await service.turn(first["id"], "Here is a fact", "same-request")
    assert len(result["session"]["beliefs"]) == 1
    assert duplicate["session"]["beliefs"] == result["session"]["beliefs"]
    restored = await service.restore(first["id"], snap["id"])
    assert restored["beliefs"] == [] and restored["messages"] == []
    assert (await service._get(second["id"]))["beliefs"] == []


async def async_none():
    return None
