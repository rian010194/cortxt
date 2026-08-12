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

type RouteDef = {
  path: string;
  Component: React.FC;
};

export const ROUTES: RouteDef[] = [
  { path: '/', Component: Overview },
  { path: '/flow', Component: Flow },
  { path: '/agents', Component: Agents },
  { path: '/skills', Component: Skills },
  { path: '/kanban', Component: Kanban },
  { path: '/dispatch', Component: Dispatch },
  { path: '/verticals', Component: Verticals },
  { path: '/assess', Component: Assess },
  { path: '/telemetry', Component: Telemetry },
];

function App() {
  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          {ROUTES.map((route) => (
            <Route key={route.path} path={route.path} element={<route.Component />} />
          ))}
        </Routes>
      </Layout>
    </BrowserRouter>
  );
}

export default App;
