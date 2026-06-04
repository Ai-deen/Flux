"""
cli.py

The `engmemory` command.

Usage:
    engmemory init              Install the post-commit hook
    engmemory uninstall         Remove the hook
    engmemory status            Show hook installation status
    engmemory test-commit       Dry-run capture on HEAD without installing hook
    engmemory recent            List recent captured commits
    engmemory analyze           Analyze commits with an LLM
    engmemory azure-setup       Set up Azure AI Search index
    engmemory index-commits     Index local commits into Azure AI Search
    engmemory ask               Ask a question using RAG over commit history
    engmemory jira              Fetch and display Jira issues
    engmemory jira-issue        Fetch details for a specific Jira issue
"""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .core import install, uninstall, status, capture_commit
from .storage import write_commit, read_recent


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------

def cmd_init(args: argparse.Namespace) -> None:
    msg = install(args.repo)
    print(msg)
    print(
        "\n✓ Setup complete! What was configured:\n"
        "  • Post-commit hook installed\n"
        "  • .ai_memory/ directory created\n"
        "  • .gitignore updated (commit logs stay local)\n"
        "  • VS Code extension installed (if available)\n"
        "\nNext steps:\n"
        "  1. Make a commit — the hook will capture it automatically\n"
        "  2. Check .ai_memory/commits/ for captured JSON\n"
        "  3. Use the EngMemory sidebar in VS Code to view commits\n"
        "  4. Run `engmemory index --analyze` to enable AI search\n"
        "  5. Run `engmemory ask \"How was X fixed?\"` to query history"
    )


def cmd_uninstall(args: argparse.Namespace) -> None:
    print(uninstall(args.repo))


def cmd_status(args: argparse.Namespace) -> None:
    print("Hook status:", status(args.repo))


def cmd_test_commit(args: argparse.Namespace) -> None:
    """Capture HEAD commit and print the JSON — no hook installation needed."""
    print("Capturing HEAD commit...")
    try:
        payload = capture_commit(args.repo)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.save:
        path = write_commit(payload, args.repo)
        print(f"Written to {path}\n")
    else:
        print("(Use --save to write to .ai_memory/commits/)\n")

    data = payload.to_dict()
    # Print without file diffs for readability; use --full for everything
    if not args.full:
        data["file_diffs"] = [
            {k: v for k, v in d.items() if k != "diff_text"}
            for d in data["file_diffs"]
        ]
    print(json.dumps(data, indent=2, ensure_ascii=False))


def cmd_recent(args: argparse.Namespace) -> None:
    entries = read_recent(args.repo, limit=args.limit)
    if not entries:
        print("No captured commits found in .ai_memory/index.jsonl")
        return
    for e in entries:
        ticket = f"[{e['ticket_id']}] " if e.get("ticket_id") else ""
        print(
            f"  {e['timestamp'][:16]}  {e['sha']}  "
            f"{e['branch']:<30}  {ticket}{e['message'][:80]}"
        )


def cmd_analyze(args: argparse.Namespace) -> None:
    """Analyze a commit or recent commits with an LLM."""
    from .analysis import analyze_commit, analyze_recent_commits
    from .storage import read_commit
    
    if args.sha:
        # Analyze a specific commit
        commit_data = read_commit(args.sha, args.repo)
        if not commit_data:
            print(f"Error: Commit {args.sha} not found in .ai_memory/commits/")
            sys.exit(1)
        
        print(f"Analyzing commit {commit_data['short_sha']}...")
        analysis = analyze_commit(commit_data)
        
        if not analysis:
            print("Error: OpenAI API key not set. Set OPENAI_API_KEY environment variable.")
            sys.exit(1)
        
        if "error" in analysis:
            print(f"Error: {analysis['error']}")
            sys.exit(1)
        
        print("\n" + "="*80)
        print(f"Commit: {commit_data['message']}")
        print("="*80)
        print(analysis["analysis"])
        print(f"\nModel: {analysis.get('model', 'N/A')}, Tokens: {analysis.get('tokens_used', 'N/A')}")
    
    else:
        # Analyze recent commits
        print(f"Analyzing {args.limit} most recent commits...")
        results = analyze_recent_commits(args.repo, limit=args.limit)
        
        if not results:
            print("No commits found or OpenAI API key not set.")
            return
        
        for result in results:
            commit = result["commit"]
            analysis = result["analysis"]
            
            # Get short SHA (first 8 chars)
            short_sha = commit.get('short_sha', commit.get('sha', 'unknown')[:8])
            
            print("\n" + "="*80)
            print(f"Commit: {short_sha} - {commit['message'][:60]}")
            print("="*80)
            
            if "error" in analysis:
                print(f"Error: {analysis['error']}")
            else:
                print(analysis["analysis"])
            print()


def cmd_azure_setup(args: argparse.Namespace) -> None:
    """Set up Azure AI Search index."""
    from .search import create_index
    from .utils import config
    
    print("Setting up Azure AI Search...")
    print(f"Endpoint: {config.azure_search_endpoint}")
    print(f"Index: {config.azure_search_index}")
    
    if not config.is_azure_configured():
        print("\nError: Azure not configured. Set these environment variables:")
        print("  - AZURE_SEARCH_ENDPOINT")
        print("  - AZURE_SEARCH_ADMIN_KEY")
        print("  - AZURE_STORAGE_ENDPOINT")
        print("\nSee docs/azure_setup.md for instructions.")
        sys.exit(1)
    
    if create_index():
        print(f"\n✓ Index '{config.azure_search_index}' created successfully!")
    else:
        print("\n✗ Failed to create index. Check logs for details.")
        sys.exit(1)


def cmd_index_commits(args: argparse.Namespace) -> None:
    """Index local commits into Azure AI Search + Azure Blob Storage."""
    from .search import index_commit
    from .storage import read_recent, read_commit
    from .storage.azure_blob import upload_commit_to_blob, _get_blob_service_client
    from .analysis import analyze_commit
    from pathlib import Path
    import json
    
    print(f"Indexing {args.limit} most recent commits...")
    
    recent = read_recent(args.repo, limit=args.limit)
    if not recent:
        print("No commits found to index.")
        return
    
    # Load AI session contexts from Azure Blob
    ai_contexts = {}
    try:
        blob_service = _get_blob_service_client()
        if blob_service:
            container = blob_service.get_container_client("ai-sessions")
            for blob in container.list_blobs():
                try:
                    data = json.loads(container.get_blob_client(blob.name).download_blob().readall())
                    sha = data.get("commit_sha", "")
                    if sha:
                        ai_contexts[sha] = data.get("ai_context", "")
                except Exception:
                    pass
    except Exception:
        pass  # AI sessions container might not exist yet
    
    indexed = 0
    for entry in recent:
        commit_data = read_commit(entry["sha"], args.repo)
        if not commit_data:
            continue
        
        # Get AI context for this commit
        short_sha = commit_data.get("short_sha", entry["sha"][:8])
        ai_context = ai_contexts.get(short_sha, "")
        
        # Optionally analyze if not already done
        analysis = None
        if args.analyze:
            print(f"Analyzing commit {short_sha}...")
            analysis = analyze_commit(commit_data, ai_context)
        
        # Index to Azure AI Search
        if index_commit(commit_data, analysis):
            indexed += 1
            print(f"✓ Indexed {short_sha}: {commit_data['message'][:60]}")
        
        # Upload to Azure Blob Storage
        upload_commit_to_blob(commit_data, analysis)
    
    print(f"\nIndexed {indexed}/{len(recent)} commits.")


def cmd_ask(args: argparse.Namespace) -> None:
    """Ask a question using RAG over commit history."""
    from .search import ask_question
    
    if args.question:
        question = args.question
    else:
        question = input("Ask a question about your commit history:\n> ")
    
    if not question.strip():
        print("No question provided.")
        return
    
    print("\nSearching commit history...")
    answer = ask_question(question, top_k=args.top_k)
    
    print("\n" + "="*80)
    print("ANSWER")
    print("="*80)
    print(answer)


def cmd_jira(args: argparse.Namespace) -> None:
    """Fetch and display Jira issues."""
    from .utils.jira import print_jira_issues, get_jira_issues
    
    if args.raw:
        # Print raw JSON
        issues = get_jira_issues(board_id=args.board, max_results=args.limit)
        import json
        print(json.dumps(issues, indent=2))
    else:
        # Print formatted
        print(f"Fetching Jira issues (max {args.limit})...\n")
        print_jira_issues(board_id=args.board)


def cmd_jira_issue(args: argparse.Namespace) -> None:
    """Fetch and display details for a specific Jira issue."""
    from .utils.jira import print_issue_details, get_issue_details
    
    if args.raw:
        # Print raw JSON
        import json
        issue = get_issue_details(args.issue_key)
        print(json.dumps(issue, indent=2))
    else:
        # Print formatted
        print_issue_details(args.issue_key)


def cmd_backfill(args: argparse.Namespace) -> None:
    """Capture all past commits from git history (for existing repos)."""
    from .core.capture import capture_commit_by_sha
    from .storage import write_commit
    
    import git as gitmodule
    
    repo = gitmodule.Repo(args.repo, search_parent_directories=True)
    commits = list(repo.iter_commits(max_count=args.limit))
    
    print(f"Backfilling {len(commits)} commits from git history...")
    
    captured = 0
    for commit in commits:
        try:
            payload = capture_commit_by_sha(args.repo, commit.hexsha)
            write_commit(payload, args.repo)
            captured += 1
            print(f"  ✓ {payload.short_sha}: {payload.message[:50]}")
        except Exception as exc:
            print(f"  ✗ {commit.hexsha[:8]}: {exc}")
    
    print(f"\nBackfilled {captured}/{len(commits)} commits.")
    print("Run `engmemory index --analyze` to push them to Azure AI Search.")


# ---------------------------------------------------------------------------
# Agent commands
# ---------------------------------------------------------------------------

def cmd_agent(args: argparse.Namespace) -> None:
    """Run the AI agent to auto-solve from Jira ticket or branch."""
    from .agent import Agent

    agent = Agent(
        repo_path=args.repo,
        max_retries=args.max_retries,
        dry_run=args.dry_run,
    )

    kwargs = {"trigger": args.trigger}
    if args.trigger == "jira":
        if not args.issue:
            print("Error: --issue required for jira trigger")
            print("Usage: engmemory agent --trigger jira --issue ENG-456")
            sys.exit(1)
        kwargs["issue_key"] = args.issue
    elif args.trigger == "branch":
        kwargs["branch_name"] = args.branch or ""
    elif args.trigger == "manual":
        if not args.prompt:
            print("Error: --prompt required for manual trigger")
            sys.exit(1)
        kwargs["prompt"] = args.prompt

    print(f"{'[DRY RUN] ' if args.dry_run else ''}Starting agent...")
    print(f"  Trigger: {args.trigger}")
    print(f"  Data: {kwargs}")
    print()

    def on_step(result):
        icon = "✓" if result.success else "✗"
        retry_info = f" (retry {result.retries})" if result.retries else ""
        print(f"  {icon} Step {result.step_id}: {result.description}{retry_info}")
        if result.output and not args.dry_run:
            for line in result.output.splitlines()[:3]:
                print(f"      {line}")
        if result.error:
            print(f"      Error: {result.error[:100]}")

    agent.on_step_complete = on_step
    run = agent.run(**kwargs)

    print(f"\n{'='*60}")
    print(f"Agent result: {run.state.value}")
    print(f"Steps: {len(run.results)} | "
          f"Success: {sum(1 for r in run.results if r.success)} | "
          f"Failed: {sum(1 for r in run.results if not r.success)}")
    if run.completed_at and run.started_at:
        print(f"Duration: {run.completed_at - run.started_at:.1f}s")


def cmd_agent_watch(args: argparse.Namespace) -> None:
    """Watch for branch changes and auto-trigger agent."""
    from .agent import Agent, Watcher

    print("Watching for feature branch changes...")
    print("(Create/checkout a branch with a Jira ticket ID to trigger the agent)")
    print("Press Ctrl+C to stop.\n")

    def on_trigger(data):
        print(f"\n{'='*60}")
        print(f"[Trigger] {data}")
        agent = Agent(repo_path=args.repo, dry_run=args.dry_run)
        result = agent.run(**data)
        print(f"[Result] {result.state.value}")
        print(f"{'='*60}\n")

    watcher = Watcher(repo_path=args.repo, on_trigger=on_trigger)
    try:
        watcher.watch()
    except KeyboardInterrupt:
        print("\nStopped watching.")


def cmd_agent_install(args: argparse.Namespace) -> None:
    """Install git hooks for agent auto-trigger."""
    from .agent import Watcher

    watcher = Watcher(repo_path=args.repo)
    result = watcher.install_hooks()
    print(result)
    print("\nThe agent will now auto-trigger when you checkout a feature branch")
    print("with a Jira ticket ID (e.g., git checkout -b feature/ENG-456-auth)")


def cmd_agent_context(args: argparse.Namespace) -> None:
    """Show what context the agent would gather (for debugging)."""
    from .agent import ContextBuilder

    builder = ContextBuilder(repo_path=args.repo)
    context = builder.build_full_context(
        issue_key=args.issue,
        branch_name=args.branch,
    )

    print("="*60)
    print("AGENT CONTEXT (what would be sent to Copilot/LLM)")
    print("="*60)
    print(context)
    print(f"\n[Context length: {len(context)} chars]")


def cmd_agent_multi(args: argparse.Namespace) -> None:
    """Run the multi-agent system (Context → Code → Review loop)."""
    from .agent.multi_agent import MultiAgentOrchestrator

    print(f"{'[DRY RUN] ' if args.dry_run else ''}Starting multi-agent system...")
    print(f"  Issue: {args.issue or 'none'}")
    print(f"  Max iterations: {args.iterations}")
    print()

    def on_complete(result):
        print(f"\n{'='*60}")
        print(f"🤖 Multi-Agent Result: {result['status']}")
        print(f"   Iterations: {result['iteration']}")
        print(f"   Duration: {result.get('duration_seconds', 0)}s")
        if result.get('summary'):
            print(f"   Summary: {result['summary']}")
        print(f"{'='*60}")

    orchestrator = MultiAgentOrchestrator(
        repo_path=args.repo,
        max_iterations=args.iterations,
        dry_run=args.dry_run,
        on_complete=on_complete,
    )

    orchestrator.run(issue_key=args.issue, search_query=args.query)


def cmd_agent_daemon(args: argparse.Namespace) -> None:
    """Run the background daemon that watches for new tickets."""
    from .agent.daemon import AgentDaemon

    daemon = AgentDaemon(
        repo_path=args.repo,
        poll_interval=args.interval,
        dry_run=args.dry_run,
        assignee_filter=args.assignee,
    )

    if args.once:
        print("Checking for new tickets (single run)...")
        daemon.check_once()
    else:
        print("🤖 EngMemory Agent Daemon starting...")
        print(f"   Watching Jira every {args.interval}s")
        print(f"   Repo: {args.repo}")
        if args.assignee:
            print(f"   Filter: tickets assigned to {args.assignee}")
        print("   Press Ctrl+C to stop.\n")
        try:
            daemon.start()
        except KeyboardInterrupt:
            print("\nDaemon stopped.")


def cmd_agent_feedback(args: argparse.Namespace) -> None:
    """Record developer feedback for the agent to learn from."""
    from .agent.multi_agent import MultiAgentOrchestrator

    orchestrator = MultiAgentOrchestrator(repo_path=args.repo)

    feedback = args.feedback
    if not feedback:
        feedback = input("Enter your feedback for the agent:\n> ")

    if feedback.strip():
        orchestrator.record_feedback(feedback, context=args.context or "")
        print(f"✓ Feedback recorded. The agent will use this in future decisions.")
    else:
        print("No feedback provided.")


def cmd_dashboard(args: argparse.Namespace) -> None:
    """Start the web dashboard."""
    from .agent.dashboard import run_dashboard
    run_dashboard(repo_path=args.repo, port=args.port)


def cmd_team_chat(args: argparse.Namespace) -> None:
    """Add a team discussion message or start the webhook server."""
    from .agent.team_chat import TeamChatIntegration

    chat = TeamChatIntegration(repo_path=args.repo)

    if args.server:
        # Start webhook receiver server
        from .agent.team_chat import create_webhook_app
        app = create_webhook_app(repo_path=args.repo)
        print(f"🔗 Team Chat webhook server running at http://localhost:{args.port}")
        print(f"   POST /webhook/slack   — for Slack webhooks")
        print(f"   POST /webhook/teams   — for Teams webhooks")
        print(f"   POST /webhook/message — for manual messages")
        print("   Press Ctrl+C to stop.\n")
        app.run(host="0.0.0.0", port=args.port)
    elif args.message:
        # Add a message manually
        entry = chat.add_message(
            message=args.message,
            author=args.author or "Developer",
            channel=args.channel,
            ticket_id=args.ticket,
        )
        print(f"✓ Message recorded for {args.ticket or 'general'}")
    elif args.show:
        # Show discussions for a ticket
        messages = chat.get_discussion(args.show)
        if messages:
            for msg in messages:
                print(f"  [{msg.get('date', '?')}] {msg['author']}: {msg['message']}")
        else:
            print(f"No discussions found for {args.show}")
    else:
        # Show recent
        recent = chat.get_all_recent(limit=10)
        if recent:
            for msg in recent:
                ticket = f" [{msg.get('ticket_id')}]" if msg.get('ticket_id') else ""
                print(f"  [{msg.get('date', '?')}]{ticket} {msg['author']}: {msg['message'][:80]}")
        else:
            print("No team discussions recorded yet.")
            print("Add one: engmemory team-chat --message 'discussion text' --ticket KAN-1")


# ---------------------------------------------------------------------------
# Pipeline commands
# ---------------------------------------------------------------------------

def cmd_pipeline(args: argparse.Namespace) -> None:
    """Run the Ask Orchestrator pipeline for a ticket."""
    from .orchestrator.ask_orchestrator import AskOrchestrator

    orch = AskOrchestrator(repo_path=args.repo)

    if args.action == "start":
        if not args.issue:
            print("Error: --issue required")
            sys.exit(1)
        state = orch.start_pipeline(args.issue, args.branch or "")
        print(f"✓ Pipeline started for {args.issue}")
        print(f"  Stage: {state.stage.value}")
        print(f"  Branch: {state.branch_name}")

    elif args.action == "context":
        if not args.issue:
            print("Error: --issue required")
            sys.exit(1)
        print(f"Gathering context for {args.issue}...")
        context = orch.gather_context(args.issue)
        print(f"\n{'='*60}")
        print(context[:3000])
        if len(context) > 3000:
            print(f"\n... ({len(context)} total chars)")

    elif args.action == "prompt":
        if not args.issue:
            print("Error: --issue required")
            sys.exit(1)
        orch.start_pipeline(args.issue)
        prompt = orch.get_developer_prompt(args.issue)
        print(prompt)

    elif args.action == "ask":
        if not args.issue or not args.question:
            print("Error: --issue and --question required")
            sys.exit(1)
        orch.start_pipeline(args.issue)
        answer = orch.handle_developer_question(args.question)
        print(f"\n{'='*60}")
        print(answer)

    elif args.action == "status":
        if not args.issue:
            print("Error: --issue required")
            sys.exit(1)
        orch.start_pipeline(args.issue)
        status = orch.get_status()
        print(json.dumps(status, indent=2))

    elif args.action == "conversation":
        if not args.issue:
            print("Error: --issue required")
            sys.exit(1)
        orch.start_pipeline(args.issue)
        messages = orch.get_conversation_log()
        for msg in messages:
            icon = {"orchestrator": "🧠", "developer": "👨‍💻", "reviewer": "👁",
                    "tester": "🧪", "user": "🧑"}.get(msg["role"], "💬")
            ts = msg.get("timestamp", "")[:19]
            print(f"  {icon} [{msg['role']}] {ts}")
            print(f"     {msg['content'][:200]}")
            print()


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="engmemory",
        description="Engineering memory — capture and search your commit intelligence",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    sub = parser.add_subparsers(dest="command", required=True)

    # Shared --repo option
    def add_repo(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--repo",
            default=".",
            metavar="PATH",
            help="Path to git repo root (default: current directory)",
        )

    p_init = sub.add_parser("init", help="Install post-commit hook into current repo")
    add_repo(p_init)
    p_init.set_defaults(func=cmd_init)

    p_uninstall = sub.add_parser("uninstall", help="Remove hook from current repo")
    add_repo(p_uninstall)
    p_uninstall.set_defaults(func=cmd_uninstall)

    p_status = sub.add_parser("status", help="Show hook installation status")
    add_repo(p_status)
    p_status.set_defaults(func=cmd_status)

    p_test = sub.add_parser("test-commit", help="Dry-run capture on HEAD commit")
    add_repo(p_test)
    p_test.add_argument("--save", action="store_true", help="Write JSON to .ai_memory/commits/")
    p_test.add_argument("--full", action="store_true", help="Include full diff text in output")
    p_test.set_defaults(func=cmd_test_commit)

    p_recent = sub.add_parser("recent", help="List recently captured commits")
    add_repo(p_recent)
    p_recent.add_argument("--limit", type=int, default=20, metavar="N")
    p_recent.set_defaults(func=cmd_recent)

    p_analyze = sub.add_parser("analyze", help="Analyze commits with an LLM")
    add_repo(p_analyze)
    p_analyze.add_argument("--limit", type=int, default=5, metavar="N", help="Number of recent commits to analyze")
    p_analyze.add_argument("--sha", type=str, help="Analyze a specific commit by SHA")
    p_analyze.set_defaults(func=cmd_analyze)

    p_azure_setup = sub.add_parser("azure-setup", help="Create Azure AI Search index")
    p_azure_setup.set_defaults(func=cmd_azure_setup)

    p_index = sub.add_parser("index", help="Index commits into Azure AI Search")
    add_repo(p_index)
    p_index.add_argument("--limit", type=int, default=20, metavar="N", help="Number of recent commits to index")
    p_index.add_argument("--analyze", action="store_true", help="Analyze commits before indexing")
    p_index.set_defaults(func=cmd_index_commits)

    p_ask = sub.add_parser("ask", help="Ask a question using RAG over commit history")
    p_ask.add_argument("question", nargs="?", help="Question to ask (interactive if not provided)")
    p_ask.add_argument("--top-k", type=int, default=5, help="Number of commits to retrieve")
    p_ask.set_defaults(func=cmd_ask)

    p_jira = sub.add_parser("jira", help="Fetch and display Jira issues")
    p_jira.add_argument("--board", type=str, help="Jira board ID (uses JIRA_BOARD_ID from env if not provided)")
    p_jira.add_argument("--limit", type=int, default=50, help="Maximum number of issues to fetch")
    p_jira.add_argument("--raw", action="store_true", help="Print raw JSON instead of formatted output")
    p_jira.set_defaults(func=cmd_jira)

    p_jira_issue = sub.add_parser("jira-issue", help="Fetch details for a specific Jira issue")
    p_jira_issue.add_argument("issue_key", type=str, help="Jira issue key (e.g., PROJ-123)")
    p_jira_issue.add_argument("--raw", action="store_true", help="Print raw JSON instead of formatted output")
    p_jira_issue.set_defaults(func=cmd_jira_issue)

    p_backfill = sub.add_parser("backfill", help="Capture all past commits from git history")
    add_repo(p_backfill)
    p_backfill.add_argument("--limit", type=int, default=100, metavar="N", help="Max commits to backfill")
    p_backfill.set_defaults(func=cmd_backfill)

    # --- Agent commands ---
    p_agent = sub.add_parser("agent", help="Run the AI agent (auto-solve from Jira/branch)")
    add_repo(p_agent)
    p_agent.add_argument("--trigger", choices=["jira", "branch", "manual"], default="jira",
                         help="What triggers the agent")
    p_agent.add_argument("--issue", type=str, help="Jira issue key (e.g., ENG-456)")
    p_agent.add_argument("--branch", type=str, help="Branch name to work on")
    p_agent.add_argument("--prompt", type=str, help="Manual instruction for the agent")
    p_agent.add_argument("--dry-run", action="store_true", help="Plan only, don't execute")
    p_agent.add_argument("--max-retries", type=int, default=3, help="Max retries per step")
    p_agent.set_defaults(func=cmd_agent)

    p_agent_watch = sub.add_parser("agent-watch", help="Watch for branch changes and auto-trigger agent")
    add_repo(p_agent_watch)
    p_agent_watch.add_argument("--dry-run", action="store_true", help="Plan only, don't execute")
    p_agent_watch.set_defaults(func=cmd_agent_watch)

    p_agent_install = sub.add_parser("agent-install", help="Install git hooks for agent auto-trigger")
    add_repo(p_agent_install)
    p_agent_install.set_defaults(func=cmd_agent_install)

    p_agent_context = sub.add_parser("agent-context", help="Show what context the agent would gather")
    add_repo(p_agent_context)
    p_agent_context.add_argument("--issue", type=str, help="Jira issue key")
    p_agent_context.add_argument("--branch", type=str, help="Branch name")
    p_agent_context.set_defaults(func=cmd_agent_context)

    p_agent_multi = sub.add_parser("agent-multi", help="Run multi-agent system (Context→Code→Review loop)")
    add_repo(p_agent_multi)
    p_agent_multi.add_argument("--issue", type=str, help="Jira issue key")
    p_agent_multi.add_argument("--query", type=str, help="Search query for context")
    p_agent_multi.add_argument("--iterations", type=int, default=3, help="Max review iterations")
    p_agent_multi.add_argument("--dry-run", action="store_true", help="Plan only, don't execute")
    p_agent_multi.set_defaults(func=cmd_agent_multi)

    p_agent_daemon = sub.add_parser("agent-daemon", help="Background daemon: auto-process new Jira tickets")
    add_repo(p_agent_daemon)
    p_agent_daemon.add_argument("--interval", type=int, default=60, help="Poll interval in seconds")
    p_agent_daemon.add_argument("--assignee", type=str, help="Only process tickets assigned to this user")
    p_agent_daemon.add_argument("--dry-run", action="store_true", help="Plan only, don't execute")
    p_agent_daemon.add_argument("--once", action="store_true", help="Single check then exit")
    p_agent_daemon.set_defaults(func=cmd_agent_daemon)

    p_feedback = sub.add_parser("agent-feedback", help="Give feedback to the agent (it learns from this)")
    add_repo(p_feedback)
    p_feedback.add_argument("feedback", nargs="?", help="Your feedback text")
    p_feedback.add_argument("--context", type=str, default="", help="What the feedback is about")
    p_feedback.set_defaults(func=cmd_agent_feedback)

    # --- Dashboard & Team Chat ---
    p_dashboard = sub.add_parser("dashboard", help="Start the web dashboard")
    add_repo(p_dashboard)
    p_dashboard.add_argument("--port", type=int, default=5050, help="Port to run on")
    p_dashboard.set_defaults(func=cmd_dashboard)

    p_team = sub.add_parser("team-chat", help="Team discussion integration (Slack/Teams)")
    add_repo(p_team)
    p_team.add_argument("--message", type=str, help="Add a discussion message")
    p_team.add_argument("--author", type=str, help="Message author")
    p_team.add_argument("--channel", type=str, default="general", help="Channel name")
    p_team.add_argument("--ticket", type=str, help="Link message to a ticket")
    p_team.add_argument("--show", type=str, help="Show discussions for a ticket")
    p_team.add_argument("--server", action="store_true", help="Start webhook receiver server")
    p_team.add_argument("--port", type=int, default=5051, help="Webhook server port")
    p_team.set_defaults(func=cmd_team_chat)

    # --- Pipeline (Ask Orchestrator) ---
    p_pipeline = sub.add_parser("pipeline", help="Run the Ask Orchestrator pipeline (dev→review→test→PR)")
    add_repo(p_pipeline)
    p_pipeline.add_argument("action", choices=["start", "context", "prompt", "ask", "status", "conversation"],
                            help="Pipeline action")
    p_pipeline.add_argument("--issue", type=str, help="Jira issue key (e.g., KAN-8)")
    p_pipeline.add_argument("--branch", type=str, help="Branch name")
    p_pipeline.add_argument("--question", type=str, help="Question to ask (for 'ask' action)")
    p_pipeline.set_defaults(func=cmd_pipeline)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()