# AI Chat Prototype Starter

A thin, production-style template for rapidly developing education-focused AI chat prototypes. Built with React + Vite + TypeScript on the frontend, and FastAPI + Python on the backend. Designed to be easily forked and configured for new proof-of-concept projects without overengineering.

## Architecture & Philosophy

The goal of this starter is to avoid building a giant "no-code platform." Instead, it relies on a **configurable core with explicit plug-in points**.

There are three layers of variability handled differently:
1. **Model behavior and prompting:** Handled via YAML configuration files (`prototypes/`).
2. **Data In (Context):** Handled via named **Context Builders** (tiny explicit Python functions that fetch data and inject it into the prompt).
3. **Data Out (Saving):** Handled via YAML configuration for expected JSON structure, and named **Save Handlers** (tiny Python functions that save data back to Firestore).

### Stack
- **Frontend**: React + Vite + TypeScript (Tailwind CSS available, but relies mostly on raw CSS inspired by standard LLM chats).
- **Backend**: Python FastAPI
- **Database**: Firestore
- **LLM**: OpenAI (utilizing Structured Outputs)

---

## Local Development Setup

### Prerequisites
- Python 3.10+
- Node.js 18+
- An OpenAI API Key
- (Optional but recommended) Google Cloud Service Account JSON for Firestore. If not provided, the app will run, but `firestore_service` will skip database writes.

### 1. Backend Setup
```bash
cd backend
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Create a `.env` file in the `backend/` directory:
```env
OPENAI_API_KEY=your-openai-api-key
# Optional: Path to your Firebase service account key
# GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
```

Run the backend:
```bash
python app/main.py
```
*The backend will be available at `http://localhost:8000`. API docs at `http://localhost:8000/docs`.*

### 2. Frontend Setup
Open a new terminal.
```bash
cd frontend
npm install
npm run dev
```
*The frontend will be available at `http://localhost:5173`.*

---

## Developer Workflow: How to Build a New Prototype

The template is designed so that adding a new prototype rarely requires touching the core `chat_service.py` logic.

### 1. Add a Configuration File
Create a new `.yaml` file in the `prototypes/` directory (e.g., `prototypes/math_tutor.yaml`).

```yaml
id: math_tutor
name: Math Tutor
description: A tutor that helps with algebra.
systemPrompt: |
  You are a math tutor. Help the student solve problems step by step.
model: gpt-4o
temperature: 0.5
maxTokens: 1000
# Tell the system to run these builders before starting the chat
contextSources:
  - fetchStudentMathLevel
# (Optional) Request a specific JSON output shape
outputSpec:
  type: object
  properties:
    concept_mastered:
      type: boolean
  required: [concept_mastered]
# Tell the system to run this handler when data is returned
saveHandler: updateMathProgress
ui:
  title: Math Tutor
  subtitle: Algebra Help
  placeholder: What problem are you working on?
```

### 2. (Optional) Add a Context Builder
If your config specifies `contextSources`, implement them in `backend/app/context_builders/registry.py`.

```python
async def fetch_student_math_level(user_id: str, session_id: str) -> str:
    # Fetch from DB here...
    return "Math Level: Algebra 1"

registry.register("fetchStudentMathLevel", fetch_student_math_level)
```

### 3. (Optional) Add a Save Handler
If your config specifies a `saveHandler`, implement it in `backend/app/save_handlers/registry.py`.

```python
async def update_math_progress(session_id: str, user_id: str, prototype_id: str, data: dict):
    # data will perfectly match your outputSpec JSON schema!
    # Save to Firestore here...
    print(f"User {user_id} mastered concept: {data['concept_mastered']}")

registry.register("updateMathProgress", update_math_progress)
```

## Deployment (Docker & Google Cloud)

This project is structured for easy deployment to Google Cloud, utilizing **Firebase Hosting** for the frontend and **Google Cloud Run** for the backend.

### 1. Backend (Cloud Run)
The repository includes a standard `Dockerfile` for the backend.

**Testing the Docker container locally:**
```bash
cd backend
docker build -t ai-prototype-backend .
docker run -p 8080:8080 -e OPENAI_API_KEY="sk-..." -e GOOGLE_APPLICATION_CREDENTIALS="/app/service-account.json" -v /path/to/your/service-account.json:/app/service-account.json ai-prototype-backend
```

**Deploying to Cloud Run:**
Assuming you have the Google Cloud CLI installed and authenticated (`gcloud auth login` and `gcloud config set project YOUR_PROJECT_ID`):

```bash
cd backend
gcloud run deploy ai-prototype-backend \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars="OPENAI_API_KEY=sk-your-key-here"
```

*Note: In production on Cloud Run, you do not need to mount a service account JSON file; Cloud Run automatically provides Application Default Credentials via its attached service account to access Firestore.*

### 2. Frontend (Firebase Hosting)
Once your backend is deployed, you will receive a Cloud Run URL (e.g., `https://ai-prototype-backend-xyz.a.run.app`).

1. Open `frontend/.env.production` (or create it) and set:
   ```env
   VITE_API_BASE_URL=https://ai-prototype-backend-xyz.a.run.app
   ```
2. Build the production assets:
   ```bash
   cd frontend
   npm run build
   ```
3. Deploy to Firebase:
   ```bash
   firebase init hosting  # If not done yet. Select 'dist' as the public directory.
   firebase deploy --only hosting
   ```
