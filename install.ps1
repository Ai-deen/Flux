# ==============================================================================
# EngMemory / Flux - One-Click Installer for Windows
# Microsoft Build AI Hackathon 2026
# ==============================================================================
#
# Usage: Right-click "Run with PowerShell" OR open PowerShell and run:
#   .\install.ps1
#
# This script:
#   1. Checks prerequisites (Python, Node.js, Git)
#   2. Offers Demo Mode (pre-configured) or Custom Project setup
#   3. Creates .env configuration
#   4. Installs Python + Node dependencies
#   5. Starts the API server + Dashboard
#   6. Opens the dashboard in your browser
# ==============================================================================

$ErrorActionPreference = "Stop"
$Host.UI.RawUI.WindowTitle = "EngMemory / Flux Installer"

# --- Colors and Helpers -------------------------------------------------------

function Write-Banner {
    Write-Host ""
    Write-Host "  =============================================================" -ForegroundColor Cyan
    Write-Host "  |      EngMemory / Flux - Automated Dev Workflow            |" -ForegroundColor Cyan
    Write-Host "  |      Microsoft Build AI Hackathon 2026                    |" -ForegroundColor Cyan
    Write-Host "  =============================================================" -ForegroundColor Cyan
    Write-Host ""
}

function Write-Step {
    param([string]$step, [string]$msg)
    Write-Host "  [$step] " -ForegroundColor Green -NoNewline
    Write-Host $msg
}

function Write-Warn {
    param([string]$msg)
    Write-Host "  [!] $msg" -ForegroundColor Yellow
}

function Write-Err {
    param([string]$msg)
    Write-Host "  [ERROR] $msg" -ForegroundColor Red
}

function Test-CommandExists {
    param([string]$cmd)
    $result = Get-Command $cmd -ErrorAction SilentlyContinue
    return ($null -ne $result)
}

# --- Prerequisites Check ------------------------------------------------------

function Test-Prerequisites {
    Write-Step "1/6" "Checking prerequisites..."
    $missing = @()

    if (Test-CommandExists "python") {
        $pyVer = python --version 2>&1
        Write-Host "       Python: $pyVer" -ForegroundColor DarkGray
    } else {
        $missing += "Python 3.11+ (https://python.org/downloads)"
    }

    if (Test-CommandExists "node") {
        $nodeVer = node --version 2>&1
        Write-Host "       Node.js: $nodeVer" -ForegroundColor DarkGray
    } else {
        $missing += "Node.js 18+ (https://nodejs.org)"
    }

    if (Test-CommandExists "git") {
        $gitVer = git --version 2>&1
        Write-Host "       Git: $gitVer" -ForegroundColor DarkGray
    } else {
        $missing += "Git (https://git-scm.com)"
    }

    if ($missing.Count -gt 0) {
        Write-Err "Missing prerequisites:"
        foreach ($m in $missing) { Write-Host "       - $m" -ForegroundColor Red }
        Write-Host ""
        Write-Host "  Please install the above and re-run this installer." -ForegroundColor Yellow
        Read-Host "  Press Enter to exit"
        exit 1
    }

    Write-Host "       All prerequisites met!" -ForegroundColor Green
    Write-Host ""
}

# --- Encoding Helpers (obfuscate demo secrets) --------------------------------

function Encode-Value {
    param([string]$plain)
    return [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($plain))
}

function Decode-Value {
    param([string]$encoded)
    return [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($encoded))
}

# --- Demo Configuration (pre-configured, encoded) -----------------------------
# These are the hackathon demo values. Encoded with Base64 for basic obfuscation.
# In production, use Azure Key Vault or similar.

$DEMO_CONFIG = @{
    JIRA_DOMAIN         = "aWl0YmhpbGFpLXRlYW0tYnlyZG9mNmkuYXRsYXNzaWFuLm5ldA=="
    JIRA_EMAIL          = "bGFoYXJpc3JlZWphdGFsbGFwYWthQGdtYWlsLmNvbQ=="
    JIRA_API_TOKEN      = "QVRBVFQzeEZmR0Ywb0VfZ3I0N2M1TEo4Y25iLWNWY1FmMEhhbnVqbXZhMS1kWG5QeFoxYlNCVUlaYVBEeU90ZHBRbXlFWnlYSWhEd3BPenEzRVFodlp1RGxSYzUycFFqLVppM215SEx3a0paczZOaEtfLS1kenlnNW82MmtrVlRDNUZ6TG1wal9QY005OXhiTjZDNFFTSWlpXzV6TXBiVG1zWi1fSXN6X0V2RzJZRmZoSWRCb3VRPTY0OEU5RjlC"
    JIRA_BOARD_ID       = "MQ=="
    SLACK_BOT_TOKEN     = "eG94Yi0xMTIxMTE5Njg5MTU5MS0xMTIyNjc0NjAzODE5NC02d3IzdlNHQ3U4dnRhOU0xOFlJOHBNdlA="
    SLACK_SIGNING_SECRET = "MjBmZmFkNDA2MGRiNjAzOGYwMWU2Y2Y3ZDk2OGUwZWE="
    AZURE_STORAGE_CONNECTION_STRING = "RGVmYXVsdEVuZHBvaW50c1Byb3RvY29sPWh0dHBzO0FjY291bnROYW1lPWVuZ21lbW9yeXN0b3JhZ2UwMDE7RW5kcG9pbnRTdWZmaXg9Y29yZS53aW5kb3dzLm5ldA=="
    AZURE_STORAGE_CONTAINER = "Y29tbWl0cw=="
    AZURE_SEARCH_ENDPOINT = "aHR0cHM6Ly9lbmdtZW1vcnktc2VhcmNoLnNlYXJjaC53aW5kb3dzLm5ldA=="
    AZURE_SEARCH_KEY    = "WUJBaHBQa3RSTlVBOTZYcjFMVjhWTDZRMkdQdWhaR1Q0T002VU5aUGdzQXpTZUR0b3ZyeA=="
    AZURE_SEARCH_INDEX  = "Y29tbWl0cw=="
    OPENROUTER_API_KEY  = "c2stb3ItdjEtNDRjMGU0NDljZTczNjBjYWIwM2IxNzZhZmFlMjBmYjkyMjg1ZDRmMDExODNmMjQxZDc5OTBkNTI2NzdhNzE5Zg=="
    OPENROUTER_MODEL    = "b3BlbnJvdXRlci9hdXRv"
    ENGMEMORY_REPO_URL  = "aHR0cHM6Ly9naXRodWIuY29tL0FpLWRlZW4vQUktRE9DUy5naXQ="
}

# --- Setup Mode Selection -----------------------------------------------------

function Get-SetupMode {
    Write-Step "2/6" "Choose setup mode:"
    Write-Host ""
    Write-Host "       [1] Demo Mode (Recommended)" -ForegroundColor Cyan
    Write-Host "           Uses pre-configured hackathon project (AI-DOCS)." -ForegroundColor DarkGray
    Write-Host "           Zero configuration needed - just run and explore." -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "       [2] Custom Project" -ForegroundColor Cyan
    Write-Host "           Configure your own Jira board, GitHub repo, and Slack." -ForegroundColor DarkGray
    Write-Host "           You will need your own API keys." -ForegroundColor DarkGray
    Write-Host ""

    do {
        $choice = Read-Host "       Enter choice (1 or 2)"
    } while ($choice -ne "1" -and $choice -ne "2")

    return [int]$choice
}

# --- Custom Project Configuration ---------------------------------------------

function Get-CustomConfig {
    Write-Host ""
    Write-Step "2/6" "Custom project configuration"
    Write-Host ""
    Write-Host "       Required:" -ForegroundColor Yellow

    $cfg = @{}

    # Git repo
    $cfg["ENGMEMORY_REPO_URL"] = Read-Host "       GitHub Repo URL (e.g. https://github.com/user/repo.git)"

    # Jira
    Write-Host ""
    Write-Host "       Jira Configuration:" -ForegroundColor Yellow
    $cfg["JIRA_DOMAIN"] = Read-Host "       Jira Domain (e.g. yourteam.atlassian.net)"
    $cfg["JIRA_EMAIL"] = Read-Host "       Jira Email"
    $cfg["JIRA_API_TOKEN"] = Read-Host "       Jira API Token (https://id.atlassian.com/manage-profile/security/api-tokens)"
    $cfg["JIRA_BOARD_ID"] = Read-Host "       Jira Board ID (usually 1)"

    # Slack (optional)
    Write-Host ""
    $setupSlack = Read-Host "       Set up Slack integration? (y/n)"
    if ($setupSlack -eq "y") {
        $cfg["SLACK_BOT_TOKEN"] = Read-Host "       Slack Bot Token (xoxb-...)"
        $cfg["SLACK_SIGNING_SECRET"] = Read-Host "       Slack Signing Secret"
    }

    # Azure (optional)
    Write-Host ""
    $setupAzure = Read-Host "       Set up your own Azure storage? (y/n, default: use demo)"
    if ($setupAzure -eq "y") {
        $cfg["AZURE_STORAGE_CONNECTION_STRING"] = Read-Host "       Azure Storage Connection String"
        $cfg["AZURE_STORAGE_CONTAINER"] = Read-Host "       Azure Storage Container (default: commits)"
        if (-not $cfg["AZURE_STORAGE_CONTAINER"]) { $cfg["AZURE_STORAGE_CONTAINER"] = "commits" }
        $cfg["AZURE_SEARCH_ENDPOINT"] = Read-Host "       Azure Search Endpoint"
        $cfg["AZURE_SEARCH_KEY"] = Read-Host "       Azure Search Admin Key"
        $cfg["AZURE_SEARCH_INDEX"] = Read-Host "       Azure Search Index (default: commits)"
        if (-not $cfg["AZURE_SEARCH_INDEX"]) { $cfg["AZURE_SEARCH_INDEX"] = "commits" }
    }

    # LLM (optional)
    Write-Host ""
    $setupLLM = Read-Host "       Set up your own LLM API key? (y/n, default: use demo)"
    if ($setupLLM -eq "y") {
        $cfg["OPENROUTER_API_KEY"] = Read-Host "       OpenRouter API Key (https://openrouter.ai/keys)"
        $cfg["OPENROUTER_MODEL"] = Read-Host "       Model (default: openrouter/auto)"
        if (-not $cfg["OPENROUTER_MODEL"]) { $cfg["OPENROUTER_MODEL"] = "openrouter/auto" }
    }

    return $cfg
}

# --- Write .env File ----------------------------------------------------------

function Write-EnvFile {
    param([int]$mode, $customCfg)

    Write-Step "3/6" "Creating configuration..."

    $scriptDir = $PSScriptRoot
    if (-not $scriptDir) { $scriptDir = Split-Path -Parent $MyInvocation.ScriptName }
    if (-not $scriptDir) { $scriptDir = (Get-Location).Path }
    $envPath = Join-Path $scriptDir ".env"

    # Don't overwrite existing .env
    if (Test-Path $envPath) {
        $overwrite = Read-Host "       .env already exists. Overwrite? (y/n)"
        if ($overwrite -ne "y") {
            Write-Host "       Keeping existing .env" -ForegroundColor DarkGray
            return
        }
    }

    $repoPath = $scriptDir
    $projectPath = Join-Path $scriptDir "project"

    # Auto-create the project folder
    if (-not (Test-Path $projectPath)) {
        New-Item -ItemType Directory -Path $projectPath -Force | Out-Null
    }

    if ($mode -eq 1) {
        # Demo mode - decode all values
        $d_jiraDomain = Decode-Value $DEMO_CONFIG.JIRA_DOMAIN
        $d_jiraEmail = Decode-Value $DEMO_CONFIG.JIRA_EMAIL
        $d_jiraToken = Decode-Value $DEMO_CONFIG.JIRA_API_TOKEN
        $d_jiraBoard = Decode-Value $DEMO_CONFIG.JIRA_BOARD_ID
        $d_slackBot = Decode-Value $DEMO_CONFIG.SLACK_BOT_TOKEN
        $d_slackSecret = Decode-Value $DEMO_CONFIG.SLACK_SIGNING_SECRET
        $d_azureConn = Decode-Value $DEMO_CONFIG.AZURE_STORAGE_CONNECTION_STRING
        $d_azureContainer = Decode-Value $DEMO_CONFIG.AZURE_STORAGE_CONTAINER
        $d_searchEp = Decode-Value $DEMO_CONFIG.AZURE_SEARCH_ENDPOINT
        $d_searchKey = Decode-Value $DEMO_CONFIG.AZURE_SEARCH_KEY
        $d_searchIdx = Decode-Value $DEMO_CONFIG.AZURE_SEARCH_INDEX
        $d_llmKey = Decode-Value $DEMO_CONFIG.OPENROUTER_API_KEY
        $d_llmModel = Decode-Value $DEMO_CONFIG.OPENROUTER_MODEL
        $d_repoUrl = Decode-Value $DEMO_CONFIG.ENGMEMORY_REPO_URL

        $lines = @(
            "# EngMemory / Flux - Configuration (Demo Mode)"
            "# Auto-generated by installer - Microsoft Build AI Hackathon 2026"
            ""
            "# --- Jira Cloud ---"
            "JIRA_DOMAIN=$d_jiraDomain"
            "JIRA_EMAIL=$d_jiraEmail"
            "JIRA_API_TOKEN=$d_jiraToken"
            "JIRA_BOARD_ID=$d_jiraBoard"
            ""
            "# --- Slack ---"
            "SLACK_BOT_TOKEN=$d_slackBot"
            "SLACK_SIGNING_SECRET=$d_slackSecret"
            ""
            "# --- Azure Storage ---"
            "AZURE_STORAGE_CONNECTION_STRING=$d_azureConn"
            "AZURE_STORAGE_CONTAINER=$d_azureContainer"
            ""
            "# --- Azure AI Search ---"
            "AZURE_SEARCH_ENDPOINT=$d_searchEp"
            "AZURE_SEARCH_KEY=$d_searchKey"
            "AZURE_SEARCH_INDEX=$d_searchIdx"
            ""
            "# --- LLM ---"
            "OPENROUTER_API_KEY=$d_llmKey"
            "OPENROUTER_MODEL=$d_llmModel"
            ""
            "# --- Repo ---"
            "ENGMEMORY_REPO_PATH=$repoPath"
            "ENGMEMORY_REPO_URL=$d_repoUrl"
            "ENGMEMORY_PROJECT_ROOT=$projectPath"
        )
    } else {
        # Custom mode - use provided values, fallback to demo for unset
        $jiraDomain = $customCfg["JIRA_DOMAIN"]
        if (-not $jiraDomain) { $jiraDomain = Decode-Value $DEMO_CONFIG.JIRA_DOMAIN }

        $jiraEmail = $customCfg["JIRA_EMAIL"]
        if (-not $jiraEmail) { $jiraEmail = Decode-Value $DEMO_CONFIG.JIRA_EMAIL }

        $jiraToken = $customCfg["JIRA_API_TOKEN"]
        if (-not $jiraToken) { $jiraToken = Decode-Value $DEMO_CONFIG.JIRA_API_TOKEN }

        $jiraBoard = $customCfg["JIRA_BOARD_ID"]
        if (-not $jiraBoard) { $jiraBoard = "1" }

        $slackBot = $customCfg["SLACK_BOT_TOKEN"]
        if (-not $slackBot) { $slackBot = Decode-Value $DEMO_CONFIG.SLACK_BOT_TOKEN }

        $slackSecret = $customCfg["SLACK_SIGNING_SECRET"]
        if (-not $slackSecret) { $slackSecret = Decode-Value $DEMO_CONFIG.SLACK_SIGNING_SECRET }

        $azureConn = $customCfg["AZURE_STORAGE_CONNECTION_STRING"]
        if (-not $azureConn) { $azureConn = Decode-Value $DEMO_CONFIG.AZURE_STORAGE_CONNECTION_STRING }

        $azureContainer = $customCfg["AZURE_STORAGE_CONTAINER"]
        if (-not $azureContainer) { $azureContainer = "commits" }

        $azureSearchEp = $customCfg["AZURE_SEARCH_ENDPOINT"]
        if (-not $azureSearchEp) { $azureSearchEp = Decode-Value $DEMO_CONFIG.AZURE_SEARCH_ENDPOINT }

        $azureSearchKey = $customCfg["AZURE_SEARCH_KEY"]
        if (-not $azureSearchKey) { $azureSearchKey = Decode-Value $DEMO_CONFIG.AZURE_SEARCH_KEY }

        $azureSearchIdx = $customCfg["AZURE_SEARCH_INDEX"]
        if (-not $azureSearchIdx) { $azureSearchIdx = "commits" }

        $llmKey = $customCfg["OPENROUTER_API_KEY"]
        if (-not $llmKey) { $llmKey = Decode-Value $DEMO_CONFIG.OPENROUTER_API_KEY }

        $llmModel = $customCfg["OPENROUTER_MODEL"]
        if (-not $llmModel) { $llmModel = "openrouter/auto" }

        $repoUrl = $customCfg["ENGMEMORY_REPO_URL"]
        if (-not $repoUrl) { $repoUrl = Decode-Value $DEMO_CONFIG.ENGMEMORY_REPO_URL }

        $lines = @(
            "# EngMemory / Flux - Configuration (Custom Project)"
            "# Auto-generated by installer - Microsoft Build AI Hackathon 2026"
            ""
            "# --- Jira Cloud ---"
            "JIRA_DOMAIN=$jiraDomain"
            "JIRA_EMAIL=$jiraEmail"
            "JIRA_API_TOKEN=$jiraToken"
            "JIRA_BOARD_ID=$jiraBoard"
            ""
            "# --- Slack ---"
            "SLACK_BOT_TOKEN=$slackBot"
            "SLACK_SIGNING_SECRET=$slackSecret"
            ""
            "# --- Azure Storage ---"
            "AZURE_STORAGE_CONNECTION_STRING=$azureConn"
            "AZURE_STORAGE_CONTAINER=$azureContainer"
            ""
            "# --- Azure AI Search ---"
            "AZURE_SEARCH_ENDPOINT=$azureSearchEp"
            "AZURE_SEARCH_KEY=$azureSearchKey"
            "AZURE_SEARCH_INDEX=$azureSearchIdx"
            ""
            "# --- LLM ---"
            "OPENROUTER_API_KEY=$llmKey"
            "OPENROUTER_MODEL=$llmModel"
            ""
            "# --- Repo ---"
            "ENGMEMORY_REPO_PATH=$repoPath"
            "ENGMEMORY_REPO_URL=$repoUrl"
            "ENGMEMORY_PROJECT_ROOT=$projectPath"
        )
    }

    $content = $lines -join "`r`n"
    Set-Content -Path $envPath -Value $content -Encoding UTF8
    Write-Host "       Configuration saved to .env" -ForegroundColor Green
}

# --- Install Dependencies -----------------------------------------------------

function Install-Dependencies {
    Write-Step "4/6" "Installing Python dependencies..."

    $scriptDir = $PSScriptRoot
    if (-not $scriptDir) { $scriptDir = (Get-Location).Path }

    Push-Location $scriptDir
    $ErrorActionPreference = "Continue"
    $output = pip install -e . 2>&1 | Out-String
    if ($LASTEXITCODE -eq 0) {
        Write-Host "       Python packages installed" -ForegroundColor Green
    } else {
        Write-Warn "pip install failed (exit code $LASTEXITCODE) - trying with --user flag"
        $output = pip install --user -e . 2>&1 | Out-String
        if ($LASTEXITCODE -eq 0) {
            Write-Host "       Python packages installed (user mode)" -ForegroundColor Green
        } else {
            Write-Err "pip install failed. Check errors above."
        }
    }
    $ErrorActionPreference = "Stop"
    Pop-Location

    Write-Step "5/6" "Installing Dashboard dependencies..."
    $dashDir = Join-Path $scriptDir "dashboard"
    if (Test-Path $dashDir) {
        Push-Location $dashDir
        $ErrorActionPreference = "Continue"
        $output = npm install 2>&1 | Out-String
        $ErrorActionPreference = "Stop"
        Write-Host "       Dashboard packages installed" -ForegroundColor Green
        Pop-Location
    } else {
        Write-Warn "Dashboard directory not found at $dashDir"
    }
}

# --- Start Services -----------------------------------------------------------

function Start-Services {
    Write-Step "6/6" "Starting EngMemory services..."

    $scriptDir = $PSScriptRoot
    if (-not $scriptDir) { $scriptDir = (Get-Location).Path }

    # Start API server in background
    Write-Host "       Starting API server on port 5051..." -ForegroundColor DarkGray
    $apiJob = Start-Process -FilePath "python" `
        -ArgumentList "-m uvicorn engmemory.api.server:app --host 0.0.0.0 --port 5051" `
        -WorkingDirectory $scriptDir `
        -WindowStyle Minimized `
        -PassThru

    # Start Dashboard in background
    $dashDir = Join-Path $scriptDir "dashboard"
    $dashJob = $null
    if (Test-Path $dashDir) {
        Write-Host "       Starting Dashboard on port 5174..." -ForegroundColor DarkGray
        $dashJob = Start-Process -FilePath "cmd" `
            -ArgumentList "/c npm run dev" `
            -WorkingDirectory $dashDir `
            -WindowStyle Minimized `
            -PassThru
    }

    # Wait a moment for servers to start
    Write-Host "       Waiting for services to start..." -ForegroundColor DarkGray
    Start-Sleep -Seconds 5

    # Open browser
    Write-Host ""
    Write-Host "  =============================================================" -ForegroundColor Green
    Write-Host "  |  EngMemory is running!                                    |" -ForegroundColor Green
    Write-Host "  |                                                           |" -ForegroundColor Green
    Write-Host "  |  Dashboard:  http://localhost:5174                        |" -ForegroundColor Green
    Write-Host "  |  API:        http://localhost:5051/docs                   |" -ForegroundColor Green
    Write-Host "  =============================================================" -ForegroundColor Green
    Write-Host ""

    Start-Process "http://localhost:5174"

    Write-Host "  The dashboard has been opened in your browser." -ForegroundColor Cyan
    Write-Host "  Press Ctrl+C or close this window to stop all services." -ForegroundColor DarkGray
    Write-Host ""

    # Keep script running - cleanup on exit
    try {
        Wait-Process -Id $apiJob.Id
    } catch {
        # User pressed Ctrl+C
    } finally {
        Write-Host "  Shutting down services..." -ForegroundColor Yellow
        if ($apiJob -and (-not $apiJob.HasExited)) {
            Stop-Process -Id $apiJob.Id -Force -ErrorAction SilentlyContinue
        }
        if ($dashJob -and (-not $dashJob.HasExited)) {
            Stop-Process -Id $dashJob.Id -Force -ErrorAction SilentlyContinue
        }
        Write-Host "  Done. Goodbye!" -ForegroundColor Green
    }
}

# --- Main ---------------------------------------------------------------------

Write-Banner
Test-Prerequisites

$mode = Get-SetupMode
$customCfg = $null
if ($mode -eq 2) {
    $customCfg = Get-CustomConfig
}

Write-EnvFile -mode $mode -customCfg $customCfg
Install-Dependencies
Start-Services
