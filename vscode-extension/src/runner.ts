import { exec } from 'child_process';
import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';

function findEngMemoryPath(cwd: string): string {
    // Check common venv locations for engmemory executable
    const venvPaths = [
        path.join(cwd, 'backend', 'venv', 'Scripts', 'engmemory.exe'),
        path.join(cwd, 'venv', 'Scripts', 'engmemory.exe'),
        path.join(cwd, '.venv', 'Scripts', 'engmemory.exe'),
        path.join(cwd, 'ai-workflow-app', 'backend', 'venv', 'Scripts', 'engmemory.exe'),
        path.join(cwd, 'backend', 'venv', 'bin', 'engmemory'),
        path.join(cwd, 'venv', 'bin', 'engmemory'),
        path.join(cwd, '.venv', 'bin', 'engmemory'),
        path.join(cwd, 'ai-workflow-app', 'backend', 'venv', 'bin', 'engmemory'),
    ];

    for (const p of venvPaths) {
        if (fs.existsSync(p)) {
            return `"${p}"`;
        }
    }

    // Fallback to global
    return 'engmemory';
}

function findEnvFile(cwd: string): string | undefined {
    const locations = [
        path.join(cwd, 'engmemory.env.txt'),
        path.join(cwd, '.env'),
        path.join(path.dirname(cwd), 'engmemory.env.txt'),
    ];
    for (const p of locations) {
        if (fs.existsSync(p)) {
            return p;
        }
    }
    return undefined;
}

function loadEnvVars(cwd: string): Record<string, string> {
    const env: Record<string, string> = { ...process.env } as Record<string, string>;
    const envFile = findEnvFile(cwd);
    if (envFile) {
        const content = fs.readFileSync(envFile, 'utf-8');
        for (const line of content.split('\n')) {
            const trimmed = line.trim();
            if (trimmed && !trimmed.startsWith('#')) {
                const eqIdx = trimmed.indexOf('=');
                if (eqIdx > 0) {
                    const key = trimmed.slice(0, eqIdx).trim();
                    const val = trimmed.slice(eqIdx + 1).trim();
                    env[key] = val;
                }
            }
        }
    }
    return env;
}

export function runEngMemory(cwd: string, args: string[]): Promise<string> {
    return new Promise((resolve) => {
        const engmemoryPath = findEngMemoryPath(cwd);
        const env = loadEnvVars(cwd);

        // Find the actual git repo to run in (might be a subfolder)
        let runDir = cwd;
        const subDirs = ['ai-workflow-app'];
        for (const sub of subDirs) {
            const subPath = path.join(cwd, sub, '.git');
            if (fs.existsSync(subPath)) {
                runDir = path.join(cwd, sub);
                break;
            }
        }
        if (!fs.existsSync(path.join(runDir, '.git'))) {
            // Check if cwd itself is a git repo
            runDir = cwd;
        }

        const command = `${engmemoryPath} ${args.map(a => `"${a}"`).join(' ')}`;

        exec(command, { cwd: runDir, timeout: 60000, env }, (error, stdout, stderr) => {
            if (error) {
                resolve(`Error: ${stderr || error.message}`);
            } else {
                resolve(stdout.trim());
            }
        });
    });
}

export function runEngMemoryRaw(cwd: string, args: string[]): Promise<{ stdout: string; stderr: string; code: number }> {
    return new Promise((resolve) => {
        const command = `engmemory ${args.map(a => `"${a}"`).join(' ')}`;
        exec(command, { cwd, timeout: 60000 }, (error, stdout, stderr) => {
            resolve({
                stdout: stdout.trim(),
                stderr: stderr.trim(),
                code: error?.code || 0
            });
        });
    });
}
