import { useState, useEffect } from 'react';
import { getDashboard, getJiraTickets, createSession, closeSession, getTicketSummary, activateTicket } from '../api/engmemory';
import { GitBranch, MessageSquare, CheckCircle2, Clock, AlertCircle, Zap, Plus, X, Brain } from 'lucide-react';
import toast from 'react-hot-toast';

const statusColors = {
  in_progress: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200',
  waiting: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200',
  blocked: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200',
  done: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
  new: 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-200',
};

const statusIcons = {
  in_progress: Zap,
  waiting: Clock,
  blocked: AlertCircle,
  done: CheckCircle2,
};

export default function TicketSessions() {
  const [dashboard, setDashboard] = useState(null);
  const [tickets, setTickets] = useState([]);
  const [loading, setLoading] = useState(true);
  const [summaryLoading, setSummaryLoading] = useState(null);
  const [summaries, setSummaries] = useState({});

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 15000); // Refresh every 15s
    return () => clearInterval(interval);
  }, []);

  const loadData = async () => {
    try {
      const [dashData, ticketData] = await Promise.all([
        getDashboard(),
        getJiraTickets('all'),
      ]);
      setDashboard(dashData);
      setTickets(ticketData.tickets || []);
    } catch (err) {
      console.error('Failed to load data:', err);
    } finally {
      setLoading(false);
    }
  };

  const [activatingTicket, setActivatingTicket] = useState(null);

  const handleActivate = async (ticketKey) => {
    setActivatingTicket(ticketKey);
    try {
      toast.loading(`Setting up workspace for ${ticketKey}... This may take 30-60 seconds.`, { id: 'activate-progress' });
      await createSession(ticketKey);
      const ticket = tickets.find(t => t.key === ticketKey);
      await activateTicket(ticketKey, ticket?.summary || '', ticketKey);
      toast.dismiss('activate-progress');
      toast.success(`${ticketKey} activated! New VS Code window opening...`);
      loadData();
    } catch (err) {
      toast.dismiss('activate-progress');
      toast.error(`Failed to activate ${ticketKey}: ${err.response?.data?.detail || err.message}`);
    } finally {
      setActivatingTicket(null);
    }
  };

  const handleClose = async (ticketKey) => {
    try {
      await closeSession(ticketKey, true);
      toast.success(`Session closed for ${ticketKey}`);
      loadData();
    } catch (err) {
      toast.error(`Failed: ${err.message}`);
    }
  };

  const handleSummary = async (ticketKey) => {
    setSummaryLoading(ticketKey);
    try {
      const result = await getTicketSummary(ticketKey);
      setSummaries(prev => ({ ...prev, [ticketKey]: result }));
    } catch (err) {
      toast.error('Failed to generate summary');
    } finally {
      setSummaryLoading(null);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
      </div>
    );
  }

  return (
    <div>
      <div className="flex justify-between items-center mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Ticket Sessions</h1>
          <p className="text-gray-500 dark:text-gray-400 mt-1">
            Automated development lifecycle — Jira → Slack → Git → AI
          </p>
        </div>
        <div className="flex items-center gap-3">
          {dashboard?.system && (
            <div className="flex gap-2 text-xs">
              <span className={`px-2 py-1 rounded-full ${dashboard.system.jira_connected ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
                Jira {dashboard.system.jira_connected ? '●' : '○'}
              </span>
              <span className={`px-2 py-1 rounded-full ${dashboard.system.slack_connected ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
                Slack {dashboard.system.slack_connected ? '●' : '○'}
              </span>
              <span className={`px-2 py-1 rounded-full ${dashboard.system.azure_connected ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
                Azure {dashboard.system.azure_connected ? '●' : '○'}
              </span>
            </div>
          )}
        </div>
      </div>

      {/* Active Sessions */}
      {dashboard?.sessions?.length > 0 && (
        <div className="mb-8">
          <h2 className="text-lg font-semibold text-gray-800 dark:text-gray-200 mb-3">Active Sessions</h2>
          <div className="grid gap-4">
            {dashboard.sessions.map((session) => {
              const StatusIcon = statusIcons[session.status] || Clock;
              return (
                <div
                  key={session.ticket_key}
                  className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5 hover:shadow-md transition-shadow"
                >
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      <div className="flex items-center gap-3">
                        <span className="font-mono text-sm font-bold text-blue-600 dark:text-blue-400">
                          {session.ticket_key}
                        </span>
                        <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${statusColors[session.status] || statusColors.new}`}>
                          <StatusIcon size={12} className="inline mr-1" />
                          {session.status}
                        </span>
                        {session.has_updates && (
                          <span className="px-2 py-0.5 rounded-full text-xs bg-orange-100 text-orange-700 dark:bg-orange-900 dark:text-orange-200 animate-pulse">
                            New updates
                          </span>
                        )}
                      </div>
                      <h3 className="text-gray-900 dark:text-white font-medium mt-1">{session.summary}</h3>

                      {/* Pipeline Stage Indicator */}
                      {session.pipeline && session.pipeline.stage !== 'no_pipeline' && (
                        <div className="flex items-center gap-2 mt-2">
                          <span className="text-xs font-medium text-gray-500 dark:text-gray-400">Pipeline:</span>
                          <div className="flex items-center gap-1">
                            <PipelineDot stage="developer" current={session.pipeline.stage} />
                            <span className="text-gray-300 dark:text-gray-600">→</span>
                            <PipelineDot stage="review" current={session.pipeline.stage} />
                            <span className="text-gray-300 dark:text-gray-600">→</span>
                            <PipelineDot stage="testing" current={session.pipeline.stage} />
                            <span className="text-gray-300 dark:text-gray-600">→</span>
                            <PipelineDot stage="done" current={session.pipeline.stage} />
                          </div>
                          {session.pipeline.pr_url && (
                            <a href={session.pipeline.pr_url} target="_blank" rel="noreferrer" className="text-xs text-purple-600 hover:underline">
                              PR ↗
                            </a>
                          )}
                        </div>
                      )}
                      <div className="flex items-center gap-4 mt-2 text-sm text-gray-500 dark:text-gray-400">
                        <span className="flex items-center gap-1">
                          <GitBranch size={14} /> {session.branch}
                        </span>
                        {session.slack_channel && (
                          <span className="flex items-center gap-1">
                            <MessageSquare size={14} /> #{session.slack_channel}
                          </span>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      {session.pending_questions > 0 && (
                        <span className="text-xs bg-yellow-100 text-yellow-800 px-2 py-1 rounded">
                          {session.pending_questions} questions
                        </span>
                      )}
                      <button
                        onClick={() => handleSummary(session.ticket_key)}
                        disabled={summaryLoading === session.ticket_key}
                        className="p-1.5 text-indigo-400 hover:text-indigo-600 transition-colors disabled:opacity-50"
                        title="AI Summary"
                      >
                        {summaryLoading === session.ticket_key ? (
                          <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-indigo-600"></div>
                        ) : (
                          <Brain size={16} />
                        )}
                      </button>
                      <button
                        onClick={() => handleClose(session.ticket_key)}
                        className="p-1 text-gray-400 hover:text-red-500 transition-colors"
                        title="Close session"
                      >
                        <X size={16} />
                      </button>
                    </div>
                  </div>
                  {/* AI Summary */}
                  {summaries[session.ticket_key] && (
                    <div className="mt-3 p-3 bg-indigo-50 dark:bg-indigo-900/20 rounded-lg border border-indigo-100 dark:border-indigo-800">
                      <div className="flex items-center gap-2 mb-1">
                        <Brain size={12} className="text-indigo-500" />
                        <span className="text-xs font-medium text-indigo-700 dark:text-indigo-300">AI Summary</span>
                        <span className={`text-xs px-1.5 py-0.5 rounded ${
                          summaries[session.ticket_key].status_assessment === 'on_track'
                            ? 'bg-green-100 text-green-700'
                            : summaries[session.ticket_key].status_assessment === 'blocked'
                            ? 'bg-red-100 text-red-700'
                            : 'bg-yellow-100 text-yellow-700'
                        }`}>
                          {summaries[session.ticket_key].status_assessment}
                        </span>
                      </div>
                      <p className="text-sm text-gray-700 dark:text-gray-300">
                        {summaries[session.ticket_key].summary}
                      </p>
                      {summaries[session.ticket_key].next_steps?.length > 0 && (
                        <div className="mt-2">
                          <span className="text-xs text-gray-500">Next steps:</span>
                          {summaries[session.ticket_key].next_steps.map((step, i) => (
                            <span key={i} className="ml-2 text-xs text-indigo-600 dark:text-indigo-400">• {step}</span>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Jira Tickets */}
      <div>
        <h2 className="text-lg font-semibold text-gray-800 dark:text-gray-200 mb-3">Jira Tickets</h2>
        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
          <table className="w-full">
            <thead className="bg-gray-50 dark:bg-gray-900">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Ticket</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Summary</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Type</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Status</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Session</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
              {tickets.map((ticket) => (
                <tr key={ticket.key} className="hover:bg-gray-50 dark:hover:bg-gray-750">
                  <td className="px-4 py-3 font-mono text-sm font-bold text-blue-600 dark:text-blue-400">
                    {ticket.key}
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-900 dark:text-white">{ticket.summary}</td>
                  <td className="px-4 py-3 text-sm text-gray-500 dark:text-gray-400">{ticket.type}</td>
                  <td className="px-4 py-3">
                    <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300">
                      {ticket.status}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    {ticket.has_session ? (
                      <span className="text-xs px-2 py-0.5 rounded-full bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300">
                        Active
                      </span>
                    ) : (
                      <span className="text-xs text-gray-400">—</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right">
                    {!ticket.has_session && (
                      <button
                        onClick={() => handleActivate(ticket.key)}
                        disabled={activatingTicket === ticket.key}
                        className={`inline-flex items-center gap-1 px-3 py-1 text-xs font-medium text-white rounded-lg transition-colors ${activatingTicket === ticket.key ? 'bg-blue-400 cursor-wait' : 'bg-blue-600 hover:bg-blue-700'}`}
                      >
                        {activatingTicket === ticket.key ? (
                          <><svg className="animate-spin h-3 w-3" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none"/><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg> Setting up...</>
                        ) : (
                          <><Plus size={12} /> Activate</>
                        )}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// Pipeline stage dot indicator
function PipelineDot({ stage, current }) {
  const stageOrder = ['idle', 'context_gathering', 'developer', 'review', 'testing', 'pr_creation', 'waiting_for_merge', 'done'];
  const currentIndex = stageOrder.indexOf(current);
  const stageIndex = stageOrder.indexOf(stage === 'done' ? 'done' : stage);

  const labels = {
    developer: 'Dev',
    review: 'Review',
    testing: 'Test',
    done: 'Done',
  };

  const isActive = current === stage || (stage === 'done' && (current === 'done' || current === 'waiting_for_merge' || current === 'pr_creation'));
  const isPast = stageIndex < currentIndex;
  const isCurrent = current === stage;

  let colorClass = 'bg-gray-200 text-gray-500 dark:bg-gray-700 dark:text-gray-400';
  if (isPast || (stage === 'done' && current === 'done')) {
    colorClass = 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300';
  } else if (isCurrent) {
    colorClass = 'bg-purple-100 text-purple-700 dark:bg-purple-900 dark:text-purple-300 ring-2 ring-purple-400 animate-pulse';
  }

  return (
    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${colorClass}`}>
      {labels[stage] || stage}
    </span>
  );
}
