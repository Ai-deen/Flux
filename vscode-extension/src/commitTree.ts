import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import * as http from 'http';

interface CommitData {
    sha: string;
    short_sha: string;
    message: string;
    author_name: string;
    timestamp: string;
    branch: string;
    files_changed: number;
    ticket_id?: string;
}

function apiGet(apiPath: string): Promise<any> {
    return new Promise((resolve, reject) => {
        const req = http.get(`http://localhost:5051${apiPath}`, { timeout: 5000 }, (res) => {
            let data = '';
            res.on('data', chunk => data += chunk);
            res.on('end', () => {
                try { resolve(JSON.parse(data)); } catch { resolve(null); }
            });
        });
        req.on('error', () => resolve(null));
        req.on('timeout', () => { req.destroy(); resolve(null); });
    });
}

export class CommitTreeProvider implements vscode.TreeDataProvider<CommitItem> {
    private _onDidChangeTreeData = new vscode.EventEmitter<CommitItem | undefined>();
    readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

    constructor(private workspaceRoot: string) {}

    refresh(): void {
        this._onDidChangeTreeData.fire(undefined);
    }

    getTreeItem(element: CommitItem): vscode.TreeItem {
        return element;
    }

    async getChildren(): Promise<CommitItem[]> {
        // Check multiple possible locations for .ai_memory
        const possibleDirs = [
            path.join(this.workspaceRoot, '.ai_memory', 'commits'),
            path.join(this.workspaceRoot, 'ai-workflow-app', '.ai_memory', 'commits'),
        ];

        let commitsDir = '';
        for (const dir of possibleDirs) {
            if (fs.existsSync(dir)) {
                commitsDir = dir;
                break;
            }
        }

        // If no local commits, try fetching from API (Azure-backed)
        if (!commitsDir) {
            return await this._fetchFromApi();
        }

        const files = fs.readdirSync(commitsDir)
            .filter(f => f.endsWith('.json'))
            .sort()
            .reverse()
            .slice(0, 30);

        if (files.length === 0) {
            return await this._fetchFromApi();
        }

        return files.map(file => {
            try {
                const content = fs.readFileSync(path.join(commitsDir, file), 'utf-8');
                const data: CommitData = JSON.parse(content);
                const item = new CommitItem(
                    data.message.slice(0, 60),
                    data.short_sha,
                    `${data.author_name} • ${new Date(data.timestamp).toLocaleDateString()} • ${data.files_changed} files`,
                    vscode.TreeItemCollapsibleState.None
                );
                item.iconPath = new vscode.ThemeIcon('git-commit');
                item.tooltip = `${data.sha}\n${data.message}\n${data.author_name}\n${data.timestamp}\nBranch: ${data.branch}\nFiles: ${data.files_changed}`;
                return item;
            } catch {
                return new CommitItem(file, '', 'Error reading commit', vscode.TreeItemCollapsibleState.None);
            }
        });
    }

    private async _fetchFromApi(): Promise<CommitItem[]> {
        const data = await apiGet('/api/commits/recent');
        if (!data || !data.commits || data.commits.length === 0) {
            return [new CommitItem('No commits captured yet', '', 'Commits from merged PRs will appear here', vscode.TreeItemCollapsibleState.None)];
        }
        return data.commits.slice(0, 20).map((c: any) => {
            const commit = c.commit || c;
            const msg = commit.message || 'No message';
            const item = new CommitItem(
                msg.slice(0, 60),
                commit.short_sha || commit.sha?.slice(0, 8) || '',
                `${commit.author_name || 'Unknown'} • ${commit.timestamp ? new Date(commit.timestamp).toLocaleDateString() : ''} • ${commit.branch || 'main'}`,
                vscode.TreeItemCollapsibleState.None
            );
            item.iconPath = new vscode.ThemeIcon('git-commit');
            item.tooltip = `${msg}\n${commit.author_name || ''}\n${commit.timestamp || ''}\nBranch: ${commit.branch || ''}`;
            return item;
        });
    }
}

class CommitItem extends vscode.TreeItem {
    constructor(
        public readonly label: string,
        private sha: string,
        private detail: string,
        public readonly collapsibleState: vscode.TreeItemCollapsibleState
    ) {
        super(label, collapsibleState);
        this.description = sha;
        this.tooltip = detail;
    }
}
