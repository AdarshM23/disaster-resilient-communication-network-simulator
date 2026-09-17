import { useCallback, useEffect, useState } from 'react';
import { Activity, CloudOff, RadioTower, RefreshCw } from 'lucide-react';
import { api } from './api';
import { ControlPanel } from './components/ControlPanel';
import { EventLog } from './components/EventLog';
import { MetricsDashboard } from './components/MetricsDashboard';
import { NetworkGraph } from './components/NetworkGraph';
import type {
  ComponentSelection, DisasterIntensity, DisasterType, EmergencyTrafficRequest,
  MetricsResponse, NodeType, SimulationEvent, TopologyResponse,
} from './types';

const POLL_INTERVAL_MS = 800;
const TYPE_NAMES: Record<NodeType, string> = {
  router: 'Router',
  switch: 'Switch',
  hospital: 'Hospital',
  police: 'Police Station',
  fire: 'Fire Station',
  rescue: 'Rescue Center',
  ambulance: 'Ambulance Station',
};

function App() {
  const [topology, setTopology] = useState<TopologyResponse | null>(null);
  const [metrics, setMetrics] = useState<MetricsResponse | null>(null);
  const [events, setEvents] = useState<SimulationEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [source, setSource] = useState('');
  const [destination, setDestination] = useState('');
  const [selection, setSelection] = useState<ComponentSelection | null>(null);
  const [service, setService] = useState<EmergencyTrafficRequest['service']>('ambulance');

  const refresh = useCallback(async (showError = false) => {
    try {
      const [nextTopology, nextMetrics, nextEvents] = await Promise.all([
        api.topology(), api.metrics(), api.events(),
      ]);
      setTopology(nextTopology);
      setMetrics(nextMetrics);
      setEvents(nextEvents.events);
      setConnected(true);
      setError(null);
    } catch (requestError) {
      setConnected(false);
      if (showError) setError(requestError instanceof Error ? requestError.message : 'Backend unavailable');
    }
  }, []);

  useEffect(() => {
    void refresh(true);
    const interval = window.setInterval(() => void refresh(false), POLL_INTERVAL_MS);
    return () => window.clearInterval(interval);
  }, [refresh]);

  useEffect(() => {
    if (!topology) return;
    const operationalNodes = topology.nodes.filter((node) => node.status === 'operational');
    if (!topology.nodes.some((node) => node.id === source)) {
      setSource(operationalNodes[0]?.id || topology.nodes[0]?.id || '');
    }
    if (!topology.nodes.some((node) => node.id === destination)) {
      setDestination(operationalNodes.at(-1)?.id || topology.nodes.at(-1)?.id || '');
    }
    if (selection) {
      const exists = selection.kind === 'node'
        ? topology.nodes.some((node) => node.id === selection.id)
        : topology.links.some((link) => link.id === selection.id);
      if (!exists) setSelection(null);
    }
  }, [destination, selection, source, topology]);

  const mutate = useCallback(async (operation: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await operation();
      await refresh(true);
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : 'Action failed');
    } finally {
      setBusy(false);
    }
  }, [refresh]);

  const handleAction = useCallback((action: string) => {
    const operations: Record<string, () => Promise<unknown>> = {
      start: api.start,
      pause: api.pause,
      reset: api.reset,
      normal: () => api.normalTraffic({ source, destination, count: 1 }),
      emergency: () => api.emergencyTraffic({ source, destination, count: 1, service }),
    };
    if (operations[action]) void mutate(operations[action]);
  }, [destination, mutate, service, source]);

  const addNode = useCallback((type: NodeType) => {
    if (!topology) return;
    let number = topology.nodes.filter((node) => node.type === type).length + 1;
    let id = `${type}-${number}`;
    while (topology.nodes.some((node) => node.id === id)) id = `${type}-${++number}`;
    const index = topology.nodes.length;
    void mutate(() => api.createNode({
      id,
      name: `${TYPE_NAMES[type]} ${number}`,
      type,
      x: 90 + (index % 5) * 155,
      y: 75 + Math.floor(index / 5) * 125,
    }));
    setSelection({ kind: 'node', id });
  }, [mutate, topology]);

  const connectNodes = useCallback((first: string, second: string) => {
    if (!topology || first === second) return;
    const endpoints = [first, second].sort();
    const parallel = topology.links.some((link) => (
      [link.source, link.destination].sort().join('|') === endpoints.join('|')
    ));
    if (parallel) {
      setError('Those components already have a communication link.');
      return;
    }
    const base = `${endpoints[0]}-${endpoints[1]}`;
    let id = base;
    let suffix = 2;
    while (topology.links.some((link) => link.id === id)) id = `${base}-${suffix++}`;
    void mutate(() => api.createLink({ id, source: first, destination: second, bandwidth: 1024, latency: 1 }));
    setSelection({ kind: 'link', id });
  }, [mutate, topology]);

  if (!topology || !metrics) {
    return (
      <main className="boot-screen">
        <div className="boot-mark"><RadioTower size={28} /></div>
        <h1>Resilient Network Command</h1>
        {connected ? <p>Loading simulation state…</p> : (
          <>
            <p>Waiting for the FastAPI backend at 127.0.0.1:8000</p>
            {error && <div className="boot-error"><CloudOff size={15} /> {error}</div>}
            <button className="button button--primary" onClick={() => void refresh(true)}><RefreshCw size={15} /> Retry connection</button>
          </>
        )}
      </main>
    );
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand">
          <div className="brand-mark"><RadioTower size={22} /></div>
          <div><span>Adaptive disaster-resilient</span><h1>Network Command</h1></div>
        </div>
        <div className="header-status">
          <div className={`connection-pill ${connected ? 'is-online' : 'is-offline'}`}><i /> {connected ? 'Backend connected' : 'Backend offline'}</div>
          <div className={`run-pill run-pill--${topology.simulation_status}`}><Activity size={14} /> {topology.simulation_status}</div>
          <div className="header-time">SIM T+{topology.time}s</div>
        </div>
      </header>

      {error && (
        <div className="error-banner" role="alert"><CloudOff size={16} /> {error}<button onClick={() => setError(null)} aria-label="Dismiss error">×</button></div>
      )}

      <main className="dashboard-grid">
        <NetworkGraph
          topology={topology}
          selection={selection}
          busy={busy}
          onSelect={setSelection}
          onAddNode={addNode}
          onConnect={connectNodes}
          onMoveNode={(id, x, y) => void mutate(() => api.updateNode(id, { x, y }))}
          onFailNode={(id) => void mutate(() => api.failNode(id))}
          onRecoverNode={(id) => void mutate(() => api.recoverNode(id))}
          onDeleteNode={(id) => void mutate(() => api.deleteNode(id))}
          onFailLink={(id) => void mutate(() => api.failLink(id))}
          onRecoverLink={(id) => void mutate(() => api.recoverLink(id))}
          onDeleteLink={(id) => void mutate(() => api.deleteLink(id))}
          onUpdateLink={(id, bandwidth, latency) => void mutate(() => api.updateLink(id, { bandwidth, latency }))}
        />
        <ControlPanel
          status={topology.simulation_status}
          nodes={topology.nodes}
          busy={busy}
          source={source}
          destination={destination}
          service={service}
          onSourceChange={setSource}
          onDestinationChange={setDestination}
          onServiceChange={setService}
          onAction={handleAction}
          onDisaster={(disaster: DisasterType, intensity: DisasterIntensity) => void mutate(() => api.triggerDisaster({ disaster, intensity }))}
        />
        <MetricsDashboard metrics={metrics} topology={topology} />
        <EventLog events={events} packets={topology.packets} />
      </main>

      <footer className="app-footer">
        <span>Engine state is authoritative · polling every {POLL_INTERVAL_MS} ms</span>
        <span>{topology.failures.length ? `${topology.failures.length} active failure${topology.failures.length === 1 ? '' : 's'}` : 'All systems nominal'}</span>
      </footer>
    </div>
  );
}

export default App;
