import type {
  CreateLinkRequest,
  CreateNodeRequest,
  DisasterRequest,
  DisasterResponse,
  EmergencyTrafficRequest,
  EventsResponse,
  MetricsResponse,
  TopologyResponse,
  TrafficRequest,
} from './types';

const API_BASE = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body !== undefined) {
    headers.set('Content-Type', 'application/json');
  }
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers,
  });
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json() as { detail?: string };
      message = body.detail || message;
    } catch {
      // Preserve the HTTP status when an error body is not JSON.
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export const api = {
  topology: () => request<TopologyResponse>('/topology'),
  metrics: () => request<MetricsResponse>('/metrics'),
  events: () => request<EventsResponse>('/events?since=0&limit=1000'),
  start: () => request('/simulation/start', { method: 'POST' }),
  pause: () => request('/simulation/pause', { method: 'POST' }),
  reset: () => request('/simulation/reset', { method: 'POST' }),
  normalTraffic: (payload: TrafficRequest) => request('/traffic/normal', {
    method: 'POST',
    body: JSON.stringify(payload),
  }),
  emergencyTraffic: (payload: EmergencyTrafficRequest) => request('/traffic/emergency', {
    method: 'POST',
    body: JSON.stringify(payload),
  }),
  failNode: (id: string) => request(`/nodes/${encodeURIComponent(id)}/fail`, { method: 'POST' }),
  recoverNode: (id: string) => request(`/nodes/${encodeURIComponent(id)}/recover`, { method: 'POST' }),
  failLink: (id: string) => request(`/links/${encodeURIComponent(id)}/fail`, { method: 'POST' }),
  recoverLink: (id: string) => request(`/links/${encodeURIComponent(id)}/recover`, { method: 'POST' }),
  createNode: (payload: CreateNodeRequest) => request<TopologyResponse>('/nodes', {
    method: 'POST', body: JSON.stringify(payload),
  }),
  updateNode: (id: string, payload: Partial<Pick<CreateNodeRequest, 'name' | 'type' | 'x' | 'y'>>) => (
    request<TopologyResponse>(`/nodes/${encodeURIComponent(id)}`, {
      method: 'PATCH', body: JSON.stringify(payload),
    })
  ),
  deleteNode: (id: string) => request<TopologyResponse>(`/nodes/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  }),
  createLink: (payload: CreateLinkRequest) => request<TopologyResponse>('/links', {
    method: 'POST', body: JSON.stringify(payload),
  }),
  updateLink: (id: string, payload: { bandwidth?: number; latency?: number }) => (
    request<TopologyResponse>(`/links/${encodeURIComponent(id)}`, {
      method: 'PATCH', body: JSON.stringify(payload),
    })
  ),
  deleteLink: (id: string) => request<TopologyResponse>(`/links/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  }),
  triggerDisaster: (payload: DisasterRequest) => request<DisasterResponse>('/disasters/trigger', {
    method: 'POST', body: JSON.stringify(payload),
  }),
};
