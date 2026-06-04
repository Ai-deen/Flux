import axios from 'axios';

// Flux API — uses env variable in production, localhost in dev
const API_BASE = import.meta.env.VITE_API_URL ?? '';

const engmemory = axios.create({
  baseURL: API_BASE,
  headers: { 'Content-Type': 'application/json' },
});

// ─── Dashboard ───────────────────────────────────────────────────────────

export const getDashboard = async () => {
  const response = await engmemory.get('/api/dashboard');
  return response.data;
};

// ─── Sessions ────────────────────────────────────────────────────────────

export const getSessions = async () => {
  const response = await engmemory.get('/api/sessions');
  return response.data;
};

export const getSession = async (ticketKey) => {
  const response = await engmemory.get(`/api/sessions/${ticketKey}`);
  return response.data;
};

export const createSession = async (ticketKey) => {
  const response = await engmemory.post(`/api/sessions/${ticketKey}/create`);
  return response.data;
};

export const closeSession = async (ticketKey, deleteChannel = false) => {
  const response = await engmemory.delete(`/api/sessions/${ticketKey}?delete_channel=${deleteChannel}`);
  return response.data;
};

export const getSessionContext = async (ticketKey) => {
  const response = await engmemory.get(`/api/sessions/${ticketKey}/context`);
  return response.data;
};

// ─── Jira ────────────────────────────────────────────────────────────────

export const getJiraTickets = async (status = 'all') => {
  const response = await engmemory.get(`/api/jira/tickets?status=${status}`);
  return response.data;
};

export const getJiraTicket = async (ticketKey) => {
  const response = await engmemory.get(`/api/jira/tickets/${ticketKey}`);
  return response.data;
};

// ─── Slack ───────────────────────────────────────────────────────────────

export const getSlackChannels = async () => {
  const response = await engmemory.get('/api/slack/channels');
  return response.data;
};

export const createSlackChannel = async (ticketKey, summary, assigneeEmail = '') => {
  const response = await engmemory.post('/api/slack/channels/create', {
    ticket_key: ticketKey,
    summary,
    assignee_email: assigneeEmail,
  });
  return response.data;
};

export const archiveSlackChannel = async (channelId) => {
  const response = await engmemory.delete(`/api/slack/channels/${channelId}`);
  return response.data;
};

export const getChannelMessages = async (channelId, limit = 50) => {
  const response = await engmemory.get(`/api/slack/channels/${channelId}/messages?limit=${limit}`);
  return response.data;
};

// ─── Git ─────────────────────────────────────────────────────────────────

export const getGitBranches = async () => {
  const response = await engmemory.get('/api/git/branches');
  return response.data;
};

export const getGitCommits = async (branch = null, limit = 20) => {
  let url = `/api/git/commits?limit=${limit}`;
  if (branch) url += `&branch=${branch}`;
  const response = await engmemory.get(url);
  return response.data;
};

export const createGitBranch = async (ticketKey) => {
  const response = await engmemory.post(`/api/git/branches/create?ticket_key=${ticketKey}`);
  return response.data;
};

// ─── Access Control ──────────────────────────────────────────────────────

export const getRoles = async () => {
  const response = await engmemory.get('/api/access/roles');
  return response.data;
};

export const setRole = async (email, role, team, allowedTickets) => {
  const response = await engmemory.post('/api/access/roles', {
    email,
    role,
    team,
    allowed_tickets: allowedTickets,
  });
  return response.data;
};

export const checkAccess = async (email, ticketKey) => {
  const response = await engmemory.get(`/api/access/check?email=${email}&ticket_key=${ticketKey}`);
  return response.data;
};

// ─── Health ──────────────────────────────────────────────────────────────

export const getHealth = async () => {
  const response = await engmemory.get('/api/health');
  return response.data;
};

// ─── AI Intelligence ─────────────────────────────────────────────────────

export const getTicketSummary = async (ticketKey) => {
  const response = await engmemory.get(`/api/sessions/${ticketKey}/summary`);
  return response.data;
};

export const getRisks = async () => {
  const response = await engmemory.get('/api/risks');
  return response.data;
};

// ─── Metrics ─────────────────────────────────────────────────────────────

export const getMetrics = async () => {
  const response = await engmemory.get('/api/metrics');
  return response.data;
};

// ─── Demo Mode ───────────────────────────────────────────────────────────

export const runDemo = async (ticketKey = 'DEMO-1', summary = 'Implement user authentication with OAuth2', priority = 'High') => {
  const response = await engmemory.post('/api/demo/run', {
    ticket_key: ticketKey,
    summary,
    priority,
  });
  return response.data;
};

export const resetDemo = async () => {
  const response = await engmemory.post('/api/demo/reset');
  return response.data;
};

// ─── Local Agent Bridge ──────────────────────────────────────────────────

export const getAgentStatus = async () => {
  const response = await engmemory.get('/api/agent/status');
  return response.data;
};

export const activateTicket = async (ticketKey, summary = '', branch = '') => {
  const response = await engmemory.post('/api/agent/command', {
    action: 'activate',
    ticket_key: ticketKey,
    summary,
    branch: branch || ticketKey,
  });
  return response.data;
};

export const askAgent = async (question) => {
  const response = await engmemory.post('/api/agent/command', {
    action: 'ask',
    question,
  });
  return response.data;
};

export default engmemory;
