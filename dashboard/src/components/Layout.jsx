import { useState, useEffect } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { LayoutDashboard, Ticket, Hash, GitBranch, Shield, Moon, Sun } from 'lucide-react';

const navItems = [
  { path: '/', label: 'Dashboard', icon: LayoutDashboard },
  { path: '/tickets', label: 'Tickets & Sessions', icon: Ticket },
  { path: '/slack', label: 'Slack Channels', icon: Hash },
  { path: '/git', label: 'Git Activity', icon: GitBranch },
  { path: '/access', label: 'Access Control', icon: Shield },
];

export default function Layout({ children }) {
  const location = useLocation();
  const [dark, setDark] = useState(() => localStorage.getItem('flux-theme') === 'dark');

  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark);
    localStorage.setItem('flux-theme', dark ? 'dark' : 'light');
  }, [dark]);

  return (
    <div className="min-h-screen flex">
      {/* Sidebar */}
      <aside className="w-64 bg-white dark:bg-gray-900 flex flex-col border-r border-gray-200 dark:border-gray-700 fixed h-full">
        <div className="p-6 border-b border-gray-200 dark:border-gray-700">
          <h1 className="text-xl font-bold text-gray-900 dark:text-white">⚡ Flux</h1>
          <p className="text-gray-500 dark:text-gray-400 text-sm mt-1">From ticket to code, automatically</p>
        </div>
        <nav className="flex-1 p-4 overflow-y-auto">
          {navItems.map(({ path, label, icon: Icon }) => (
            <Link
              key={path}
              to={path}
              className={`flex items-center gap-3 px-4 py-3 rounded-lg mb-1 transition-colors ${
                location.pathname === path
                  ? 'bg-indigo-50 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300 font-medium'
                  : 'text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800'
              }`}
            >
              <Icon size={20} />
              <span>{label}</span>
            </Link>
          ))}
        </nav>
        <div className="p-4 border-t border-gray-200 dark:border-gray-700">
          <button
            onClick={() => setDark(!dark)}
            className="flex items-center gap-3 px-4 py-2 rounded-lg w-full text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
          >
            {dark ? <Sun size={20} /> : <Moon size={20} />}
            <span>{dark ? 'Light Mode' : 'Dark Mode'}</span>
          </button>
        </div>
        <div className="p-4 border-t border-gray-200 dark:border-gray-700 text-xs text-gray-400">
          Flux v1.0 • Microsoft Build AI Hackathon 2026
        </div>
      </aside>

      {/* Main Content */}
      <main className="flex-1 ml-64 overflow-auto">
        <div className="p-8">
          {children}
        </div>
      </main>
    </div>
  );
}
