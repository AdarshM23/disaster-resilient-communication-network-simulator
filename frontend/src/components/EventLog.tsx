import { Clock3, Route, ScrollText, Zap } from 'lucide-react';
import type { PacketState, SimulationEvent } from '../types';

function path(route?: string[]) {
  return route?.length ? route.join(' → ') : 'unreachable';
}

function describe(event: SimulationEvent, packets: Map<number, PacketState>) {
  const packet = event.packet ? packets.get(event.packet) : undefined;
  const packetName = event.packet ? `P${event.packet}` : 'Packet';
  switch (event.kind) {
    case 'injected':
      return packet?.packet_class === 'emergency'
        ? `Emergency packet ${packetName} generated (${packet.traffic})`
        : `Packet ${packetName} generated`;
    case 'queued':
      return `Route ${path(event.route)} selected for ${packetName}`;
    case 'route_recalculated':
      return packet?.packet_class === 'emergency'
        ? `Emergency packet ${packetName} rerouted via ${path(event.route)}`
        : `Route recalculated for ${packetName}: ${path(event.route)}`;
    case 'node_failed':
      return `Node ${event.component} failed`;
    case 'node_restored':
      return `Node ${event.component} recovered`;
    case 'link_failed':
      return `Link ${event.component} failed`;
    case 'link_restored':
      return `Link ${event.component} recovered`;
    case 'transmitted':
      return event.priority === 'emergency'
        ? `Emergency packet ${packetName} dispatched with priority on ${event.link}`
        : `Packet ${packetName} transmitted on ${event.link}`;
    case 'arrived':
      return `Packet ${packetName} reached ${event.node}`;
    case 'delivered':
      return `${packet?.packet_class === 'emergency' ? 'Emergency packet' : 'Packet'} ${packetName} delivered`;
    case 'dropped':
      return `Packet ${packetName} dropped: ${event.reason}`;
    case 'bytes_transmitted':
      return `${event.size} bytes of ${packetName} sent on ${event.link}`;
    case 'disaster_triggered':
      return `${String(event.disaster).toUpperCase()} triggered · ${String(event.intensity).toUpperCase()} intensity`;
    case 'recalculating_routes':
      return 'Recalculating affected routes';
    case 'node_added':
      return `Node ${event.component} added to topology`;
    case 'link_added':
      return `Link ${event.component} added to topology`;
    case 'node_deleted':
      return `Node ${event.component} deleted`;
    case 'link_deleted':
      return `Link ${event.component} deleted`;
    case 'link_updated':
      return `Link ${event.component} properties updated`;
    default:
      return event.kind.replaceAll('_', ' ');
  }
}

function eventTone(event: SimulationEvent, packets: Map<number, PacketState>) {
  if (event.kind.includes('failed') || event.kind === 'dropped') return 'danger';
  if (event.kind === 'disaster_triggered') return 'danger';
  if (event.kind.includes('restored') || event.kind === 'delivered') return 'success';
  if (event.kind === 'route_recalculated') return 'route';
  if (event.packet && packets.get(event.packet)?.packet_class === 'emergency') return 'emergency';
  return 'neutral';
}

export function EventLog({ events, packets }: { events: SimulationEvent[]; packets: PacketState[] }) {
  const packetMap = new Map(packets.map((packet) => [packet.id, packet]));
  const visibleEvents = [...events].reverse().slice(0, 120);

  return (
    <section className="event-panel panel">
      <div className="panel-heading">
        <div>
          <span className="eyebrow">Engine event stream</span>
          <h2>Event log</h2>
        </div>
        <div className="event-count"><ScrollText size={15} /> {events.length} events</div>
      </div>
      <div className="event-list">
        {visibleEvents.length === 0 ? (
          <div className="empty-state">Start the simulation or generate traffic to populate the event stream.</div>
        ) : visibleEvents.map((event, index) => {
          const tone = eventTone(event, packetMap);
          return (
            <article className={`event-row event-row--${tone}`} key={`${event.time}-${event.kind}-${index}`}>
              <span className="event-row__icon">
                {tone === 'emergency' ? <Zap size={13} />
                  : tone === 'route' ? <Route size={13} />
                    : <Clock3 size={13} />}
              </span>
              <div>
                <p>{describe(event, packetMap)}</p>
                <small>T+{event.time}s · {event.kind}</small>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
