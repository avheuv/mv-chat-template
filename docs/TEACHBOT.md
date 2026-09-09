# TEACHBOT experiment guide

TEACHBOT (“Learning by Teaching an AI Learner”) is a separate prototype in the existing launcher. The learner's beliefs are application state, not model reasoning and not a claim that the model has forgotten its pretrained knowledge.

## Run it

1. Configure the existing backend environment with `OPENAI_API_KEY` and Google Application Default Credentials (or `GOOGLE_APPLICATION_CREDENTIALS`).
2. From `backend`, install `requirements.txt` and run `uvicorn app.main:app --reload`.
3. From `frontend`, run `npm install && npm run dev`, open the launcher, and select **TEACHBOT**.
4. Select a topic populated through the existing Firestore `lesson_topics` dynamic-options collection and choose a learner profile.

On first prototype access, the existing override mechanism initializes `prompts/teachbot` with `systemPrompt` and `model` from `backend/prototypes/teachbot.yaml`. Edit that Firestore document to override either value without redeploying. The actual resolved model and settings are frozen into each run's export. Models must be supported by the existing OpenAI chat-completions integration and JSON output mode.

## Add a lesson configuration

Add an object keyed by the **existing `lesson_topics` document ID** to `backend/teachbot_lessons.json`. Profiles contain only starting conceptual beliefs (`id`, `statement`, conviction-style `confidence`, and `sources`). Keep personality separate. Evaluation criteria and labeled misconceptions belong under `evaluation`; the service never inserts that section into learner prompts or conversation history. A topic present in Firestore but absent from this file starts explicitly blank, with `lesson_configured: false` in the exported run.

## Manual demonstration

Use a blank-slate profile, saving a snapshot before each scenario when useful.

1. Ask an untaught content question, then ask “use everything you know.” Confirm it asks for teaching rather than answering expertly; inspect any heuristic leakage flag.
2. Clearly explain one narrow fact. Confirm one relevant belief highlights and unrelated beliefs remain unchanged.
3. Teach an incorrect claim. Confirm it remains in the belief panel on later turns and appears in evaluator review when configured.
4. Say only “That's wrong.” Confirm this may reduce conviction or add uncertainty but does not create a replacement explanation.
5. Inspect the observer dashboard. Its uncertain judgments never appear in chat or belief sources.
6. Save a snapshot, teach another fact, then restore. Confirm both the belief and later chat messages disappear. Continue teaching and verify the restored branch has no later context.
7. Start a second session/profile and confirm its state remains independent. Export JSON to review conversation, audit events, leakage flags, starting state, lesson/config prompt version, model, and settings.

## Design and limitations

- Every call includes the complete authoritative belief state. The model proposes a reply and minimal mutations; backend validation accepts only cited current-user/existing-belief evidence and provides request-level idempotency.
- Firestore is authoritative when configured; an in-process store supports local development. Concurrent requests across multiple backend instances are not transactionally serialized yet. A production study should use Firestore transactions plus a request document with a uniqueness precondition.
- The leakage detector depends on model-reported claims and evidence. It exempts declared paraphrases/simple deductions and is a lightweight review signal—not proof that leakage is absent.
- The evaluator is deliberately separate and conservative, using uncertain lexical checks for this prototype. It is not a validated learning assessment.
- Valid JSON is enforced, but a model can still produce a reply inconsistent with a rejected mutation. Such unsupported claims are flagged for review rather than silently changing state. Model behavior therefore needs empirical verification with the configured credentials.
