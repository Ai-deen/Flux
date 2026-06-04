# Getting Started - Using EngMemory in Your Project

This guide shows you how to set up and use **engmemory** in any Git repository.

## Quick Start (5 Minutes)

### Step 1: Install EngMemory

Choose one of these installation methods:

#### Option A: Install from Source (Recommended for Development)
```bash
# Clone the engmemory repository
cd ~/projects  # or wherever you keep projects
git clone <engmemory-repo-url>
cd hackathon

# Install engmemory package
pip install -e .

# Verify installation
engmemory --version
```

#### Option B: Install from PyPI (When Published)
```bash
pip install engmemory
```

#### Option C: Install from Local Path
```bash
# If you already have engmemory downloaded
pip install /path/to/hackathon
```

### Step 2: Navigate to Your Project

```bash
# Go to ANY Git repository where you want to use engmemory
cd ~/projects/my-awesome-project
```

### Step 3: Install the Hook

```bash
# This installs the post-commit hook in THIS repository
engmemory init
```

**Output:**
```
✓ Installed post-commit hook in /home/user/projects/my-awesome-project/.git/hooks/
```

### Step 4: Make a Commit

```bash
# Make any commit
git commit -m "TEST-123: Testing engmemory"
```

**That's it!** The hook will automatically capture your commit data to `.ai_memory/commits/`.

---

## Configuration (Optional but Recommended)

Create a `.env` file in your project or set environment variables:

### Minimal Setup (Local Only)

```bash
# Nothing required! Just works locally
```

### Enable AI Analysis

```bash
# Add to ~/.bashrc or project .env
export OPENAI_API_KEY="sk-..."
# OR
export OPENROUTER_API_KEY="sk-or-..."
```

### Enable Jira Integration

```bash
export JIRA_DOMAIN="your-company.atlassian.net"
export JIRA_EMAIL="your-email@company.com"
export JIRA_API_TOKEN="your-api-token"
```

**How to get Jira API token:**
1. Go to https://id.atlassian.com/manage-profile/security/api-tokens
2. Click "Create API token"
3. Copy the token

### Enable Azure Storage

```bash
export AZURE_STORAGE_ENDPOINT="https://youraccount.blob.core.windows.net"
```

**Authentication:**
```bash
# Login to Azure
az login

# Or set up service principal
export AZURE_CLIENT_ID="..."
export AZURE_CLIENT_SECRET="..."
export AZURE_TENANT_ID="..."
```

---

## Using EngMemory in Multiple Projects

You can install the hook in **multiple repositories** - each will have its own `.ai_memory/` folder:

```bash
# Project 1
cd ~/projects/frontend-app
engmemory init

# Project 2
cd ~/projects/backend-api
engmemory init

# Project 3
cd ~/projects/mobile-app
engmemory init
```

Each project will independently capture its commits!

---

## Environment Setup Guide

### Option 1: Global Configuration (All Projects)

Add to `~/.bashrc` or `~/.zshrc`:

```bash
# LLM API Keys
export OPENAI_API_KEY="sk-..."
# or
export OPENROUTER_API_KEY="sk-or-..."

# Jira Configuration
export JIRA_DOMAIN="company.atlassian.net"
export JIRA_EMAIL="you@company.com"
export JIRA_API_TOKEN="your-token"

# Azure Configuration
export AZURE_STORAGE_ENDPOINT="https://account.blob.core.windows.net"
```

Then reload:
```bash
source ~/.bashrc
```

### Option 2: Per-Project Configuration

Create `.env` file in each project:

```bash
cd ~/projects/my-project

# Create .env file
cat > .env << 'EOF'
export OPENAI_API_KEY="sk-..."
export JIRA_DOMAIN="company.atlassian.net"
export JIRA_EMAIL="you@company.com"
export JIRA_API_TOKEN="your-token"
EOF

# Load it before committing
source .env
git commit -m "PROJ-123: My change"
```

**Add .env to .gitignore:**
```bash
echo ".env" >> .gitignore
```

### Option 3: Use direnv (Automatic per-directory)

```bash
# Install direnv
brew install direnv  # macOS
# or
sudo apt install direnv  # Linux

# Add to shell
echo 'eval "$(direnv hook bash)"' >> ~/.bashrc

# Create .envrc in project
cd ~/projects/my-project
cat > .envrc << 'EOF'
export OPENAI_API_KEY="sk-..."
export JIRA_DOMAIN="company.atlassian.net"
export JIRA_EMAIL="you@company.com"
export JIRA_API_TOKEN="your-token"
EOF

# Allow it
direnv allow

# Now env vars auto-load when you cd into this directory!
```

---

## Verification Checklist

After setup, verify everything works:

### 1. Check Installation
```bash
engmemory --version
engmemory status
```

Expected output:
```
Hook status: installed
```

### 2. Test Capture
```bash
# Make a test commit
git commit --allow-empty -m "TEST: engmemory setup test"

# Check if captured
ls .ai_memory/commits/
engmemory recent
```

### 3. Test Jira Integration (if configured)
```bash
# Commit with a real ticket ID
git commit --allow-empty -m "PROJ-123: Testing Jira integration"

# Check logs
tail .ai_memory/engmemory.log
```

Look for:
```
INFO Fetching Jira issue details for PROJ-123
INFO Fetched Jira context for PROJ-123
```

### 4. Test AI Analysis (if configured)
```bash
# Check logs for analysis
grep "Analysis completed" .ai_memory/engmemory.log
```

### 5. Test Azure Upload (if configured)
```bash
# Check logs for upload
grep "Uploaded to Azure Blob" .ai_memory/engmemory.log
```

---

## Project Structure

After installation, your project will have:

```
your-project/
├── .git/
│   └── hooks/
│       └── post-commit          # ← Installed by engmemory
├── .ai_memory/                  # ← Created automatically
│   ├── commits/                 # Captured commit JSONs
│   │   └── 2026-05-24T10-30-00_abc123.json
│   ├── index.jsonl              # Quick index
│   └── engmemory.log            # Activity log
├── .env                         # ← Your config (optional)
├── .gitignore                   # ← Add .env and .ai_memory/
└── ... (your project files)
```

**Important:** Add to `.gitignore`:
```bash
# Add these to .gitignore
echo ".ai_memory/" >> .gitignore
echo ".env" >> .gitignore
git add .gitignore
git commit -m "Add engmemory to gitignore"
```

---

## Common Workflows

### Workflow 1: Local Development (No Cloud)

```bash
# 1. Install
pip install -e /path/to/hackathon
cd ~/my-project
engmemory init

# 2. Use normally
git commit -m "Fix bug"

# 3. View captured data
engmemory recent
cat .ai_memory/commits/*.json
```

### Workflow 2: With AI Analysis

```bash
# 1. Set API key
export OPENAI_API_KEY="sk-..."

# 2. Commit
git commit -m "Add feature"

# 3. View analysis
engmemory analyze --limit 1
```

### Workflow 3: Full Integration (Jira + AI + Azure)

```bash
# 1. Set all credentials
export OPENAI_API_KEY="sk-..."
export JIRA_DOMAIN="company.atlassian.net"
export JIRA_EMAIL="you@company.com"
export JIRA_API_TOKEN="token"
export AZURE_STORAGE_ENDPOINT="https://..."

# 2. Commit with ticket ID
git commit -m "PROJ-123: Implement OAuth"

# 3. Everything happens automatically!
# Check log to see all steps
tail -f .ai_memory/engmemory.log
```

---

## Team Setup

### For Team Leads

1. **Share engmemory installation instructions** with team
2. **Create team .env template**:
   ```bash
   # Save as .env.example (commit this)
   export JIRA_DOMAIN="company.atlassian.net"
   export JIRA_EMAIL="YOUR_EMAIL"
   export JIRA_API_TOKEN="YOUR_TOKEN"
   export AZURE_STORAGE_ENDPOINT="https://team-storage.blob.core.windows.net"
   ```
3. **Add to README**:
   ```markdown
   ## EngMemory Setup
   
   1. Install: `pip install engmemory`
   2. Setup hook: `engmemory init`
   3. Copy `.env.example` to `.env` and fill in your credentials
   4. Source it: `source .env`
   ```

### For Team Members

1. Clone the project
2. Install engmemory: `pip install engmemory`
3. Install hook: `engmemory init`
4. Copy `.env.example` to `.env`
5. Fill in your personal credentials
6. Start committing!

---

## Troubleshooting

### Hook Not Running

```bash
# Check if installed
ls -la .git/hooks/post-commit

# Check if executable
chmod +x .git/hooks/post-commit

# Reinstall
engmemory init
```

### Environment Variables Not Working

```bash
# Check if set
echo $OPENAI_API_KEY
echo $JIRA_DOMAIN

# Source .env before committing
source .env
git commit -m "Test"
```

### Commits Not Captured

```bash
# Check logs
cat .ai_memory/engmemory.log

# Test manually
engmemory test-commit --save
```

### Jira Fetch Failing

```bash
# Test Jira connection
engmemory jira-issue PROJ-123

# Check credentials
python -c "
from engmemory.utils.config import config
print(f'Domain: {config.jira_domain}')
print(f'Email: {config.jira_email}')
print(f'Token set: {bool(config.jira_api_token)}')
"
```

---

## Uninstallation

### Remove from One Project

```bash
cd ~/projects/my-project
engmemory uninstall
```

### Remove from System

```bash
pip uninstall engmemory
```

### Clean Up Data

```bash
# Remove captured data (optional)
rm -rf .ai_memory/
```

---

## Next Steps

After setup, explore these features:

1. **View Recent Commits**: `engmemory recent`
2. **Analyze Commits**: `engmemory analyze --limit 5`
3. **Query Jira**: `engmemory jira-issue PROJ-123`
4. **Ask Questions** (with Azure): `engmemory ask "How was X fixed?"`
5. **Index for Search**: `engmemory index --limit 100`

---

## See Also

- [Enhanced Workflow Guide](enhanced_workflow.md) - Full feature documentation
- [Jira Integration](jira_issue_details.md) - Jira setup details
- [Azure Setup](azure_setup.md) - Azure configuration
- [Workflow Diagrams](workflow_diagrams.md) - Visual guides

---

## Quick Reference Card

```bash
# Installation
pip install -e /path/to/hackathon

# Setup in project
cd /path/to/your-project
engmemory init

# Environment (pick what you want)
export OPENAI_API_KEY="sk-..."        # For AI
export JIRA_DOMAIN="company.atlassian.net"  # For Jira
export JIRA_EMAIL="you@company.com"
export JIRA_API_TOKEN="token"
export AZURE_STORAGE_ENDPOINT="https://..." # For cloud

# Use
git commit -m "PROJ-123: Your change"  # Just commit normally!

# View
engmemory recent                      # List commits
engmemory analyze                     # Analyze recent
engmemory jira-issue PROJ-123         # View Jira issue
tail .ai_memory/engmemory.log         # Check logs
```

---

Need help? Check the logs at `.ai_memory/engmemory.log` or create an issue!
