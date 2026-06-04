import { useState, useEffect } from 'react';
import { getGitBranches, getGitCommits } from '../api/engmemory';
import { GitBranch, GitCommit, Clock, User } from 'lucide-react';

export default function GitActivity() {
  const [branches, setBranches] = useState([]);
  const [currentBranch, setCurrentBranch] = useState('');
  const [commits, setCommits] = useState([]);
  const [selectedBranch, setSelectedBranch] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    try {
      const [branchData, commitData] = await Promise.all([
        getGitBranches(),
        getGitCommits(null, 20),
      ]);
      setBranches(branchData.branches || []);
      setCurrentBranch(branchData.current || '');
      setCommits(commitData.commits || []);
    } catch (err) {
      console.error('Failed to load git data:', err);
    } finally {
      setLoading(false);
    }
  };

  const loadBranchCommits = async (branch) => {
    setSelectedBranch(branch);
    try {
      const data = await getGitCommits(branch, 20);
      setCommits(data.commits || []);
    } catch (err) {
      console.error('Failed:', err);
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
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Git Activity</h1>
        <p className="text-gray-500 dark:text-gray-400 mt-1">
          Branches and commits tracked by Flux
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Branches */}
        <div className="lg:col-span-1">
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
            <div className="p-4 border-b border-gray-200 dark:border-gray-700">
              <h2 className="font-medium text-gray-900 dark:text-white flex items-center gap-2">
                <GitBranch size={16} /> Branches ({branches.length})
              </h2>
            </div>
            <div className="max-h-96 overflow-y-auto">
              {branches.map((branch) => (
                <div
                  key={branch}
                  onClick={() => loadBranchCommits(branch)}
                  className={`px-4 py-3 border-b border-gray-100 dark:border-gray-700 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-750 transition-colors ${
                    (selectedBranch || currentBranch) === branch ? 'bg-blue-50 dark:bg-gray-700' : ''
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <GitBranch size={14} className={branch === currentBranch ? 'text-green-500' : 'text-gray-400'} />
                    <span className="text-sm font-mono text-gray-900 dark:text-white truncate">
                      {branch}
                    </span>
                    {branch === currentBranch && (
                      <span className="text-xs px-1.5 py-0.5 rounded bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300">
                        current
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Commits */}
        <div className="lg:col-span-2">
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
            <div className="p-4 border-b border-gray-200 dark:border-gray-700">
              <h2 className="font-medium text-gray-900 dark:text-white flex items-center gap-2">
                <GitCommit size={16} /> Recent Commits
                {selectedBranch && (
                  <span className="text-xs text-gray-400 font-normal">on {selectedBranch}</span>
                )}
              </h2>
            </div>
            <div className="divide-y divide-gray-100 dark:divide-gray-700">
              {commits.map((commit, i) => (
                <div key={i} className="px-4 py-3 hover:bg-gray-50 dark:hover:bg-gray-750">
                  <div className="flex items-start gap-3">
                    <div className="mt-1">
                      <div className="w-6 h-6 bg-gray-100 dark:bg-gray-700 rounded-full flex items-center justify-center">
                        <GitCommit size={12} className="text-gray-500" />
                      </div>
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-gray-900 dark:text-white">{commit.message}</p>
                      <div className="flex items-center gap-3 mt-1">
                        <span className="text-xs text-gray-400 font-mono">{commit.sha}</span>
                        <span className="text-xs text-gray-400 flex items-center gap-1">
                          <User size={10} /> {commit.author}
                        </span>
                        <span className="text-xs text-gray-400 flex items-center gap-1">
                          <Clock size={10} /> {commit.time_ago}
                        </span>
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
