import copy
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.core.prototype_loader import prototype_loader
from app.models.teachbot import Belief, LearnerProposal
from app.services.firestore_service import firestore_service
from app.services.llm_service import llm_service


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TeachBotService:
    """Owns authoritative learner state; the model may only propose mutations."""

    prompt_version = "teachbot-learner-v1"

    def __init__(self, config_path: Optional[str] = None):
        path = config_path or os.path.join(os.path.dirname(__file__), "..", "..", "teachbot_lessons.json")
        with open(path, encoding="utf-8") as stream:
            self.lessons = json.load(stream)
        self._sessions: Dict[str, Dict[str, Any]] = {}

    async def _get(self, session_id: str) -> Optional[Dict[str, Any]]:
        document = await firestore_service.get_document("teachbot_sessions", session_id)
        return document or self._sessions.get(session_id)

    async def _save(self, session: Dict[str, Any]) -> None:
        self._sessions[session["id"]] = copy.deepcopy(session)
        await firestore_service.set_document("teachbot_sessions", session["id"], session)

    async def start(self, lesson_code: str, profile: str) -> Dict[str, Any]:
        prototype = prototype_loader.get_prototype("teachbot")
        overrides = await firestore_service.get_prototype_overrides("teachbot", prototype.systemPrompt, prototype.model)
        lesson = self.lessons.get(lesson_code)
        configured = lesson is not None
        lesson = lesson or {"title": lesson_code, "profiles": {}, "evaluation": {"criteria": [], "misconceptions": {}}}
        if profile not in {"blank_slate", "confident_novice", "uncertain"}:
            raise ValueError("Unknown learner profile")
        beliefs = lesson.get("profiles", {}).get(profile, []) if configured else []
        sid = str(uuid.uuid4())
        session = {
            "id": sid, "lesson_code": lesson_code, "lesson_title": lesson.get("title", lesson_code),
            "profile": profile, "beliefs": beliefs, "unresolved_questions": [], "messages": [],
            "history": [], "snapshots": {}, "processed_requests": {}, "created_at": _now(),
            "run_config": {"model": overrides["model"], "temperature": prototype.temperature,
                "max_tokens": prototype.maxTokens, "prompt_version": self.prompt_version,
                "learner_prompt": overrides["systemPrompt"],
                "lesson_configured": configured, "lesson_config": lesson_code,
                "starting_state": copy.deepcopy(beliefs), "personality": {"tone": "curious and candid"}},
        }
        await self._save(session)
        return self.public(session)

    def public(self, session: Dict[str, Any]) -> Dict[str, Any]:
        result = copy.deepcopy(session)
        result.pop("processed_requests", None)
        result.pop("snapshots", None)
        result["evaluation"] = self.evaluate(session)
        return result

    def _prompt(self, session: Dict[str, Any], user_id: str) -> list[dict[str, str]]:
        state = {"beliefs": session["beliefs"], "unresolved_questions": session["unresolved_questions"]}
        schema = LearnerProposal.model_json_schema()
        system = (session["run_config"]["learner_prompt"] + "\n\nAUTHORITATIVE LEARNER STATE (complete):\n" + json.dumps(state) +
            "\nEvidence must cite the current user message ID or an existing belief ID. "
            "Never use your own prior replies as learning evidence. Reply as JSON matching this schema:\n" + json.dumps(schema))
        context = [{"role": m["role"], "content": m["content"]} for m in session["messages"]]
        return [{"role": "system", "content": system}, *context, {"role": "user", "content": f"[{user_id}] {session['_pending_content']}"}]

    def apply(self, session: Dict[str, Any], proposal: LearnerProposal, user_message_id: str, turn_id: str, teaching: str = "") -> list[Dict[str, Any]]:
        beliefs = {item["id"]: Belief(**item) for item in session["beliefs"]}
        audit = []
        for change in proposal.changes:
            allowed_evidence = {user_message_id, *beliefs.keys()}
            if not change.evidence or any(ref not in allowed_evidence for ref in change.evidence):
                continue
            before = beliefs.get(change.belief_id)
            vague_disagreement = teaching.strip().lower().rstrip(".!?") in {"that's wrong", "that is wrong", "no", "wrong", "not right"}
            if vague_disagreement and (change.operation != "update" or not before or (change.statement and change.statement != before.statement)):
                continue
            if change.operation == "add":
                if before or not change.statement or user_message_id not in change.evidence:
                    continue
                after = Belief(id=change.belief_id, statement=change.statement, confidence=change.confidence or .4,
                               sources=change.evidence, deduction=user_message_id not in change.evidence)
                beliefs[change.belief_id] = after
            elif change.operation == "update":
                if not before:
                    continue
                after = before.model_copy(update={"statement": change.statement or before.statement,
                    "confidence": before.confidence if change.confidence is None else change.confidence,
                    "sources": list(dict.fromkeys(before.sources + change.evidence))})
                beliefs[change.belief_id] = after
            else:
                if not before or user_message_id not in change.evidence:
                    continue
                after = None
                del beliefs[change.belief_id]
            audit.append({"belief_id": change.belief_id, "operation": change.operation,
                "before": before.model_dump() if before else None, "after": after.model_dump() if after else None,
                "evidence": change.evidence, "explanation": change.explanation})
        session["beliefs"] = [belief.model_dump() for belief in beliefs.values()]
        session["unresolved_questions"] = list(dict.fromkeys(proposal.unresolved_questions))[:12]
        session["history"].append({"turn_id": turn_id, "at": _now(), "changes": audit, "teaching_message_id": user_message_id})
        return audit

    async def turn(self, session_id: str, content: str, request_id: str) -> Dict[str, Any]:
        session = await self._get(session_id)
        if not session:
            raise ValueError("TeachBot session not found")
        if request_id in session["processed_requests"]:
            response = copy.deepcopy(session["processed_requests"][request_id])
            response["session"] = self.public(session)
            response["duplicate"] = True
            return response
        user_id, turn_id = f"user:{uuid.uuid4()}", str(uuid.uuid4())
        session["_pending_content"] = content
        proposal_data = await llm_service.generate_teachbot_proposal(
            self._prompt(session, user_id), session["run_config"]["model"],
            session["run_config"]["temperature"], session["run_config"]["max_tokens"])
        proposal = LearnerProposal.model_validate(proposal_data)
        session.pop("_pending_content", None)
        session["messages"].append({"id": user_id, "role": "user", "content": content, "turn_id": turn_id})
        changes = self.apply(session, proposal, user_id, turn_id, content)
        leakage = self.detect_leakage(proposal, session, content)
        assistant_id = f"assistant:{uuid.uuid4()}"
        session["messages"].append({"id": assistant_id, "role": "assistant", "content": proposal.reply,
                                    "turn_id": turn_id, "leakage_flags": leakage})
        response = {"session": self.public(session), "reply": proposal.reply, "accepted_changes": changes,
                    "leakage_flags": leakage, "duplicate": False}
        session["processed_requests"][request_id] = copy.deepcopy(response)
        await self._save(session)
        return response

    def detect_leakage(self, proposal: LearnerProposal, session: Dict[str, Any], teaching: str) -> list[Dict[str, str]]:
        support = (teaching + " " + " ".join(b["statement"] for b in session["beliefs"])).lower()
        flags = []
        for claim in proposal.reply_claims:
            text, kind = str(claim.get("text", "")), claim.get("kind", "claim")
            evidence = claim.get("evidence", [])
            if kind not in {"paraphrase", "simple_deduction"} and text and not evidence and text.lower() not in support:
                flags.append({"claim": text, "reason": "No state or teaching evidence was cited", "status": "heuristic_review"})
        return flags

    def evaluate(self, session: Dict[str, Any]) -> Dict[str, Any]:
        # Kept out of model prompts/history; lexical matching is intentionally uncertain.
        config = self.lessons.get(session["lesson_code"], {}).get("evaluation", {})
        text = " ".join(b["statement"] for b in session["beliefs"]).lower()
        starting = " ".join(b["statement"] for b in session["run_config"]["starting_state"]).lower()
        misconceptions = config.get("misconceptions", {})
        matches = {key: label for key, label in misconceptions.items() if all(w in text for w in label.lower().split() if len(w) > 4)}
        started = {key for key, label in misconceptions.items() if all(w in starting for w in label.lower().split() if len(w) > 4)}
        return {"label": "Evaluator judgment (not learner belief)", "certainty": "uncertain",
            "corrected": [misconceptions[k] for k in started - matches.keys()], "remaining": list(matches.values()),
            "newly_introduced": [label for k, label in matches.items() if k not in started],
            "stalled": list(session["unresolved_questions"]), "criteria_reviewed": len(config.get("criteria", []))}

    async def snapshot(self, session_id: str, name: str) -> Dict[str, Any]:
        session = await self._get(session_id)
        if not session: raise ValueError("TeachBot session not found")
        snapshot_id = str(uuid.uuid4())
        session["snapshots"][snapshot_id] = {"id": snapshot_id, "name": name, "created_at": _now(),
            "beliefs": copy.deepcopy(session["beliefs"]), "unresolved_questions": copy.deepcopy(session["unresolved_questions"]),
            "messages": copy.deepcopy(session["messages"]), "history": copy.deepcopy(session["history"])}
        await self._save(session)
        return session["snapshots"][snapshot_id]

    async def restore(self, session_id: str, snapshot_id: str) -> Dict[str, Any]:
        session = await self._get(session_id)
        if not session or snapshot_id not in session["snapshots"]: raise ValueError("Snapshot not found")
        snap = session["snapshots"][snapshot_id]
        for key in ("beliefs", "unresolved_questions", "messages", "history"):
            session[key] = copy.deepcopy(snap[key])
        session["processed_requests"] = {}
        await self._save(session)
        return self.public(session)


teachbot_service = TeachBotService()
