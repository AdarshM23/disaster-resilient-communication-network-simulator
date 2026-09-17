export type HealthStatus = 'operational' | 'failed';
export type SimulationStatus = 'running' | 'paused';
export type PacketClass = 'normal' | 'emergency';
export type PacketStatus = 'queued' | 'in_flight' | 'delivered' | 'dropped';
export type NodeType = 'router' | 'switch' | 'hospital' | 'police' | 'fire' | 'rescue' | 'ambulance';
export type DisasterType = 'earthquake' | 'flood' | 'cyclone' | 'cyberattack';
export type DisasterIntensity = 'low' | 'medium' | 'high';

export interface NodeState {
  id: string;
  name: string;
  status: HealthStatus;
  type: NodeType;
  x: number | null;
  y: number | null;
}

export interface LinkState {
  id: string;
  source: string;
  destination: string;
  bandwidth: number;
  latency: number;
  status: HealthStatus;
  current_load: number;
  transmitted_bytes: number;
  available_bytes: number;
  last_available_bytes: number;
  utilization: number | null;
  queue: number[];
}

export interface PacketState {
  id: number;
  source: string;
  destination: string;
  size: number;
  priority: PacketClass;
  packet_class: PacketClass;
  traffic: string;
  creation_time: number;
  deadline: number;
  node: string | null;
  delivery_time: number | null;
  latency_seconds: number | null;
  route: string[];
  status: PacketStatus;
  path: string[];
  link: string | null;
  queued_link: string | null;
  next_node: string | null;
  arrives_at: number | null;
  remaining_bytes: number;
  drop_reason: string | null;
  queue_order: number;
}

export interface ActiveRoute {
  packet: number;
  status: 'queued' | 'in_flight';
  route: string[];
  path: string[];
  node: string | null;
  link: string | null;
  queued_link: string | null;
}

export interface FailureState {
  component_type: 'node' | 'link';
  component: string;
}

export interface SimulationEvent {
  time: number;
  kind: string;
  packet?: number;
  component?: string;
  link?: string;
  node?: string;
  priority?: PacketClass;
  route?: string[];
  previous_route?: string[];
  reason?: string;
  size?: number;
  [key: string]: unknown;
}

export interface TopologyResponse {
  time: number;
  simulation_status: SimulationStatus;
  nodes: NodeState[];
  links: LinkState[];
  active_routes: ActiveRoute[];
  packets: PacketState[];
  failures: FailureState[];
  routing_changes: SimulationEvent[];
}

export interface TrafficClassMetrics {
  generated: number;
  delivered: number;
  dropped: number;
  pending: number;
  average_latency_seconds: number | null;
}

export interface LinkMetrics {
  transmitted_bytes: number;
  available_bytes: number;
  current_load: number;
  utilization: number | null;
  queue_depth: number;
  queue_capacity: number;
  queued_normal: number;
  queued_emergency: number;
  last_tick_utilization: number | null;
}

export interface MetricsResponse {
  elapsed_seconds: number;
  packets_generated: number;
  packets_delivered: number;
  packets_dropped: number;
  pending: number;
  average_latency_seconds: number | null;
  emergency_packet_latency_seconds: number | null;
  normal_packet_latency_seconds: number | null;
  throughput_bps: number;
  packet_loss_percentage: number;
  traffic_classes: Record<PacketClass, TrafficClassMetrics>;
  links: Record<string, LinkMetrics>;
}

export interface EventsResponse {
  count: number;
  events: SimulationEvent[];
}

export interface TrafficRequest {
  source: string;
  destination: string;
  size?: number;
  count: number;
}

export interface EmergencyTrafficRequest extends TrafficRequest {
  service: 'emergency' | 'hospital' | 'ambulance' | 'police' | 'fire' | 'rescue';
}

export interface CreateNodeRequest {
  id: string;
  name: string;
  type: NodeType;
  x: number;
  y: number;
}

export interface CreateLinkRequest {
  id: string;
  source: string;
  destination: string;
  bandwidth?: number;
  latency?: number;
}

export interface DisasterRequest {
  disaster: DisasterType;
  intensity: DisasterIntensity;
  seed?: number;
}

export interface DisasterResponse {
  disaster: DisasterType;
  intensity: DisasterIntensity;
  failed_nodes: string[];
  failed_links: string[];
  topology: TopologyResponse;
}

export type ComponentSelection =
  | { kind: 'node'; id: string }
  | { kind: 'link'; id: string };
