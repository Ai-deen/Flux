import { useState, useEffect } from 'react';
import { getDashboard, getGitCommits, getMetrics, runDemo, resetDemo, getRisks } from '../api/engmemory';
import { Zap, GitBranch, MessageSquare, Ticket, Shield, CheckCircle2, Clock, AlertCircle, Play, RotateCcw, TrendingUp, Activity } from 'lucide-react';
import { Link } from 'react-router-dom';
import toast from 'react-hot-toast';

const statusColors = {
  in_progress: 'border-blue-500 bg-blue-50 dark:bg-blue-900/20',
  waiting: 'border-yellow-500 bg-yellow-50 dark:bg-yellow-900/20',
  blocked: 'border-red-500 bg-red-50 dark:bg-red-900/20',
  done: 'border-green-500 bg-green-50 dark:bg-green-900/20',
};

export default function Dashboard() {
  const [data, setData] = useState(null);
  const [commits, setCommits] = useState([]);
  const [metrics, setMetrics] = useState(null);
  const [risks, setRisks] = useState([]);
  const [demoResult, setDemoResult] = useState(null);
  const [demoRunning, setDemoRunning] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 10000);
    return () => clearInterval(interval);
  }, []);

  const loadData = async () => {
    try {
      const [dash, commitData, metricsData, risksData] = await Promise.all([
        getDashboard(),
        getGitCommits(null, 5),
        getMetrics().catch(() => null),
        getRisks().catch(() => ({ risks: [] })),
      ]);
      setData(dash);
      setCommits(commitData.commits || []);
      setMetrics(metricsData);
      setRisks(risksData.risks || []);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const handleRunDemo = async () => {
    setDemoRunning(true);
    setDemoResult(null);
    try {
      const result = await runDemo();
      setDemoResult(result);
      toast.success(`Demo complete in ${result.total_time_ms}ms!`);
      loadData();
    } catch (err) {
      toast.error('Demo failed: ' + (err.response?.data?.detail || err.message));
    } finally {
      setDemoRunning(false);
    }
  };

  const handleResetDemo = async () => {
    await resetDemo();
    setDemoResult(null);
    toast.success('Demo sessions cleared');
    loadData();
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-600"></div>
      </div>
    );
  }

  if (!data) return <p className="text-gray-500">Failed to connect to Flux server</p>;

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900 dark:text-white">Flux Dashboard</h1>
        <p className="text-gray-500 dark:text-gray-400 mt-1">
          From ticket to code — zero friction, fully automated
        </p>
      </div>

      {/* System Status */}
      <div className="grid grid-cols-4 gap-4 mb-8">
        <StatusCard
          label="Active Sessions"
          value={data.active_sessions}
          icon={Ticket}
          color="indigo"
          link="/tickets"
        />
        <StatusCard
          label="Jira"
          value={data.system.jira_connected ? 'Connected' : 'Offline'}
          icon={CheckCircle2}
          color={data.system.jira_connected ? 'green' : 'red'}
        />
        <StatusCard
          label="Slack"
          value={data.system.slack_connected ? 'Connected' : 'Offline'}
          icon={MessageSquare}
          color={data.system.slack_connected ? 'green' : 'red'}
        />
        <StatusCard
          label="Azure"
          value={data.system.azure_connected ? 'Connected' : 'Offline'}
          icon={Shield}
          color={data.system.azure_connected ? 'green' : 'red'}
        />
      </div>

      {/* Metrics Bar */}
      {metrics && (
        <div className="grid grid-cols-5 gap-3 mb-8">
          <MetricCard label="Total Sessions" value={metrics.total_sessions} icon={Activity} />
          <MetricCard label="Commits Tracked" value={metrics.commits_tracked} icon={GitBranch} />
          <MetricCard label="Channels Active" value={metrics.channels_tracked} icon={MessageSquare} />
          <MetricCard label="Jira Comments" value={metrics.context_captured.jira_comments} icon={Ticket} />
          <MetricCard label="Slack Messages" value={metrics.context_captured.slack_messages} icon={TrendingUp} />
        </div>
      )}

      {/* Demo Mode */}
      <div className="mb-8 bg-gradient-to-r from-indigo-50 to-purple-50 dark:from-indigo-900/20 dark:to-purple-900/20 rounded-xl border border-indigo-200 dark:border-indigo-800 p-6">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white flex items-center gap-2">
              <Play size={18} className="text-indigo-600" /> Demo Mode
            </h2>
            <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
              One-click full flow: Create ticket → Slack channel → Git branch → AI context → Summary
            </p>
          </div>
          <div className="flex gap-2">
            <button
              onClick={handleResetDemo}
              className="px-3 py-2 text-sm text-gray-600 hover:text-gray-900 dark:text-gray-400 flex items-center gap-1"
            >
              <RotateCcw size={14} /> Reset
            </button>
            <button
              onClick={handleRunDemo}
              disabled={demoRunning}
              className="px-5 py-2 text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 rounded-lg flex items-center gap-2 disabled:opacity-50"
            >
              {demoRunning ? (
                <><div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div> Running...</>
              ) : (
                <><Play size={14} /> Run Full Demo</>
              )}
            </button>
          </div>
        </div>

        {/* Demo Results */}
        {demoResult && (
          <div className="mt-4 bg-white dark:bg-gray-800 rounded-lg p-4 border border-gray-200 dark:border-gray-700">
            <div className="flex items-center gap-2 mb-3">
              <CheckCircle2 size={16} className="text-green-500" />
              <span className="text-sm font-medium text-gray-900 dark:text-white">
                Completed in {demoResult.total_time_ms}ms
              </span>
            </div>
            <div className="grid grid-cols-5 gap-2">
              {demoResult.steps.map((step, i) => (
                <div key={i} className="text-center p-2 bg-gray-50 dark:bg-gray-700 rounded">
                  <div className="text-xs font-medium text-indigo-600 dark:text-indigo-400">
                    {step.step.replace(/_/g, ' ')}
                  </div>
                  <div className="text-[10px] text-gray-400 mt-1">{step.time_ms}ms</div>
                </div>
              ))}
            </div>
            {demoResult.steps.find(s => s.step === 'ai_summary_generated')?.summary && (
              <p className="mt-3 text-sm text-gray-600 dark:text-gray-300 italic">
                "{demoResult.steps.find(s => s.step === 'ai_summary_generated').summary}"
              </p>
            )}
          </div>
        )}
      </div>

      {/* Risks */}
      {risks.length > 0 && (
        <div className="mb-8 bg-red-50 dark:bg-red-900/20 rounded-xl border border-red-200 dark:border-red-800 p-5">
          <h2 className="text-lg font-semibold text-red-700 dark:text-red-300 flex items-center gap-2">
            <AlertCircle size={18} /> Active Risks ({risks.length})
          </h2>
          <div className="mt-3 space-y-2">
            {risks.map((r, i) => (
              <div key={i} className="flex items-center gap-3 text-sm">
                <span className="font-mono text-red-600 dark:text-red-400">{r.ticket_key}</span>
                <span className="text-gray-700 dark:text-gray-300">{r.detail}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Active Sessions */}
        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Active Sessions</h2>
            <Link to="/tickets" className="text-sm text-indigo-600 hover:text-indigo-700">View all →</Link>
          </div>
          {data.sessions.length === 0 ? (
            <p className="text-gray-400 text-sm">No active sessions. Activate a ticket to begin.</p>
          ) : (
            <div className="space-y-3">
              {data.sessions.map((s) => (
                <div
                  key={s.ticket_key}
                  className={`p-4 rounded-lg border-l-4 ${statusColors[s.status] || 'border-gray-300 bg-gray-50 dark:bg-gray-700'}`}
                >
                  <div className="flex items-center justify-between">
                    <div>
                      <span className="font-mono text-sm font-bold text-indigo-600 dark:text-indigo-400">
                        {s.ticket_key}
                      </span>
                      <span className="ml-2 text-xs px-2 py-0.5 rounded-full bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-300 border">
                        {s.status}
                      </span>
                      {s.has_updates && (
                        <span className="ml-2 text-xs px-2 py-0.5 rounded-full bg-orange-100 text-orange-700 animate-pulse">
                          updates
                        </span>
                      )}
                    </div>
                    <span className="text-xs text-gray-400">{s.priority}</span>
                  </div>
                  <p className="text-sm text-gray-700 dark:text-gray-300 mt-1">{s.summary}</p>
                  <div className="flex items-center gap-3 mt-2 text-xs text-gray-400">
                    <span className="flex items-center gap-1"><GitBranch size={11} /> {s.branch}</span>
                    {s.slack_channel && (
                      <span className="flex items-center gap-1"><MessageSquare size={11} /> #{s.slack_channel}</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Recent Commits */}
        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Recent Commits</h2>
            <Link to="/git" className="text-sm text-indigo-600 hover:text-indigo-700">View all →</Link>
          </div>
          <div className="space-y-3">
            {commits.map((c, i) => (
              <div key={i} className="flex items-start gap-3 py-2 border-b border-gray-100 dark:border-gray-700 last:border-0">
                <div className="w-6 h-6 rounded-full bg-gray-100 dark:bg-gray-700 flex items-center justify-center mt-0.5">
                  <Zap size={12} className="text-gray-500" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-gray-900 dark:text-white truncate">{c.message}</p>
                  <div className="flex gap-3 text-xs text-gray-400 mt-0.5">
                    <span className="font-mono">{c.sha}</span>
                    <span>{c.author}</span>
                    <span>{c.time_ago}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Architecture Overview */}
      <div className="mt-8 bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">How It Works</h2>
        <div className="grid grid-cols-5 gap-2 text-center">
          <FlowStep icon={Ticket} label="Jira Ticket" sublabel="Auto-detected" />
          <FlowArrow />
          <FlowStep icon={MessageSquare} label="Slack Channel" sublabel="Auto-created" />
          <FlowArrow />
          <FlowStep icon={GitBranch} label="Git Branch" sublabel="Auto-created" />
        </div>
        <div className="flex justify-center mt-4">
          <div className="text-gray-400 text-2xl">↓</div>
        </div>
        <div className="grid grid-cols-3 gap-4 mt-4 text-center">
          <FlowStep icon={Zap} label="Context Builder" sublabel="Jira + Slack + Commits" />
          <FlowStep icon={Shield} label="AI Agent" sublabel="Code generation" />
          <FlowStep icon={CheckCircle2} label="Review & PR" sublabel="Auto-pushed" />
        </div>
      </div>
    </div>
  );
}

function StatusCard({ label, value, icon: Icon, color, link }) {
  const colorMap = {
    indigo: 'bg-indigo-50 dark:bg-indigo-900/20 text-indigo-700 dark:text-indigo-300 border-indigo-200 dark:border-indigo-800',
    green: 'bg-green-50 dark:bg-green-900/20 text-green-700 dark:text-green-300 border-green-200 dark:border-green-800',
    red: 'bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-300 border-red-200 dark:border-red-800',
  };
  const Wrapper = link ? Link : 'div';
  return (
    <Wrapper to={link} className={`p-4 rounded-xl border ${colorMap[color]} ${link ? 'hover:shadow-md transition-shadow' : ''}`}>
      <Icon size={20} className="mb-2" />
      <p className="text-2xl font-bold">{value}</p>
      <p className="text-xs opacity-70 mt-1">{label}</p>
    </Wrapper>
  );
}

function FlowStep({ icon: Icon, label, sublabel }) {
  return (
    <div className="p-3 rounded-lg bg-gray-50 dark:bg-gray-700">
      <Icon size={24} className="mx-auto text-indigo-500 mb-1" />
      <p className="text-sm font-medium text-gray-900 dark:text-white">{label}</p>
      <p className="text-xs text-gray-400">{sublabel}</p>
    </div>
  );
}

function FlowArrow() {
  return (
    <div className="flex items-center justify-center text-gray-300 dark:text-gray-600 text-2xl">
      →
    </div>
  );
}

function MetricCard({ label, value, icon: Icon }) {
  return (
    <div className="p-3 bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 text-center">
      <Icon size={16} className="mx-auto text-gray-400 mb-1" />
      <p className="text-xl font-bold text-gray-900 dark:text-white">{value}</p>
      <p className="text-xs text-gray-400">{label}</p>
    </div>
  );
}
