import { BrowserRouter, Routes, Route } from 'react-router-dom';
import Layout from './components/Layout';
import Overview from './pages/Overview';
import Flow from './pages/Flow';
import Agents from './pages/Agents';
import Skills from './pages/Skills';
import Kanban from './pages/Kanban';
import Dispatch from './pages/Dispatch';
import Verticals from './pages/Verticals';
import Assess from './pages/Assess';
import Telemetry from './pages/Telemetry';

function App() {
  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/flow" element={<Flow />} />
          <Route path="/agents" element={<Agents />} />
          <Route path="/skills" element={<Skills />} />
          <Route path="/kanban" element={<Kanban />} />
          <Route path="/dispatch" element={<Dispatch />} />
          <Route path="/verticals" element={<Verticals />} />
          <Route path="/assess" element={<Assess />} />
          <Route path="/telemetry" element={<Telemetry />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  );
}

export default App;
