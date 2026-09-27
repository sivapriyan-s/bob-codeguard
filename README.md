# 🛡️ Bob CodeGuard

**AI-powered engineering intelligence** built on IBM Bob 2.0.

CodeGuard doesn't just review code — it follows the *ripple effect* of every change: from bug to fix, PR to hidden dependencies, and code to documentation.

---

## Architecture

```
GitHub Repository
       │
       ├── Issue
       └── Pull Request
              │
              ▼
       Bob CodeGuard
       Main Orchestrator
              │
      ┌───────┼────────┐
      ▼       ▼        ▼
   Bug      Review   Detective
   Agent    Agents    Agent
   (S1)     (S2 ×4)  (S3)
      │       │        │
      └───────┼────────┘
              ▼
       Documentation Agent (S4)
              │
              ▼
       Unified CodeGuard Report
```

---

## Stages

| Stage | Mode | Description |
|-------|------|-------------|
| **1 — Bug Fix** | `bug_fix` / `full_issue` | Analyze a GitHub issue, trace root cause, propose fix + tests |
| **2 — PR Review** | `pr_review` / `full_pr` | Parallel Security · Code Quality · Testing · Regression agents |
| **3 — PR Detective** | `pr_detective` / `full_pr` | Ripple-effect impact tracing beyond the diff |
| **4 — Doc Sync** | `doc_sync` / `full_pr` / `full_issue` | Detect documentation drift vs. actual source |

---

## Quick Start

### 1. Prerequisites

- Python 3.11+
- A GitHub Personal Access Token (repo read access)
- An OpenAI API key (GPT-4o recommended)

### 2. Install

```bash
# Clone / enter directory
cd codeguard

# Create virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

# Install dependencies
pip install -r requirements.txt
```

### 3. Configure

```bash
# Copy the example env file
copy .env.example .env    # Windows
# cp .env.example .env    # macOS/Linux

# Edit .env and fill in your values:
#   GITHUB_TOKEN=ghp_...
#   OPENAI_API_KEY=sk-...
```

### 4. Run

```bash
python main.py
```

Open **http://localhost:8000** in your browser.

---

## Using the UI

1. Enter a GitHub repository in `owner/repo` format (e.g. `microsoft/vscode`)
2. Select the analysis mode
3. Enter a PR or issue number
4. Click **⚡ Analyze**

The workflow panel shows real-time progress. When complete, view:

- **Findings** — grouped by category and severity
- **Impact Map** — PR Detective ripple graph
- **Documentation** — detected doc drift
- **Full Report** — copyable engineering report

---

## API

### POST `/api/analyze`

Start an analysis job. Returns `job_id` immediately.

```json
{
  "repository": "owner/repo",
  "mode": "full_pr",
  "ref": "142"
}
```

**Modes:** `bug_fix` · `pr_review` · `pr_detective` · `doc_sync` · `full_pr` · `full_issue`

### GET `/api/jobs/{job_id}`

Poll job status and retrieve results.

### GET `/api/jobs/{job_id}/report`

Get the full CodeGuard report for a completed job.

### GET `/api/jobs`

List all recent jobs.

### GET `/api/health`

Health check.

---

## IBM Bob 2.0 Capabilities Demonstrated

| Capability | Where |
|-----------|-------|
| Agent mode | All stages — `BaseAgent` subclasses |
| Specialized subagents | `SecurityAgent`, `CodeQualityAgent`, `TestAnalysisAgent`, `RegressionAgent`, `PRDetectiveAgent`, `DocSyncAgent` |
| Parallel task execution | `asyncio.gather()` in PR Review stage |
| Repository understanding | `RepoAnalysisAgent` + `GitHubClient.get_repo_tree()` |
| Document understanding | `DocSyncAgent` reads and compares docs vs. source |
| Multi-step reasoning | Orchestrator chains repo analysis → investigation → detection → report |
| Code modification proposals | `BugInvestigationAgent` returns structured `code_changes` |
| Test generation | `BugInvestigationAgent` returns `test_suggestions` |
| Cross-file impact analysis | `PRDetectiveAgent` traces dependencies across entire repo |
| Evidence-based findings | All `Finding` objects include `Evidence` with `file`, `symbol`, `snippet`, `confidence` |

---

## Project Structure

```
codeguard/
  core/
    config.py          # Settings from .env
    models.py          # Shared Pydantic models
    github_client.py   # Async GitHub REST client
    llm.py             # OpenAI wrapper
    evidence_store.py  # Per-job finding accumulator
  agents/
    base.py            # BaseAgent ABC
    repo_analysis.py   # Repository structure agent
    bug_investigation.py  # Root cause + fix agent
    pr_review.py       # Security/Quality/Testing/Regression agents
    pr_detective.py    # Impact tracing agent
    doc_sync.py        # Documentation drift agent
  stages/
    bug_fix.py         # Stage 1 pipeline
    pr_review.py       # Stage 2 pipeline
    pr_detective.py    # Stage 3 pipeline
    doc_sync.py        # Stage 4 pipeline
  reports/
    generator.py       # Unified report generator
  api/
    routes.py          # FastAPI endpoints
  orchestrator.py      # Main job coordinator
frontend/
  public/
    index.html
    static/
      app.css
      app.js
main.py                # Application entry point
requirements.txt
.env.example
```

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GITHUB_TOKEN` | ✅ | — | GitHub Personal Access Token |
| `OPENAI_API_KEY` | ✅ | — | OpenAI API key |
| `OPENAI_MODEL` | | `gpt-4o` | OpenAI model |
| `HOST` | | `0.0.0.0` | Server host |
| `PORT` | | `8000` | Server port |
| `LOG_LEVEL` | | `INFO` | Logging level |

---

## Notes

- Analysis jobs run as background tasks. Results persist in memory for the session.
- GitHub API rate limits: 5000 requests/hour for authenticated users.
- Large repositories with many files will analyze the most relevant subset.
- Code changes proposed by the Bug Fix stage are **proposals** — always review before applying.
