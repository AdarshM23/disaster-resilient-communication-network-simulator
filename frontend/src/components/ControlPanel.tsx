import { useState } from 'react';
import {
  Ambulance, CirclePause, CirclePlay, CloudLightning, Radio, RotateCcw, Send,
} from 'lucide-react';
import type {
  DisasterIntensity, DisasterType, EmergencyTrafficRequest, NodeState, SimulationStatus,
} from '../types';

type ControlPanelProps = {
  status: SimulationStatus;
  nodes: NodeState[];
  busy: boolean;
  source: string;
  destination: string;
  service: EmergencyTrafficRequest['service'];
  onSourceChange: (value: string) => void;
  onDestinationChange: (value: string) => void;
  onServiceChange: (value: EmergencyTrafficRequest['service']) => void;
  onAction: (action: string) => void;
  onDisaster: (disaster: DisasterType, intensity: DisasterIntensity) => void;
};

const emergencyServices: EmergencyTrafficRequest['service'][] = [
  'emergency', 'hospital', 'ambulance', 'police', 'fire', 'rescue',
];
const disasterTypes: DisasterType[] = ['earthquake', 'flood', 'cyclone', 'cyberattack'];
const intensities: DisasterIntensity[] = ['low', 'medium', 'high'];

export function ControlPanel(props: ControlPanelProps) {
  const [disaster, setDisaster] = useState<DisasterType>('earthquake');
  const [intensity, setIntensity] = useState<DisasterIntensity>('medium');
  const noRouteEndpoints = !props.source || !props.destination;

  return (
    <aside className="controls-panel panel">
      <div className="panel-heading">
        <div><span className="eyebrow">Command center</span><h2>Simulation controls</h2></div>
        <Radio size={18} />
      </div>

      <section className="control-section">
        <h3>Timeline</h3>
        <div className="button-grid button-grid--three">
          <button className="button button--primary" disabled={props.busy || props.status === 'running'} onClick={() => props.onAction('start')}>
            <CirclePlay size={16} /> Start
          </button>
          <button className="button" disabled={props.busy || props.status === 'paused'} onClick={() => props.onAction('pause')}>
            <CirclePause size={16} /> Pause
          </button>
          <button className="button" disabled={props.busy} onClick={() => props.onAction('reset')}>
            <RotateCcw size={16} /> Reset
          </button>
        </div>
      </section>

      <section className="control-section">
        <h3>Traffic injection</h3>
        <div className="field-row">
          <label>Source
            <select value={props.source} onChange={(event) => props.onSourceChange(event.target.value)}>
              {props.nodes.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
            </select>
          </label>
          <label>Destination
            <select value={props.destination} onChange={(event) => props.onDestinationChange(event.target.value)}>
              {props.nodes.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
            </select>
          </label>
        </div>
        <label>Emergency service
          <select value={props.service} onChange={(event) => props.onServiceChange(event.target.value as EmergencyTrafficRequest['service'])}>
            {emergencyServices.map((item) => <option key={item} value={item}>{item[0].toUpperCase() + item.slice(1)}</option>)}
          </select>
        </label>
        <div className="button-stack">
          <button className="button button--normal" disabled={props.busy || noRouteEndpoints} onClick={() => props.onAction('normal')}>
            <Send size={16} /> Generate normal traffic
          </button>
          <button className="button button--emergency" disabled={props.busy || noRouteEndpoints} onClick={() => props.onAction('emergency')}>
            <Ambulance size={17} /> Generate emergency traffic
          </button>
        </div>
      </section>

      <section className="control-section disaster-controls">
        <h3>Disaster simulation</h3>
        <p>Educational infrastructure-failure presets. The backend selects and fails real components.</p>
        <div className="field-row">
          <label>Preset
            <select value={disaster} onChange={(event) => setDisaster(event.target.value as DisasterType)}>
              {disasterTypes.map((item) => <option key={item} value={item}>{item[0].toUpperCase() + item.slice(1)}</option>)}
            </select>
          </label>
          <label>Intensity
            <select value={intensity} onChange={(event) => setIntensity(event.target.value as DisasterIntensity)}>
              {intensities.map((item) => <option key={item} value={item}>{item.toUpperCase()}</option>)}
            </select>
          </label>
        </div>
        <button className="button button--danger disaster-button" disabled={props.busy} onClick={() => props.onDisaster(disaster, intensity)}>
          <CloudLightning size={17} /> Trigger {disaster}
        </button>
      </section>
    </aside>
  );
}
