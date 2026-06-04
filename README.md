# Flux — AI-Powered Developer Lifecycle Automation

> **From ticket to code, automatically.** Flux reimagines software production by orchestrating AI agents that transform Jira tickets into working code — with full context from Slack conversations, commit history, AI discussions, and team knowledge.

[![Theme](https://img.shields.io/badge/Theme-AI--Powered%20Production%20Function-blue)]()
[![Stack](https://img.shields.io/badge/Stack-Groq%20%7C%20Azure%20AI%20Search%20%7C%20Azure%20Blob%20%7C%20GitHub%20Copilot-0078D4)]()
[![License](https://img.shields.io/badge/License-MIT-green)]()

---

## Problem Statement

Modern software teams lose **40%+ of their time** on workflow overhead — context-switching between Jira, Slack, Git, and IDEs. Developers manually:
- Read ticket descriptions and comments
- Search Slack for relevant discussions
- Create branches, set up workspaces
- Gather context before writing any code
- Wait for reviews with no automated quality gates
- **Lose all AI conversation context** — past discussions with AI tools are never saved or reused

**The result:** Slow delivery cycles, lost context, and AI tools that can't help because they don't understand the full picture.

## Solution Overview

**Flux** is an AI-native production system with **two core capabilities**:

### 1. Intelligent Ask Agent (Chatbot + Knowledge Engine)

A conversational AI agent that can **intelligently fetch answers from anywhere** in your project:
- Ask about any Jira ticket, commit, or Slack discussion
- Find out **which developer worked on which task** — so you can directly connect with them
- Get AI-analyzed summaries of past work, bugs, and decisions
- **AI discussions are stored as context** — when you commit or merge, your AI conversations become part of the project knowledge base for future queries

### 2. Full Lifecycle Orchestrator

When a Jira ticket is created, Flux automatically:
1. **Creates a Slack channel** → Invites assignees, posts ticket context
2. **Creates a Git branch** → Named after the ticket, workspace ready
3. **Gathers full context** → Jira + Slack + commits + **AI session history**
4. **Builds an AI prompt** → Rich prompt including past AI discussions
5. **Deploys a multi-agent system** → Context Agent + Code Agent + Reviewer Agent
6. **Generates code** → Via GitHub Copilot bridge or Groq LLM
7. **Reviews automatically** → AI reviewer checks against ticket requirements
8. **Stores AI context** → All agent discussions saved for future reference

### What Makes Flux Different

| Traditional Workflow | Flux Workflow |
|---------------------|---------------|
| Developer reads ticket manually | AI reads & synthesizes ticket + history |
| AI conversations are lost after closing | **AI discussions stored as project context** |
| "Who worked on this?" → search git blame | **Ask Agent tells you instantly** |
| Copy-paste context to Copilot | Full context auto-fed to agents |
| Manual branch creation | Auto-branch on ticket creation |
| Slack discussions scattered | Auto-channel with captured context |
| No memory across sessions | RAG-powered commit + AI session intelligence |

---

## Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│                        EVENT SOURCES (Watched)                          │
├────────────┬──────────────┬──────────────┬────────────────────────────┤
│  Jira      │  Slack       │  Git         │  AI Discussions            │
│  - Tickets │  - Messages  │  - Branches  │  - Agent conversations     │
│  - Comments│  - Threads   │  - Commits   │  - Past Q&A sessions       │
└─────┬──────┴──────┬───────┴──────┬───────┴──────────┬─────────────────┘
      │             │              │                   │
      ▼             ▼              ▼                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│                    ORCHESTRATOR + ASK AGENT                              │
│  - One session per ticket                                               │
│  - Intelligent Q&A across all sources                                   │
│  - Tracks developer assignments (who worked on what)                    │
│  - AI discussions stored as searchable context                          │
│  - Role-based access control                                            │
└─────────────────────────────────┬──────────────────────────────────────┘
                                  │
                                  ▼
┌────────────────────────────────────────────────────────────────────────┐
│                    CONTEXT BUILDER                                       │
│  Combines: Jira + Slack + Commits + AI Sessions → Rich Prompt          │
│  Uses Azure AI Search (RAG) for relevant past context                  │
│  Includes past AI discussions for continuity                           │
└─────────────────────────────────┬──────────────────────────────────────┘
                                  │
                                  ▼
┌────────────────────────────────────────────────────────────────────────┐
│                    MULTI-AGENT SYSTEM                                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                 │
│  │Context Agent │→ │  Code Agent  │→ │Review Agent  │                 │
│  │(Synthesizes) │  │(Generates)   │  │(Validates)   │                 │
│  └──────────────┘  └──────────────┘  └──────────────┘                 │
│  Shared Memory (AgentMemory) for cross-agent learning                  │
└─────────────────────────────────┬──────────────────────────────────────┘
                                  │
                                  ▼
┌────────────────────────────────────────────────────────────────────────┐
│               OUTPUT: Code → Commit → Push → PR                         │
│  Via GitHub Copilot Bridge / Groq LLM                                  │
└────────────────────────────────────────────────────────────────────────┘
```

### Component Diagram

```
┌─────────────────────────────────────────────────┐
│              FLUX PLATFORM                        │
├─────────────────────────────────────────────────┤
│                                                  │
│  ┌─────────────┐    ┌────────────────────────┐  │
│  │  Dashboard  │    │   VS Code Extension    │  │
│  │  (React)    │    │   - Ask AI (Chatbot)   │  │
│  │  Port 5174  │    │   - Pipeline View      │  │
│  └──────┬──────┘    │   - Commit Tree        │  │
│         │           └────────────┬───────────┘  │
│         ▼                        ▼              │
│  ┌─────────────────────────────────────────┐    │
│  │         FastAPI Server (Port 5051)       │    │
│  │  /sessions, /tickets, /slack, /git      │    │
│  │  /ask, /context, /access-control        │    │
│  └──────────────────┬──────────────────────┘    │
│                     │                           │
│  ┌──────────┬───────┼───────┬──────────────┐   │
│  ▼          ▼       ▼       ▼              ▼   │
│ Jira API  Slack   Azure    Azure AI     GitHub │
│           Bot     Blob     Search       Copilot│
│                   Storage  (RAG)               │
└─────────────────────────────────────────────────┘
```

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| **LLM Engine** | **Groq** (LLaMA 3 / Mixtral — fast inference) |
| **Code Generation** | **GitHub Copilot** (via Copilot Bridge) |
| **Semantic Search** | **Azure AI Search** (RAG over commits + AI sessions) |
| **Data Storage** | **Azure Blob Storage** (commits, AI sessions, context) |
| **Backend** | FastAPI (Python 3.11) |
| **Dashboard** | React 18 + Vite + Tailwind CSS |
| **VS Code Extension** | TypeScript (Ask AI panel, Pipeline view, Commit tree) |
| **Collaboration** | Slack Bot (channel automation, message capture) |
| **Project Tracking** | Jira REST API |

### AI Tools Used in the Product

- **Groq** — Primary LLM for commit analysis, Q&A, agent reasoning (fast + free tier)
- **GitHub Copilot** — Code generation engine via Copilot Bridge
- **Azure AI Search** — RAG-powered semantic search over commit history, AI sessions, and project knowledge
- **Azure Blob Storage** — Persistent storage for commit intelligence, AI session logs, and agent memory

### AI Tools Used During Development

- **GitHub Copilot** — Code completion and boilerplate generation
- **GitHub Copilot Chat** — Architecture discussions, debugging, code review

---

## Key Features

### Ask Agent (Intelligent Chatbot)
- 🧠 **Ask anything** — "What bugs were fixed this sprint?", "Who worked on authentication?"
- 🔍 **Cross-source search** — Searches Jira tickets, commits, Slack messages, AND past AI discussions simultaneously
- 👤 **Developer lookup** — "Who implemented the OAuth flow?" → Returns developer name + relevant commits
- 💬 **AI memory** — Past AI conversations are stored and used as context for future queries
- 📝 **Commit context** — Every commit's AI analysis becomes searchable knowledge

### Lifecycle Orchestrator
- 🎫 **Jira Integration** — Auto-detects new tickets, fetches details/comments, triggers workflows
- 💬 **Slack Automation** — Creates discussion channels, captures technical messages, invites assignees
- 🌿 **Git Automation** — Creates branches, tracks commits per ticket, links everything
- 🤖 **Multi-Agent System** — Context + Code + Review agents collaborate with shared memory
- 🔗 **Copilot Bridge** — Feeds rich context to GitHub Copilot for informed code generation

### AI Context Continuity
- 🔄 **AI discussions saved on commit** — When you commit/merge, your AI conversations are stored in Azure Blob
- 📖 **Context carries forward** — Future agents see past AI discussions as part of project knowledge
- 🧩 **RAG over AI sessions** — Ask questions and get answers informed by previous AI reasoning

### Developer Experience
- 📊 **Web Dashboard** — Real-time view of sessions, channels, branches, agent status
- 🖥️ **VS Code Extension** — Pipeline view, commit tree, Ask AI chatbot panel in IDE
- 🛡️ **Access Control** — Role-based (admin/lead/developer/intern) ticket filtering
- 📈 **Agent Memory** — Agents learn from past decisions and developer feedback

---

## Quick Start

### Option 1: One-Click Start (Windows)

```bash
git clone https://github.com/Ai-deen/Flux.git
cd Flux
# Configure your .env (copy from .env.example)
START.bat
```

### Option 2: Manual Setup

#### Prerequisites
- Python 3.10+
- Node.js 18+
- Git
- Jira Cloud account with API token
- Slack workspace with bot token
- Azure account (for Blob Storage + AI Search)
- Groq API key (free at https://console.groq.com)

#### Install

```bash
git clone https://github.com/Ai-deen/Flux.git
cd Flux
pip install -e .
```

#### Configure Environment

Create a `.env` file (copy from `.env.example`):

```bash
# Jira
JIRA_DOMAIN=your-team.atlassian.net
JIRA_EMAIL=your@email.com
JIRA_API_TOKEN=your-jira-api-token

# Slack
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_SIGNING_SECRET=your-signing-secret

# Azure Storage & Search
AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=https;AccountName=...
AZURE_SEARCH_ENDPOINT=https://your-search.search.windows.net
AZURE_SEARCH_KEY=your-search-key

# LLM — Groq (primary)
GROQ_API_KEY=gsk_your-groq-key

# Git
FLUX_REPO_PATH=/path/to/your/target/project
```

#### Run

```bash
# Start the API server
python -m uvicorn engmemory.api.server:app --host 0.0.0.0 --port 5051 --reload

# Start the dashboard (separate terminal)
cd dashboard
npm install && npm run dev
```

#### Use the Ask Agent

```bash
# Ask questions about your project
flux ask "What auth bugs were fixed this sprint?"
flux ask "Who worked on the payment module?"
flux ask "What was discussed about the API rate limiting?"

# Check status
flux status
```

---

## How It Works — AI Context Flow

```
Developer has AI conversation (Copilot Chat, Ask Agent)
                    │
                    ▼
Developer commits code: "KAN-10: Fix auth timeout"
                    │
                    ▼
┌──────────────────────────────────────────────────┐
│  Post-Commit Hook captures:                       │
│  • Commit SHA, message, diff                     │
│  • AI session summary (what was discussed)       │
│  • Jira ticket context (if ticket ID found)      │
│  • Files changed                                 │
└──────────────────┬───────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────┐
│  Stored in Azure:                                 │
│  • Blob Storage → commit + AI session data       │
│  • AI Search Index → searchable by RAG           │
└──────────────────┬───────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────┐
│  Future queries use ALL past context:             │
│  "What was the reasoning behind the auth fix?"   │
│  → Finds commit + AI discussion + Slack msgs     │
│  → Returns comprehensive answer                  │
└──────────────────────────────────────────────────┘
```

---

## Project Structure

```
Flux/
├── engmemory/                # Core Python engine
│   ├── agent/                # Multi-agent system (Context, Code, Review)
│   ├── api/                  # FastAPI server (orchestrator + ask endpoints)
│   ├── orchestrator/         # Session management, polling, context building
│   ├── slack/                # Slack bot, channel manager, message capture
│   ├── storage/              # Azure Blob + local storage
│   ├── search/               # Azure AI Search + RAG (queries commits + AI sessions)
│   ├── core/                 # Git hook, commit capture
│   ├── analysis/             # LLM-powered commit analysis (Groq)
│   └── utils/                # Config, Jira client, helpers
├── dashboard/                # React web dashboard
├── deploy/                   # Demo server (pre-built, deployable without credentials)
├── vscode-extension/         # VS Code extension (Ask AI, Pipeline, Commit Tree)
├── docs/                     # Documentation
├── scripts/                  # Setup scripts (Azure provisioning)
├── .env.example              # Environment template (no secrets)
├── pyproject.toml            # Python package config (CLI: `flux`)
└── START.bat                 # One-click start (Windows)
```

---

## Demo

### Ask Agent in Action

```bash
$ flux ask "Who fixed the JWT expiry bug?"

🔍 Searching: commits, Jira tickets, Slack messages, AI sessions...

Found in KAN-7 (resolved):
  Developer: Sreeja
  Commit: c5d2a7b3 — "Fix JWT refresh token rotation logic"
  Context: JWT middleware was checking `exp` without clock skew buffer.
           Added 30s buffer + Redis lock for atomic refresh rotation.
  AI Session: Developer discussed with AI agent about race conditions
              in concurrent token refresh — solved with distributed lock.

→ Connect with Sreeja for details on the auth middleware patterns.
```

### Web Dashboard
- Real-time session view (active tickets, pipeline stages, agent status)
- Slack channels auto-created per ticket with captured messages
- Git activity tracker (branches, commits, diffs)
- Role-based access control panel

### VS Code Extension
- **Ask AI panel** — Natural language queries over entire project history
- **Pipeline view** — Shows automation status per ticket
- **Commit tree** — Browse AI-analyzed commits with full context

---

## Team

| Name | Role | Contributions |
|------|------|--------------|
| **Sreeja** | Lead Developer | Architecture, orchestrator, multi-agent system, API server, VS Code extension, Ask Agent, RAG pipeline, dashboard |
| **Sahithi** | Developer | Commit hook implementation, git extension for capturing commits |
| **Chandramalika** | Developer | Azure setup and configuration (Blob Storage, AI Search) |

---

## AI Tools Disclosure

| Tool | Usage |
|------|-------|
| **GitHub Copilot** | Code completion, boilerplate generation during development |
| **GitHub Copilot Chat** | Architecture discussions, debugging assistance during development |
| **Groq (LLaMA 3)** | Core AI engine within the product — commit analysis, Q&A, agent reasoning |
| **Azure AI Search** | RAG implementation for semantic search over commits + AI sessions |

> All AI-generated code was reviewed, tested, and refined by team members. The system architecture, multi-agent design, RAG pipeline, and workflow orchestration represent original engineering work.

---

## License

MIT License

---

## Hackathon Info

- **Hackathon:** Microsoft Build AI Codeathon 2026
- **Theme:** AI-Powered Production Function: Reinventing Work
- **Track:** Reimagining how software is built with AI-native workflows
- **Period:** May 3 – June 30, 2026
