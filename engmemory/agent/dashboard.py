"""
dashboard.py — Web Dashboard for EngMemory Agent

Shows:
- Agent activity feed (what tickets were processed)
- Statistics (accepted vs rejected reviews, iterations, etc.)
- Ticket status (new, in-progress, processed)
- Developer feedback history
- Team discussion context
- Live agent status

Run:
    engmemory dashboard
    # Opens at http://localhost:5050
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

try:
    from flask import Flask, render_template_string, jsonify
    HAS_FLASK = True
except ImportError:
    HAS_FLASK = False

log = logging.getLogger(__name__)

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>EngMemory Agent Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        tailwind.config = {
            theme: { extend: { colors: { primary: '#6366f1', dark: '#1e1b4b' } } }
        }
    </script>
    <style>
        body { font-family: 'Inter', system-ui, sans-serif; }
        .animate-pulse-slow { animation: pulse 3s infinite; }
    </style>
</head>
<body class="bg-gray-950 text-gray-100 min-h-screen">
    <!-- Header -->
    <header class="bg-gray-900 border-b border-gray-800 px-6 py-4">
        <div class="max-w-7xl mx-auto flex items-center justify-between">
            <div class="flex items-center gap-3">
                <div class="w-10 h-10 rounded-lg bg-primary flex items-center justify-center text-white font-bold">EM</div>
                <div>
                    <h1 class="text-xl font-bold text-white">EngMemory Agent</h1>
                    <p class="text-sm text-gray-400">AI-Powered Engineering Intelligence</p>
                </div>
            </div>
            <div id="status-badge" class="flex items-center gap-2 px-3 py-1 rounded-full bg-green-900/30 text-green-400 text-sm">
                <span class="w-2 h-2 rounded-full bg-green-400 animate-pulse-slow"></span>
                Active
            </div>
        </div>
    </header>

    <main class="max-w-7xl mx-auto px-6 py-8">
        <!-- Stats Cards -->
        <div class="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
            <div class="bg-gray-900 rounded-xl p-5 border border-gray-800">
                <p class="text-sm text-gray-400">Tickets Processed</p>
                <p id="stat-processed" class="text-3xl font-bold text-white mt-1">-</p>
            </div>
            <div class="bg-gray-900 rounded-xl p-5 border border-gray-800">
                <p class="text-sm text-gray-400">Reviews Approved</p>
                <p id="stat-approved" class="text-3xl font-bold text-green-400 mt-1">-</p>
            </div>
            <div class="bg-gray-900 rounded-xl p-5 border border-gray-800">
                <p class="text-sm text-gray-400">Needed Revision</p>
                <p id="stat-revised" class="text-3xl font-bold text-yellow-400 mt-1">-</p>
            </div>
            <div class="bg-gray-900 rounded-xl p-5 border border-gray-800">
                <p class="text-sm text-gray-400">Developer Feedback</p>
                <p id="stat-feedback" class="text-3xl font-bold text-blue-400 mt-1">-</p>
            </div>
        </div>

        <!-- Two Column Layout -->
        <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <!-- Activity Feed -->
            <div class="lg:col-span-2">
                <div class="bg-gray-900 rounded-xl border border-gray-800">
                    <div class="px-5 py-4 border-b border-gray-800 flex items-center justify-between">
                        <h2 class="text-lg font-semibold">Agent Activity</h2>
                        <button onclick="loadData()" class="text-sm text-primary hover:text-primary/80">Refresh</button>
                    </div>
                    <div id="activity-feed" class="p-5 space-y-4 max-h-[600px] overflow-y-auto">
                        <p class="text-gray-500">Loading...</p>
                    </div>
                </div>
            </div>

            <!-- Right Sidebar -->
            <div class="space-y-6">
                <!-- Agent Memory -->
                <div class="bg-gray-900 rounded-xl border border-gray-800">
                    <div class="px-5 py-4 border-b border-gray-800">
                        <h2 class="text-lg font-semibold">Agent Decisions</h2>
                    </div>
                    <div id="decisions-list" class="p-5 space-y-3 max-h-[300px] overflow-y-auto">
                        <p class="text-gray-500">Loading...</p>
                    </div>
                </div>

                <!-- Developer Feedback -->
                <div class="bg-gray-900 rounded-xl border border-gray-800">
                    <div class="px-5 py-4 border-b border-gray-800">
                        <h2 class="text-lg font-semibold">Developer Feedback</h2>
                        <p class="text-xs text-gray-500">What the agent has learned from you</p>
                    </div>
                    <div id="feedback-list" class="p-5 space-y-3 max-h-[300px] overflow-y-auto">
                        <p class="text-gray-500">Loading...</p>
                    </div>
                </div>

                <!-- Team Discussions -->
                <div class="bg-gray-900 rounded-xl border border-gray-800">
                    <div class="px-5 py-4 border-b border-gray-800">
                        <h2 class="text-lg font-semibold">Team Discussions</h2>
                        <p class="text-xs text-gray-500">From linked channels</p>
                    </div>
                    <div id="discussions-list" class="p-5 space-y-3 max-h-[300px] overflow-y-auto">
                        <p class="text-gray-500">No discussions yet</p>
                    </div>
                </div>
            </div>
        </div>
    </main>

    <script>
        async function loadData() {
            try {
                const resp = await fetch('/api/data');
                const data = await resp.json();
                renderStats(data.stats);
                renderActivity(data.runs);
                renderDecisions(data.decisions);
                renderFeedback(data.feedback);
                renderDiscussions(data.discussions);
            } catch (err) {
                console.error('Failed to load data:', err);
            }
        }

        function renderStats(stats) {
            document.getElementById('stat-processed').textContent = stats.processed || 0;
            document.getElementById('stat-approved').textContent = stats.approved || 0;
            document.getElementById('stat-revised').textContent = stats.revised || 0;
            document.getElementById('stat-feedback').textContent = stats.feedback_count || 0;
        }

        function renderActivity(runs) {
            const feed = document.getElementById('activity-feed');
            if (!runs || runs.length === 0) {
                feed.innerHTML = '<p class="text-gray-500">No agent runs yet. Run: engmemory agent-daemon --once</p>';
                return;
            }
            feed.innerHTML = runs.map(run => {
                const statusColor = run.result?.status === 'approved' ? 'green' :
                                    run.result?.status === 'failed' ? 'red' : 'yellow';
                const date = new Date(run.timestamp * 1000).toLocaleString();
                const duration = run.result?.duration_seconds || '?';
                return `
                    <div class="flex items-start gap-3 p-3 rounded-lg bg-gray-800/50 border border-gray-700/50">
                        <div class="w-3 h-3 rounded-full bg-${statusColor}-400 mt-1.5 shrink-0"></div>
                        <div class="flex-1 min-w-0">
                            <div class="flex items-center gap-2">
                                <span class="font-medium text-white">${run.issue_key}</span>
                                <span class="text-xs px-2 py-0.5 rounded bg-${statusColor}-900/50 text-${statusColor}-400">${run.result?.status || 'unknown'}</span>
                            </div>
                            <p class="text-sm text-gray-400 mt-0.5">Branch: ${run.branch || '?'}</p>
                            <p class="text-xs text-gray-500 mt-1">${date} · ${duration}s · ${run.result?.iteration || '?'} iteration(s)</p>
                            ${run.result?.summary ? `<p class="text-sm text-gray-300 mt-2">${run.result.summary}</p>` : ''}
                        </div>
                    </div>
                `;
            }).join('');
        }

        function renderDecisions(decisions) {
            const el = document.getElementById('decisions-list');
            if (!decisions || decisions.length === 0) {
                el.innerHTML = '<p class="text-gray-500">No decisions recorded yet</p>';
                return;
            }
            el.innerHTML = decisions.slice(-10).reverse().map(d => `
                <div class="text-sm border-l-2 border-primary pl-3">
                    <span class="text-xs text-gray-500">${d.agent}</span>
                    <p class="text-gray-300">${d.decision}</p>
                    ${d.reasoning ? `<p class="text-xs text-gray-500 mt-0.5">${d.reasoning}</p>` : ''}
                </div>
            `).join('');
        }

        function renderFeedback(feedback) {
            const el = document.getElementById('feedback-list');
            if (!feedback || feedback.length === 0) {
                el.innerHTML = '<p class="text-gray-500">No feedback yet. Run: engmemory agent-feedback "your feedback"</p>';
                return;
            }
            el.innerHTML = feedback.map(fb => `
                <div class="text-sm p-2 rounded bg-blue-900/20 border border-blue-800/30">
                    <p class="text-blue-200">"${fb.feedback}"</p>
                    ${fb.context ? `<p class="text-xs text-gray-500 mt-1">Context: ${fb.context}</p>` : ''}
                </div>
            `).join('');
        }

        function renderDiscussions(discussions) {
            const el = document.getElementById('discussions-list');
            if (!discussions || discussions.length === 0) {
                el.innerHTML = '<p class="text-gray-500">No team discussions captured yet</p>';
                return;
            }
            el.innerHTML = discussions.map(d => `
                <div class="text-sm border-l-2 border-purple-500 pl-3">
                    <span class="font-medium text-purple-300">${d.author}</span>
                    <span class="text-xs text-gray-500 ml-2">${d.channel || ''}</span>
                    <p class="text-gray-300 mt-0.5">${d.message}</p>
                </div>
            `).join('');
        }

        // Load on start + auto-refresh every 10s
        loadData();
        setInterval(loadData, 10000);
    </script>
</body>
</html>
"""


def create_dashboard_app(repo_path: str = ".") -> "Flask":
    """Create the Flask dashboard app."""
    if not HAS_FLASK:
        raise ImportError("Flask not installed. Run: pip install flask")

    app = Flask(__name__)
    memory_dir = Path(repo_path) / ".ai_memory"

    @app.route("/")
    def index():
        return render_template_string(DASHBOARD_HTML)

    @app.route("/api/data")
    def api_data():
        # Load agent runs
        runs = _load_runs(memory_dir)
        
        # Load agent memory (decisions + feedback)
        memory = _load_memory(memory_dir)
        
        # Load team discussions
        discussions = _load_discussions(memory_dir)

        # Compute stats
        stats = _compute_stats(runs, memory)

        return jsonify({
            "runs": runs,
            "decisions": memory.get("decisions", []),
            "feedback": memory.get("developer_feedback", []),
            "discussions": discussions,
            "stats": stats,
        })

    return app


def _load_runs(memory_dir: Path) -> list:
    """Load agent run history."""
    runs_file = memory_dir / "agent_runs.jsonl"
    if not runs_file.exists():
        return []
    
    runs = []
    try:
        for line in runs_file.read_text(encoding="utf-8").strip().split("\n"):
            if line.strip():
                runs.append(json.loads(line))
    except Exception:
        pass
    
    return sorted(runs, key=lambda r: r.get("timestamp", 0), reverse=True)[:50]


def _load_memory(memory_dir: Path) -> dict:
    """Load agent memory."""
    memory_file = memory_dir / "agent_memory.json"
    if not memory_file.exists():
        return {"decisions": [], "developer_feedback": []}
    
    try:
        return json.loads(memory_file.read_text(encoding="utf-8"))
    except Exception:
        return {"decisions": [], "developer_feedback": []}


def _load_discussions(memory_dir: Path) -> list:
    """Load team discussions."""
    disc_dir = memory_dir / "team_discussions"
    if not disc_dir.exists():
        return []
    
    discussions = []
    for f in sorted(disc_dir.glob("*.json"), reverse=True)[:20]:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(data, list):
                discussions.extend(data)
            elif isinstance(data, dict):
                discussions.append(data)
        except Exception:
            pass
    
    return discussions[:30]


def _compute_stats(runs: list, memory: dict) -> dict:
    """Compute dashboard statistics."""
    processed = len(runs)
    approved = sum(1 for r in runs if r.get("result", {}).get("status") == "approved")
    revised = sum(1 for r in runs if r.get("result", {}).get("status") == "max_iterations_reached")
    failed = sum(1 for r in runs if r.get("result", {}).get("status") == "failed")
    feedback_count = len(memory.get("developer_feedback", []))

    return {
        "processed": processed,
        "approved": approved,
        "revised": revised,
        "failed": failed,
        "feedback_count": feedback_count,
    }


def run_dashboard(repo_path: str = ".", port: int = 5050, debug: bool = False):
    """Start the dashboard server."""
    app = create_dashboard_app(repo_path)
    print(f"\n🤖 EngMemory Dashboard running at: http://localhost:{port}")
    print(f"   Repo: {os.path.abspath(repo_path)}")
    print("   Press Ctrl+C to stop.\n")
    app.run(host="0.0.0.0", port=port, debug=debug)
