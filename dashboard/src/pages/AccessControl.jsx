import { useState, useEffect } from 'react';
import { getRoles, setRole, checkAccess } from '../api/engmemory';
import { Shield, UserPlus, CheckCircle, XCircle } from 'lucide-react';
import toast from 'react-hot-toast';

const roleBadges = {
  admin: 'bg-purple-100 text-purple-700 dark:bg-purple-900 dark:text-purple-300',
  lead: 'bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300',
  developer: 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300',
  intern: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900 dark:text-yellow-300',
};

export default function AccessControl() {
  const [roles, setRoles] = useState({});
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [newEmail, setNewEmail] = useState('');
  const [newRole, setNewRole] = useState('developer');
  const [newTeam, setNewTeam] = useState('');
  const [newTickets, setNewTickets] = useState('*');

  // Access check
  const [checkEmail, setCheckEmail] = useState('');
  const [checkTicket, setCheckTicket] = useState('');
  const [checkResult, setCheckResult] = useState(null);

  useEffect(() => {
    loadRoles();
  }, []);

  const loadRoles = async () => {
    try {
      const data = await getRoles();
      setRoles(data.roles || {});
    } catch (err) {
      console.error('Failed:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleAddRole = async () => {
    if (!newEmail) return;
    try {
      await setRole(newEmail, newRole, newTeam, newTickets);
      toast.success(`Role set for ${newEmail}`);
      setShowAdd(false);
      setNewEmail('');
      loadRoles();
    } catch (err) {
      toast.error('Failed to set role');
    }
  };

  const handleCheck = async () => {
    if (!checkEmail || !checkTicket) return;
    try {
      const result = await checkAccess(checkEmail, checkTicket);
      setCheckResult(result);
    } catch (err) {
      toast.error('Check failed');
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
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Access Control</h1>
          <p className="text-gray-500 dark:text-gray-400 mt-1">
            Role-based permissions — who can see which tickets and context
          </p>
        </div>
        <button
          onClick={() => setShowAdd(true)}
          className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg"
        >
          <UserPlus size={16} /> Add User
        </button>
      </div>

      {/* Add User Form */}
      {showAdd && (
        <div className="mb-6 bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5">
          <h3 className="font-medium text-gray-900 dark:text-white mb-3">Add User Role</h3>
          <div className="grid grid-cols-4 gap-3">
            <input
              type="email"
              placeholder="Email"
              value={newEmail}
              onChange={(e) => setNewEmail(e.target.value)}
              className="px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-900 text-gray-900 dark:text-white text-sm"
            />
            <select
              value={newRole}
              onChange={(e) => setNewRole(e.target.value)}
              className="px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-900 text-gray-900 dark:text-white text-sm"
            >
              <option value="admin">Admin</option>
              <option value="lead">Team Lead</option>
              <option value="developer">Developer</option>
              <option value="intern">Intern</option>
            </select>
            <input
              type="text"
              placeholder="Team name"
              value={newTeam}
              onChange={(e) => setNewTeam(e.target.value)}
              className="px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-900 text-gray-900 dark:text-white text-sm"
            />
            <input
              type="text"
              placeholder="Allowed tickets (* = all)"
              value={newTickets}
              onChange={(e) => setNewTickets(e.target.value)}
              className="px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-900 text-gray-900 dark:text-white text-sm"
            />
          </div>
          <div className="flex gap-2 mt-3">
            <button onClick={handleAddRole} className="px-4 py-2 text-sm text-white bg-green-600 hover:bg-green-700 rounded-lg">
              Save
            </button>
            <button onClick={() => setShowAdd(false)} className="px-4 py-2 text-sm text-gray-600 dark:text-gray-400">
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Existing Roles */}
      <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden mb-8">
        <table className="w-full">
          <thead className="bg-gray-50 dark:bg-gray-900">
            <tr>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">User</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Role</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Team</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Access</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
            {Object.entries(roles).map(([email, info]) => (
              <tr key={email} className="hover:bg-gray-50 dark:hover:bg-gray-750">
                <td className="px-4 py-3 text-sm text-gray-900 dark:text-white">{email}</td>
                <td className="px-4 py-3">
                  <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${roleBadges[info.role] || 'bg-gray-100 text-gray-700'}`}>
                    {info.role}
                  </span>
                </td>
                <td className="px-4 py-3 text-sm text-gray-500 dark:text-gray-400">{info.team || '—'}</td>
                <td className="px-4 py-3 text-sm font-mono text-gray-500 dark:text-gray-400">{info.allowed_tickets}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Access Check Tool */}
      <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5">
        <h3 className="font-medium text-gray-900 dark:text-white mb-3 flex items-center gap-2">
          <Shield size={16} /> Check Access
        </h3>
        <div className="flex gap-3 items-end">
          <div className="flex-1">
            <label className="text-xs text-gray-500 dark:text-gray-400">Email</label>
            <input
              type="email"
              placeholder="user@example.com"
              value={checkEmail}
              onChange={(e) => setCheckEmail(e.target.value)}
              className="w-full mt-1 px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-900 text-gray-900 dark:text-white text-sm"
            />
          </div>
          <div className="flex-1">
            <label className="text-xs text-gray-500 dark:text-gray-400">Ticket Key</label>
            <input
              type="text"
              placeholder="KAN-1"
              value={checkTicket}
              onChange={(e) => setCheckTicket(e.target.value)}
              className="w-full mt-1 px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-900 text-gray-900 dark:text-white text-sm"
            />
          </div>
          <button onClick={handleCheck} className="px-4 py-2 text-sm text-white bg-blue-600 hover:bg-blue-700 rounded-lg">
            Check
          </button>
        </div>
        {checkResult && (
          <div className={`mt-3 p-3 rounded-lg flex items-center gap-2 ${
            checkResult.allowed
              ? 'bg-green-50 dark:bg-green-900/30 text-green-700 dark:text-green-300'
              : 'bg-red-50 dark:bg-red-900/30 text-red-700 dark:text-red-300'
          }`}>
            {checkResult.allowed ? <CheckCircle size={16} /> : <XCircle size={16} />}
            <span className="text-sm">{checkResult.allowed ? 'Allowed' : 'Denied'} — {checkResult.reason}</span>
          </div>
        )}
      </div>
    </div>
  );
}
