import * as vscode from 'vscode';
import { runEngMemory } from './runner';

export class AskWebviewProvider implements vscode.WebviewViewProvider {
    private _view?: vscode.WebviewView;
    private _messages: Array<{ role: string; content: string }> = [];

    constructor(
        private readonly _extensionUri: vscode.Uri,
        private readonly _workspaceRoot: string
    ) {}

    resolveWebviewView(webviewView: vscode.WebviewView) {
        this._view = webviewView;

        webviewView.webview.options = {
            enableScripts: true,
        };

        webviewView.webview.html = this._getHtml();

        webviewView.webview.onDidReceiveMessage(async (message) => {
            if (message.type === 'ask') {
                this._messages.push({ role: 'user', content: message.question });
                this._updateChat();

                const answer = await runEngMemory(this._workspaceRoot, ['ask', message.question]);
                this._messages.push({ role: 'assistant', content: answer });
                this._updateChat();
            }
        });
    }

    showAnswer(question: string, answer: string) {
        this._messages.push({ role: 'user', content: question });
        this._messages.push({ role: 'assistant', content: answer });
        this._updateChat();
        this._view?.show();
    }

    private _updateChat() {
        this._view?.webview.postMessage({
            type: 'messages',
            messages: this._messages
        });
    }

    private _getHtml(): string {
        return `<!DOCTYPE html>
<html>
<head>
    <style>
        body { font-family: var(--vscode-font-family); padding: 0; margin: 0; color: var(--vscode-foreground); }
        .container { display: flex; flex-direction: column; height: 100vh; }
        .messages { flex: 1; overflow-y: auto; padding: 12px; }
        .message { margin-bottom: 12px; padding: 8px 12px; border-radius: 8px; font-size: 13px; line-height: 1.5; white-space: pre-wrap; }
        .user { background: var(--vscode-button-background); color: var(--vscode-button-foreground); margin-left: 20px; }
        .assistant { background: var(--vscode-editor-inactiveSelectionBackground); margin-right: 20px; }
        .input-area { padding: 8px; border-top: 1px solid var(--vscode-panel-border); display: flex; gap: 6px; }
        input { flex: 1; padding: 8px; border: 1px solid var(--vscode-input-border); background: var(--vscode-input-background); color: var(--vscode-input-foreground); border-radius: 4px; font-size: 13px; }
        button { padding: 8px 12px; background: var(--vscode-button-background); color: var(--vscode-button-foreground); border: none; border-radius: 4px; cursor: pointer; font-size: 13px; }
        button:hover { background: var(--vscode-button-hoverBackground); }
        .empty { text-align: center; padding: 40px 20px; opacity: 0.7; font-size: 13px; }
        .label { font-size: 11px; opacity: 0.6; margin-bottom: 4px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="messages" id="messages">
            <div class="empty">Ask questions about your commit history.<br><br>Examples:<br>• "How was the auth bug fixed?"<br>• "What changes were made to the API?"<br>• "Who worked on the database?"</div>
        </div>
        <div class="input-area">
            <input type="text" id="input" placeholder="Ask about commits..." />
            <button id="send">Ask</button>
        </div>
    </div>
    <script>
        const vscode = acquireVsCodeApi();
        const messagesEl = document.getElementById('messages');
        const inputEl = document.getElementById('input');
        const sendBtn = document.getElementById('send');

        sendBtn.addEventListener('click', send);
        inputEl.addEventListener('keydown', (e) => { if (e.key === 'Enter') send(); });

        function send() {
            const q = inputEl.value.trim();
            if (!q) return;
            inputEl.value = '';
            vscode.postMessage({ type: 'ask', question: q });
        }

        window.addEventListener('message', (event) => {
            const { type, messages } = event.data;
            if (type === 'messages') {
                messagesEl.innerHTML = messages.map(m =>
                    '<div class="message ' + m.role + '">' +
                    '<div class="label">' + (m.role === 'user' ? '🧑 You' : '🧠 EngMemory') + '</div>' +
                    escapeHtml(m.content) +
                    '</div>'
                ).join('');
                messagesEl.scrollTop = messagesEl.scrollHeight;
            }
        });

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
    </script>
</body>
</html>`;
    }
}
