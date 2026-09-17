import {
  Activity,
  Gauge,
  PackageCheck,
  PackageX,
  Timer,
  Unplug,
} from 'lucide-react';
import type { MetricsResponse, TopologyResponse } from '../types';

function formatLatency(value: number | null) {
  return value === null ? '—' : `${value.toFixed(2)} s`;
}

function formatThroughput(bitsPerSecond: number) {
  if (bitsPerSecond >= 1_000_000) return `${(bitsPerSecond / 1_000_000).toFixed(2)} Mbps`;
  if (bitsPerSecond >= 1_000) return `${(bitsPerSecond / 1_000).toFixed(2)} Kbps`;
  return `${bitsPerSecond.toFixed(0)} bps`;
}

export function MetricsDashboard({
  metrics,
  topology,
}: {
  metrics: MetricsResponse;
  topology: TopologyResponse;
}) {
  const cards = [
    { label: 'Average latency', value: formatLatency(metrics.average_latency_seconds), icon: Timer },
    { label: 'Throughput', value: formatThroughput(metrics.throughput_bps), icon: Activity },
    { label: 'Packet loss', value: `${metrics.packet_loss_percentage.toFixed(1)}%`, icon: Unplug },
    { label: 'Delivered', value: metrics.packets_delivered.toString(), icon: PackageCheck },
    { label: 'Dropped', value: metrics.packets_dropped.toString(), icon: PackageX },
  ];

  return (
    <section className="metrics-panel panel">
      <div className="panel-heading">
        <div>
          <span className="eyebrow">Measured telemetry</span>
          <h2>Metrics dashboard</h2>
        </div>
        <span className="sim-clock">T+{metrics.elapsed_seconds}s</span>
      </div>
      <div className="metric-layout">
        <div className="metric-cards">
          {cards.map(({ label, value, icon: Icon }) => (
            <article className="metric-card" key={label}>
              <Icon size={17} />
              <span>{label}</span>
              <strong>{value}</strong>
            </article>
          ))}
        </div>
        <div className="utilization-card">
          <div className="utilization-card__heading">
            <span><Gauge size={16} /> Link utilization</span>
            <small>cumulative transmitted / available</small>
          </div>
          <div className="utilization-list">
            {topology.links.map((link) => {
              const utilization = metrics.links[link.id]?.utilization;
              const percent = utilization === null || utilization === undefined
                ? 0
                : Math.min(100, utilization * 100);
              return (
                <div className="utilization-row" key={link.id}>
                  <div>
                    <span>{link.id}</span>
                    <small>{utilization === null || utilization === undefined ? 'No capacity yet' : `${percent.toFixed(1)}%`}</small>
                  </div>
                  <div className="utilization-track">
                    <i
                      className={link.status === 'failed' ? 'is-failed' : ''}
                      style={{ width: `${percent}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </section>
  );
}
