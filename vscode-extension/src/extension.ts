import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import { CommitTreeProvider } from './commitTree';
import { AskWebviewProvider } from './askWebview';
import { PipelineWebviewProvider } from './pipelineWebview';
import { runEngMemory } from './runner';

export function activate(context: vscode.ExtensionContext) {
    console.log('EngMemory extension activated');

    const workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
    if (!workspaceRoot) {
        return;
    }

    // Auto-trigger developer agent if .ticket-context.md exists
    autoTriggerDeveloperAgent(workspaceRoot, context);

    // Start polling for server triggers (auto-invokes agents when pipeline advances)
    startTriggerWatcher(context);

    // Register commit tree view
    const commitProvider = new CommitTreeProvider(workspaceRoot);
    vscode.window.registerTreeDataProvider('engmemory.commits', commitProvider);

    // Register ask webview
    const askProvider = new AskWebviewProvider(context.extensionUri, workspaceRoot);
    context.subscriptions.push(
        vscode.window.registerWebviewViewProvider('engmemory.ask', askProvider)
    );

    // Register pipeline webview (inter-agent conversation view)
    const pipelineProvider = new PipelineWebviewProvider(context.extensionUri, workspaceRoot);
    context.subscriptions.push(
        vscode.window.registerWebviewViewProvider('engmemory.pipeline', pipelineProvider)
    );

    // Register commands
    context.subscriptions.push(
        vscode.commands.registerCommand('engmemory.ask', async () => {
            const question = await vscode.window.showInputBox({
                prompt: 'Ask about your commit history',
                placeHolder: 'How was the login bug fixed?'
            });
            if (question) {
                const answer = await runEngMemory(workspaceRoot, ['ask', question]);
                askProvider.showAnswer(question, answer);
            }
        }),

        vscode.commands.registerCommand('engmemory.refresh', () => {
            commitProvider.refresh();
        }),

        vscode.commands.registerCommand('engmemory.init', async () => {
            const result = await runEngMemory(workspaceRoot, ['init']);
            vscode.window.showInformationMessage(result || 'EngMemory hook installed!');
        }),

        vscode.commands.registerCommand('engmemory.index', async () => {
            vscode.window.withProgress(
                { location: vscode.ProgressLocation.Notification, title: 'EngMemory: Indexing commits...' },
                async () => {
                    const result = await runEngMemory(workspaceRoot, ['index', '--limit', '20', '--analyze']);
                    vscode.window.showInformationMessage(result || 'Indexing complete!');
                    commitProvider.refresh();
                }
            );
        }),

        vscode.commands.registerCommand('engmemory.status', async () => {
            const result = await runEngMemory(workspaceRoot, ['status']);
            vscode.window.showInformationMessage(`EngMemory: ${result}`);
        })
    );

    // Auto-refresh on file save in .ai_memory
    const watcher = vscode.workspace.createFileSystemWatcher('**/.ai_memory/commits/*.json');
    watcher.onDidCreate(() => commitProvider.refresh());
    context.subscriptions.push(watcher);

    // Register agent trigger commands
    registerAgentTriggerCommand(context, workspaceRoot);
}

export function deactivate() {}


/**
 * Auto-trigger the developer agent when a workspace with .ticket-context.md is opened.
 * This is the key automation: when a ticket workspace opens, the developer starts coding automatically.
 */
async function autoTriggerDeveloperAgent(workspaceRoot: string, context: vscode.ExtensionContext) {
    const contextFile = path.join(workspaceRoot, '.ticket-context.md');
    const triggerFlagFile = path.join(workspaceRoot, '.agent-triggered');

    // Check if .ticket-context.md exists
    if (!fs.existsSync(contextFile)) {
        return;
    }

    // Check if we already triggered (avoid re-triggering on reload)
    if (fs.existsSync(triggerFlagFile)) {
        return;
    }

    // Read the ticket context to get the ticket key
    const contextContent = fs.readFileSync(contextFile, 'utf-8');
    const ticketMatch = contextContent.match(/([A-Z]+-\d+)/);
    const ticketKey = ticketMatch ? ticketMatch[1] : 'ticket';

    // Mark as triggered FIRST (prevents double-trigger on fast reloads)
    fs.writeFileSync(triggerFlagFile, new Date().toISOString(), 'utf-8');

    // Wait for VS Code + Copilot Chat to fully initialize (8 seconds is safer)
    await new Promise(resolve => setTimeout(resolve, 8000));

    // Show persistent notification
    vscode.window.withProgress(
        { location: vscode.ProgressLocation.Notification, title: `EngMemory: Starting developer agent for ${ticketKey}...`, cancellable: false },
        async (progress) => {
            progress.report({ increment: 30, message: 'Opening chat...' });

            const chatQuery = `@developer You are working on ${ticketKey}. Call GET http://localhost:5051/api/pipeline/${ticketKey}/developer-prompt to get your instructions. Context update: ${contextContent.slice(0, 300)}. Implement the required changes. When done, call POST http://localhost:5051/api/pipeline/${ticketKey}/developer-done with a summary.`;

            // Retry up to 3 times with increasing delays
            for (let attempt = 1; attempt <= 3; attempt++) {
                try {
                    progress.report({ increment: 20, message: `Attempt ${attempt}...` });

                    // Open chat panel first
                    await vscode.commands.executeCommand('workbench.action.chat.open');
                    await new Promise(resolve => setTimeout(resolve, 2000));

                    // Send the query with auto-submit
                    await vscode.commands.executeCommand(
                        'workbench.action.chat.open',
                        { query: chatQuery, isPartialQuery: false }
                    );

                    progress.report({ increment: 50, message: 'Agent started!' });
                    return; // Success
                } catch (e) {
                    if (attempt < 3) {
                        await new Promise(resolve => setTimeout(resolve, 3000));
                    }
                }
            }

            // All attempts failed — show manual instruction
            vscode.window.showWarningMessage(
                `EngMemory: Could not auto-start agent. Open Chat and type: @developer read .ticket-context.md and implement the changes for ${ticketKey}`,
                'Open Chat'
            ).then(choice => {
                if (choice === 'Open Chat') {
                    vscode.commands.executeCommand('workbench.action.chat.open');
                }
            });
        }
    );
}


/**
 * Command to manually re-trigger the developer agent
 */
function registerAgentTriggerCommand(context: vscode.ExtensionContext, workspaceRoot: string) {
    context.subscriptions.push(
        vscode.commands.registerCommand('engmemory.triggerDeveloper', async () => {
            const contextFile = path.join(workspaceRoot, '.ticket-context.md');
            if (!fs.existsSync(contextFile)) {
                vscode.window.showWarningMessage('No .ticket-context.md found in workspace.');
                return;
            }

            // Remove trigger flag to allow re-trigger
            const flagFile = path.join(workspaceRoot, '.agent-triggered');
            if (fs.existsSync(flagFile)) {
                fs.unlinkSync(flagFile);
            }

            await autoTriggerDeveloperAgent(workspaceRoot, context);
        }),

        vscode.commands.registerCommand('engmemory.triggerReviewer', async () => {
            try {
                await vscode.commands.executeCommand(
                    'workbench.action.chat.newChat',
                    { agentMode: 'reviewer' }
                );
                await new Promise(resolve => setTimeout(resolve, 1000));
                await vscode.commands.executeCommand(
                    'workbench.action.chat.open',
                    {
                        query: `Review the code changes in this workspace. Read .ticket-context.md to understand requirements, then run git diff master to see changes. Provide your verdict: APPROVED, CHANGES_REQUESTED, or QUESTIONS.`,
                        isPartialQuery: false
                    }
                );
            } catch {
                try {
                    await vscode.commands.executeCommand(
                        'workbench.action.chat.open',
                        { mode: 'reviewer', query: `Review the code changes. Read .ticket-context.md then run git diff master. Provide verdict.`, isPartialQuery: false }
                    );
                } catch {
                    vscode.window.showInformationMessage(
                        'Select "reviewer" from the agent dropdown and ask it to review.'
                    );
                }
            }
        }),

        vscode.commands.registerCommand('engmemory.triggerTester', async () => {
            try {
                await vscode.commands.executeCommand(
                    'workbench.action.chat.newChat',
                    { agentMode: 'tester' }
                );
                await new Promise(resolve => setTimeout(resolve, 1000));
                await vscode.commands.executeCommand(
                    'workbench.action.chat.open',
                    {
                        query: `Test the implementation in this workspace. Read .ticket-context.md to understand what to test. Run existing tests, write new ones, verify the implementation. Provide verdict: PASSED, FAILED, or PARTIAL.`,
                        isPartialQuery: false
                    }
                );
            } catch {
                try {
                    await vscode.commands.executeCommand(
                        'workbench.action.chat.open',
                        { mode: 'tester', query: `Test the implementation. Read .ticket-context.md then run tests. Provide verdict.`, isPartialQuery: false }
                    );
                } catch {
                    vscode.window.showInformationMessage(
                        'Select "tester" from the agent dropdown and ask it to test.'
                    );
                }
            }
        })
    );
}


/**
 * Polls the server for pending agent triggers and auto-invokes agents.
 * This is what makes the pipeline fully autonomous — no button presses needed.
 */
function startTriggerWatcher(context: vscode.ExtensionContext) {
    const http = require('http');
    const path = require('path');
    let lastTriggerTimestamp = '';

    // Get this window's workspace root for matching
    const thisWorkspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || '';

    const interval = setInterval(async () => {
        try {
            // Poll for pending triggers
            const data: any = await new Promise((resolve, reject) => {
                http.get('http://localhost:5051/api/triggers/pending', (res: any) => {
                    let body = '';
                    res.on('data', (chunk: string) => body += chunk);
                    res.on('end', () => {
                        try { resolve(JSON.parse(body)); } catch { resolve({ triggers: [] }); }
                    });
                }).on('error', () => resolve({ triggers: [] }));
            });

            const triggers = data.triggers || [];
            if (triggers.length === 0) { return; }

            for (const trigger of triggers) {
                // Skip if we already processed this trigger
                if (trigger.timestamp === lastTriggerTimestamp) { continue; }

                // STRICT workspace matching: only the correct VS Code window handles this trigger
                const triggerWorkspace = trigger.workspace_path || '';
                if (triggerWorkspace) {
                    const normalizedTrigger = path.resolve(triggerWorkspace).toLowerCase();
                    const normalizedThis = path.resolve(thisWorkspaceRoot).toLowerCase();
                    if (normalizedTrigger !== normalizedThis) {
                        continue; // Not for this window — completely ignore
                    }
                } else {
                    // No workspace_path set — skip entirely (server should always set it)
                    continue;
                }

                lastTriggerTimestamp = trigger.timestamp;

                const ticketKey = trigger.ticket_key;
                const agent = trigger.agent;
                const triggerContext = trigger.context || '';

                // Show notification (non-blocking — don't await)
                vscode.window.showInformationMessage(
                    `🤖 [${ticketKey}] Auto-triggering @${agent} agent...`
                );

                // Build the query for each agent
                let query = '';
                switch (agent) {
                    case 'developer':
                        query = `You are working on ${ticketKey}. Call GET http://localhost:5051/api/pipeline/${ticketKey}/developer-prompt to get your instructions. Context update: ${triggerContext}. Implement the required changes. When done, call POST http://localhost:5051/api/pipeline/${ticketKey}/developer-done with a summary.`;
                        break;
                    case 'reviewer':
                        query = `Review the changes for ${ticketKey}. Call GET http://localhost:5051/api/pipeline/${ticketKey}/reviewer-prompt for instructions. Run git diff main to see changes. Review against requirements. When done, call POST http://localhost:5051/api/pipeline/${ticketKey}/reviewer-done with your response (start with VERDICT: APPROVED or VERDICT: CHANGES_REQUESTED).`;
                        break;
                    case 'tester':
                        query = `Test the implementation for ${ticketKey}. Call GET http://localhost:5051/api/pipeline/${ticketKey}/tester-prompt for instructions. Run any existing tests and verify the implementation. When done, call POST http://localhost:5051/api/pipeline/${ticketKey}/tester-done with your response (start with VERDICT: PASSED or VERDICT: FAILED).`;
                        break;
                }

                // Auto-open the agent chat immediately (try multiple approaches)
                try {
                    await vscode.commands.executeCommand(
                        'workbench.action.chat.open',
                        { query: `@${agent} ${query}`, isPartialQuery: false }
                    );
                } catch {
                    try {
                        await vscode.commands.executeCommand(
                            'workbench.action.chat.open',
                            { mode: agent, query, isPartialQuery: false }
                        );
                    } catch {
                        try {
                            await vscode.commands.executeCommand('workbench.action.chat.open', { query });
                        } catch {
                            vscode.window.showWarningMessage(
                                `Switch to @${agent} in Chat and paste the prompt from the Pipeline panel.`
                            );
                        }
                    }
                }

                // Clear the trigger after consumption
                http.request({
                    hostname: 'localhost', port: 5051,
                    path: `/api/triggers/${ticketKey}`,
                    method: 'DELETE'
                }, () => {}).end();
            }
        } catch {
            // Server not running — silently ignore
        }
    }, 5000); // Check every 5 seconds

    context.subscriptions.push({ dispose: () => clearInterval(interval) });
}
