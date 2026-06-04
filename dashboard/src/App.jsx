import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import { Toaster } from 'react-hot-toast';
import Layout from './components/Layout';
import Dashboard from './pages/Dashboard';
import TicketSessions from './pages/TicketSessions';
import SlackChannels from './pages/SlackChannels';
import GitActivity from './pages/GitActivity';
import AccessControl from './pages/AccessControl';

function App() {
  return (
    <Router>
      <Toaster position="top-right" />
      <Layout>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/tickets" element={<TicketSessions />} />
          <Route path="/slack" element={<SlackChannels />} />
          <Route path="/git" element={<GitActivity />} />
          <Route path="/access" element={<AccessControl />} />
        </Routes>
      </Layout>
    </Router>
  );
}

export default App;
