import { useState, useEffect } from 'react';
import { getSlackChannels, getChannelMessages, createSlackChannel, archiveSlackChannel } from '../api/engmemory';
import { Hash, Users, Archive, Plus, MessageSquare, RefreshCw } from 'lucide-react';
import toast from 'react-hot-toast';

export default function SlackChannels() {
  const [channels, setChannels] = useState([]);
  const [selectedChannel, setSelectedChannel] = useState(null);
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [newTicket, setNewTicket] = useState('');
  const [newSummary, setNewSummary] = useState('');

  useEffect(() => {
    loadChannels();
  }, []);

  const loadChannels = async () => {
    try {
      const data = await getSlackChannels();
      setChannels(data.channels || []);
    } catch (err) {
      toast.error('Failed to load channels');
    } finally {
      setLoading(false);
    }
  };

  const loadMessages = async (channelId) => {
    setSelectedChannel(channelId);
    try {
      const data = await getChannelMessages(channelId, 30);
      setMessages(data.messages || []);
    } catch (err) {
      toast.error('Failed to load messages');
    }
  };

  const handleCreate = async () => {
    if (!newTicket || !newSummary) return;
    try {
      await createSlackChannel(newTicket, newSummary);
      toast.success(`Channel created for ${newTicket}`);
      setShowCreate(false);
      setNewTicket('');
      setNewSummary('');
      loadChannels();
    } catch (err) {
      toast.error('Failed to create channel');
    }
  };

  const handleArchive = async (channelId, channelName) => {
    if (!confirm(`Archive #${channelName}?`)) return;
    try {
      await archiveSlackChannel(channelId);
      toast.success(`#${channelName} archived`);
      loadChannels();
    } catch (err) {
      toast.error('Failed to archive');
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
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Slack Channels</h1>
          <p className="text-gray-500 dark:text-gray-400 mt-1">
            Auto-created discussion channels for Jira tickets
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={loadChannels}
            className="p-2 text-gray-500 hover:text-blue-600 transition-colors"
          >
            <RefreshCw size={18} />
          </button>
          <button
            onClick={() => setShowCreate(true)}
            className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors"
          >
            <Plus size={16} /> Create Channel
          </button>
        </div>
      </div>

      {/* Create Channel Modal */}
      {showCreate && (
        <div className="mb-6 bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5">
          <h3 className="font-medium text-gray-900 dark:text-white mb-3">Create Slack Channel</h3>
          <div className="flex gap-3">
            <input
              type="text"
              placeholder="Ticket Key (e.g. KAN-4)"
              value={newTicket}
              onChange={(e) => setNewTicket(e.target.value)}
              className="flex-1 px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-900 text-gray-900 dark:text-white text-sm"
            />
            <input
              type="text"
              placeholder="Summary (e.g. Fix login bug)"
              value={newSummary}
              onChange={(e) => setNewSummary(e.target.value)}
              className="flex-1 px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-900 text-gray-900 dark:text-white text-sm"
            />
            <button onClick={handleCreate} className="px-4 py-2 text-sm text-white bg-green-600 hover:bg-green-700 rounded-lg">
              Create
            </button>
            <button onClick={() => setShowCreate(false)} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900 dark:text-gray-400">
              Cancel
            </button>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Channel List */}
        <div className="lg:col-span-1">
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
            {channels.map((ch) => (
              <div
                key={ch.id}
                onClick={() => loadMessages(ch.id)}
                className={`p-4 border-b border-gray-100 dark:border-gray-700 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-750 transition-colors ${
                  selectedChannel === ch.id ? 'bg-blue-50 dark:bg-gray-700' : ''
                }`}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Hash size={14} className="text-gray-400" />
                    <span className="text-sm font-medium text-gray-900 dark:text-white truncate">
                      {ch.name}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-gray-400 flex items-center gap-1">
                      <Users size={12} /> {ch.num_members}
                    </span>
                    <button
                      onClick={(e) => { e.stopPropagation(); handleArchive(ch.id, ch.name); }}
                      className="p-1 text-gray-300 hover:text-red-500 transition-colors"
                      title="Archive channel"
                    >
                      <Archive size={12} />
                    </button>
                  </div>
                </div>
                {ch.topic && (
                  <p className="text-xs text-gray-500 dark:text-gray-400 mt-1 truncate">{ch.topic}</p>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Messages */}
        <div className="lg:col-span-2">
          {selectedChannel ? (
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5">
              <h3 className="font-medium text-gray-900 dark:text-white mb-4 flex items-center gap-2">
                <MessageSquare size={16} /> Channel Messages
              </h3>
              {messages.length === 0 ? (
                <p className="text-gray-400 text-sm">No messages yet</p>
              ) : (
                <div className="space-y-3 max-h-96 overflow-y-auto">
                  {messages.map((msg, i) => (
                    <div key={i} className="flex gap-3">
                      <div className="w-8 h-8 bg-blue-100 dark:bg-blue-900 rounded-full flex items-center justify-center text-xs font-medium text-blue-700 dark:text-blue-300">
                        {msg.user?.slice(0, 2).toUpperCase() || '??'}
                      </div>
                      <div className="flex-1">
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-medium text-gray-700 dark:text-gray-300">{msg.user}</span>
                          <span className="text-xs text-gray-400">
                            {new Date(parseFloat(msg.timestamp) * 1000).toLocaleTimeString()}
                          </span>
                        </div>
                        <p className="text-sm text-gray-900 dark:text-white mt-0.5">{msg.text}</p>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-8 text-center">
              <MessageSquare size={40} className="mx-auto text-gray-300 dark:text-gray-600" />
              <p className="text-gray-500 dark:text-gray-400 mt-3">Select a channel to view messages</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
