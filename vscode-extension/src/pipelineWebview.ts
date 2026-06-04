import * as vscode from 'vscode';
import * as http from 'http';

const API_BASE = 'http://localhost:5051';

interface PipelineMessage {
    role: string;
    content: string;
    timestamp: string;
    stage: string;
    query_to: string;
}

interface PipelineStatus {
    ticket_key: string;
    stage: string;
    iteration: number;
    reviewer_verdict: string;
    tester_verdict: string;
    pr_url: string;
    messages: number;
}

function apiGet(path: string): Promise<any> {
    return new Promise((resolve, reject) => {
        http.get(`${API_BASE}${path}`, (res) => {
            let data = '';
            res.on('data', chunk => data += chunk);
            res.on('end', () => {
                try {
                    resolve(JSON.parse(data));
                } catch {
                    resolve({ error: data });
                }
            });
        }).on('error', reject);
    });
}

function apiPost(path: string, body: any): Promise<any> {
    return new Promise((resolve, reject) => {
        const postData = JSON.stringify(body);
        const url = new URL(`${API_BASE}${path}`);
        const options = {
            hostname: url.hostname,
            port: url.port,
            path: url.pathname,
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Content-Length': Buffer.byteLength(postData),
            },
        };

        const req = http.request(options, (res) => {
            let data = '';
            res.on('data', chunk => data += chunk);
            res.on('end', () => {
                try {
                    resolve(JSON.parse(data));
                } catch {
                    resolve({ error: data });
                }
            });
        });
        req.on('error', reject);
        req.write(postData);
        req.end();
    });
}

export class PipelineWebviewProvider implements vscode.WebviewViewProvider {
    private _view?: vscode.WebviewView;
    private _ticketKey: string = '';
    private _messages: PipelineMessage[] = [];
    private _status: PipelineStatus | null = null;
    private _pollInterval: NodeJS.Timeout | null = null;

    constructor(
        private readonly _extensionUri: vscode.Uri,
        private readonly _workspaceRoot: string
    ) {}

    resolveWebviewView(webviewView: vscode.WebviewView) {
        this._view = webviewView;

        webviewView.webview.options = { enableScripts: true };
        webviewView.webview.html = this._getHtml();

        webviewView.webview.onDidReceiveMessage(async (message) => {
            switch (message.type) {
                case 'start-pipeline':
                    await this._startPipeline(message.ticketKey);
                    break;
                case 'send-instruction':
                    await this._sendUserInstruction(message.instruction);
                    break;
                case 'refresh':
                    await this._refreshStatus();
                    break;
                case 'trigger-agent':
                    await this._triggerAgent(message.agent);
                    break;
            }
        });

        // Auto-detect ticket from .ticket-context.md
        this._detectTicket();

        // Start polling for updates
        this._startPolling();
    }

    private async _detectTicket() {
        const fs = require('fs');
        const path = require('path');
        const contextFile = path.join(this._workspaceRoot, '.ticket-context.md');
        if (fs.existsSync(contextFile)) {
            const content = fs.readFileSync(contextFile, 'utf-8');
            const match = content.match(/\[([A-Z]+-\d+)\]/);
            if (match) {
                this._ticketKey = match[1];
                await this._refreshStatus();
            }
        }
    }

    private _startPolling() {
        this._pollInterval = setInterval(async () => {
            if (this._ticketKey) {
                await this._refreshStatus();
            }
        }, 10000); // Poll every 10 seconds
    }

    private async _startPipeline(ticketKey: string) {
        this._ticketKey = ticketKey;
        try {
            await apiPost(`/api/pipeline/${ticketKey}/start`, {});
            await this._refreshStatus();
            vscode.window.showInformationMessage(
                `🚀 Pipeline started for ${ticketKey}`
            );
        } catch (err: any) {
            vscode.window.showErrorMessage(`Failed to start pipeline: ${err.message}`);
        }
    }

    private async _refreshStatus() {
        if (!this._ticketKey) { return; }
        try {
            this._status = await apiGet(`/api/pipeline/${this._ticketKey}/status`);
            const convResp = await apiGet(`/api/pipeline/${this._ticketKey}/conversation`);
            this._messages = convResp.messages || [];
            this._updateWebview();
        } catch {
            // API not running — silently ignore
        }
    }

    private async _sendUserInstruction(instruction: string) {
        if (!this._ticketKey) { return; }
        try {
            const result = await apiPost(
                `/api/pipeline/${this._ticketKey}/user-instruction`,
                { instruction }
            );
            await this._refreshStatus();

            if (result.next_stage === 'developer') {
                // Trigger developer agent
                await this._triggerAgent('developer');
            }
        } catch (err: any) {
            vscode.window.showErrorMessage(`Failed: ${err.message}`);
        }
    }

    private async _triggerAgent(agent: string) {
        if (!this._ticketKey) { return; }

        let query = '';
        switch (agent) {
            case 'developer':
                query = `Read .ticket-context.md and call GET http://localhost:5051/api/pipeline/${this._ticketKey}/developer-prompt to get your instructions. Implement the changes.`;
                break;
            case 'reviewer':
                query = `Call GET http://localhost:5051/api/pipeline/${this._ticketKey}/reviewer-prompt to get your review instructions. Review the changes.`;
                break;
            case 'tester':
                query = `Call GET http://localhost:5051/api/pipeline/${this._ticketKey}/tester-prompt to get your test instructions. Test the changes.`;
                break;
        }

        try {
            await vscode.commands.executeCommand(
                'workbench.action.chat.open',
                { query: `@${agent} ${query}`, isPartialQuery: false }
            );
        } catch {
            vscode.window.showInformationMessage(
                `Switch to @${agent} mode and paste:\n${query}`
            );
        }
    }

    private _updateWebview() {
        this._view?.webview.postMessage({
            type: 'update',
            status: this._status,
            messages: this._messages,
            ticketKey: this._ticketKey,
        });
    }

    dispose() {
        if (this._pollInterval) {
            clearInterval(this._pollInterval);
        }
    }

    private _getHtml(): string {
        return `<!DOCTYPE html>
<html>
<head>
    <style>
        body { font-family: var(--vscode-font-family); padding: 0; margin: 0; color: var(--vscode-foreground); font-size: 12px; }
        .container { display: flex; flex-direction: column; height: 100vh; }
        .header { padding: 8px 12px; border-bottom: 1px solid var(--vscode-panel-border); }
        .status-bar { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
        .stage-badge { padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: bold; }
        .stage-developer { background: #2ea043; color: white; }
        .stage-review { background: #bf8700; color: white; }
        .stage-testing { background: #1f6feb; color: white; }
        .stage-pr_creation { background: #8957e5; color: white; }
        .stage-waiting_for_merge { background: #da3633; color: white; }
        .stage-done { background: #238636; color: white; }
        .messages { flex: 1; overflow-y: auto; padding: 8px 12px; }
        .message { margin-bottom: 8px; padding: 6px 10px; border-radius: 6px; font-size: 12px; line-height: 1.4; }
        .msg-orchestrator { background: var(--vscode-editor-inactiveSelectionBackground); border-left: 3px solid #8957e5; }
        .msg-developer { background: var(--vscode-editor-inactiveSelectionBackground); border-left: 3px solid #2ea043; }
        .msg-reviewer { background: var(--vscode-editor-inactiveSelectionBackground); border-left: 3px solid #bf8700; }
        .msg-tester { background: var(--vscode-editor-inactiveSelectionBackground); border-left: 3px solid #1f6feb; }
        .msg-user { background: var(--vscode-button-background); color: var(--vscode-button-foreground); }
        .msg-role { font-size: 10px; opacity: 0.7; margin-bottom: 2px; }
        .input-area { padding: 8px; border-top: 1px solid var(--vscode-panel-border); }
        .input-row { display: flex; gap: 4px; margin-bottom: 6px; }
        input { flex: 1; padding: 6px; border: 1px solid var(--vscode-input-border); background: var(--vscode-input-background); color: var(--vscode-input-foreground); border-radius: 4px; font-size: 12px; }
        button { padding: 6px 10px; background: var(--vscode-button-background); color: var(--vscode-button-foreground); border: none; border-radius: 4px; cursor: pointer; font-size: 11px; }
        button:hover { background: var(--vscode-button-hoverBackground); }
        .btn-row { display: flex; gap: 4px; flex-wrap: wrap; }
        .btn-small { padding: 3px 8px; font-size: 10px; }
        .empty { text-align: center; padding: 30px 16px; opacity: 0.7; }
        .iteration { font-size: 10px; opacity: 0.6; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="status-bar">
                <strong id="ticket">No pipeline</strong>
                <span class="stage-badge" id="stage">idle</span>
                <span class="iteration" id="iteration"></span>
            </div>
        </div>
        <div class="messages" id="messages">
            <div class="empty">
                Activate a ticket from the Flux dashboard to start.<br>
                <small>Pipeline: developer → reviewer → tester → PR (all automated)</small>
            </div>
        </div>
    </div>
    <script>
        const vscode = acquireVsCodeApi();
        const messagesEl = document.getElementById('messages');

        function refresh() {
            vscode.postMessage({ type: 'refresh' });
        }

        window.addEventListener('message', (event) => {
            const { type, status, messages, ticketKey } = event.data;
            if (type === 'update') {
                // Update header
                document.getElementById('ticket').textContent = ticketKey || 'No pipeline';
                const stageEl = document.getElementById('stage');
                stageEl.textContent = status?.stage || 'idle';
                stageEl.className = 'stage-badge stage-' + (status?.stage || 'idle');
                document.getElementById('iteration').textContent = 
                    status?.iteration > 0 ? 'iter ' + status.iteration : '';

                // Update messages
                if (messages && messages.length > 0) {
                    messagesEl.innerHTML = messages.map(m => {
                        const roleIcons = {
                            orchestrator: '🧠',
                            developer: '👨‍💻',
                            reviewer: '👁',
                            tester: '🧪',
                            user: '🧑'
                        };
                        const icon = roleIcons[m.role] || '💬';
                        const time = m.timestamp ? new Date(m.timestamp).toLocaleTimeString() : '';
                        return '<div class="message msg-' + m.role + '">' +
                            '<div class="msg-role">' + icon + ' ' + m.role + ' · ' + time + '</div>' +
                            escapeHtml(m.content.substring(0, 500)) +
                            (m.content.length > 500 ? '...' : '') +
                            '</div>';
                    }).join('');
                    messagesEl.scrollTop = messagesEl.scrollHeight;
                }
            }
        });

        function escapeHtml(str) {
            return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        }
    </script>
</body>
</html>`;
    }
}
