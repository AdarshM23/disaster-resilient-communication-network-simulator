# Adaptive Disaster-Resilient Communication Network Simulator

## Architecture and implementation plan

The core is a deterministic Python engine with no third-party runtime dependencies. `simulator/engine.py` contains the models, adjacency-map graph, heap-based Dijkstra routing, queues, transmissions, measurements, and structured events. Networking logic is independent of web frameworks and visualization. `backend/` is a thin FastAPI adapter that calls the engine's public controls and returns its snapshots, metrics, and events. Tests use Python unittest.

Implementation order:
1. Core models, configurable graph, Dijkstra, packet generation, transmission, and delivery — implemented.
2. Failure/recovery, congestion-aware routing, emergency scheduling, measured metrics, and core tests — implemented.
3. FastAPI topology, lifecycle, traffic injection, failure/recovery, metrics, and event endpoints — implemented. One engine instance is owned by the API manager and mutations are serialized.
4. React graph visualization using snapshots/events, controls, and metric charts — implemented.

All four demonstration layers are implemented.

## FastAPI backend

- `backend.app` exposes the engine through `GET /topology`, `GET /metrics`, `GET /events`, simulation start/pause/reset controls, normal/emergency traffic injection, and node/link failure and recovery controls. `POST/PATCH/DELETE /nodes` and `/links` are thin topology-editor adapters; `POST /disasters/trigger` delegates failure selection and mutation to the engine.
- The API manager owns one `Simulator`, protects it with an asynchronous lock, and advances it by one engine tick at each configured real-time interval while running. Pausing stops simulated-time advancement. Reset rebuilds the most recently edited topology at simulated time zero, clears packets and measurements, and returns components to operational health.
- `POST /simulation/start` without a body resumes the current run. Supplying a validated start body creates a fresh run with optional topology, tick interval, queue size, default packet size, lifetime, and congestion weight. If topology is omitted, the last configured topology is retained.
- `GET /topology` includes component health, link queues, active routes, packet state, active failures, and routing-change events. `/metrics` and `/events` expose measured engine output without recalculating or fabricating it in the API.
- Request and response schemas are defined with Pydantic in `backend/models.py` and appear in the generated OpenAPI document and interactive `/docs` page.
- Development and production-preview origins are enabled by default. Deployments can override the comma-separated allowlist with `FRONTEND_ORIGINS`.

## React frontend

- `frontend/` is a strict TypeScript React application built with Vite. React Flow is an interactive topology editor with a router/switch/emergency-service palette, draggable persisted positions, link creation, a click-driven inspector, and visible operational/failed components. Active routes, link queues, and normal/emergency packet markers come from backend snapshots.
- Start, pause, reset, traffic generation, topology edits, manual health controls, and disaster triggers call FastAPI directly. The browser does not maintain a second topology, advance time, choose routes, select disaster failures, move packets, or calculate metrics. React holds only transient canvas interaction state while dragging; drag completion persists the position before polling resumes authority.
- The dashboard polls `/topology`, `/metrics`, and `/events` every 800 milliseconds. Metrics, failure state, active routes, packets, and friendly event-log messages are projections of backend responses.
- The API base defaults to `http://127.0.0.1:8000` and can be changed at build time with `VITE_API_BASE_URL`.
- The interface is intended for a desktop demonstration and includes a topology legend, measured metric cards, per-link utilization bars, connection/run state, and a reverse-chronological event stream.

## Models and public controls

- `Node`: string `id`, display `name`, `status` (`operational` or `failed`), component `type`, and optional editor coordinates `x`/`y`. Supported types are router, switch, hospital, police, fire, rescue, and ambulance. All are generic graph vertices; the type describes their role and disaster targeting, not a separate routing implementation. String-only node configuration uses the ID as its name and router as its type.
- `Link`: `id`, `source`, `destination`, positive integer `bandwidth` in bytes/second, positive integer propagation `latency` in seconds, and component `status`. `current_load` is bytes transmitted during the most recently processed tick. `utilization` is the cumulative fraction of available byte capacity consumed.
- `Packet`: generated integer `id`, source/destination IDs, `size` in bytes, `priority`/`packet_class` (`normal` or `emergency`), `creation_time`, nullable `delivery_time`, `route`, and `status` (`queued`, `in_flight`, `delivered`, or `dropped`). `route` is the latest planned route from a forwarding node; `path` is the actual sequence of visited nodes. Position, selected link queue, remaining serialization bytes, deadline, drop reason, and measured delivery latency are also exposed.
- `Network`: `nodes`, `links`, and `adjacency` dictionaries; validated add/update/remove, fail/recover, and `route` methods. Links are undirected; self-loops and parallel links are rejected. An empty network can be populated incrementally. Deleting a node removes its incident links. Active packets affected by deletion are dropped with recorded reasons; other queued packets recalculate routes.
- `Simulator`: owns an independent copy of its input network. Use `sim.network` methods to alter an active simulation; these notify the engine so queues, failures, and events stay consistent. Direct mutation of model fields or graph dictionaries is unsupported. Nodes and links may be added between steps.
- `inject` generates a packet with optional size, class, and emergency service category. `normal` is the normal class. `emergency`, `hospital`, `ambulance`, `police`, `fire`, and `rescue` select the emergency class. `generate_packet` provides a simple size/priority interface. `step`, `metrics`, and `snapshot` advance and inspect the simulation. Snapshots are detached, JSON-serializable data.

## Simulation contract

- One tick represents one simulated second. Sizes and bandwidth are integer bytes and bytes/second. Both directions share a link's bandwidth.
- A link spends at most its bandwidth in bytes per tick. Packets larger than the bandwidth serialize across multiple ticks. Once serialization begins, it is not preempted. Unused capacity in a tick can serve another packet.
- Propagation begins after serialization finishes. Without contention, one-hop delivery takes `ceil(size / bandwidth) + latency` seconds. Propagating packets do not consume subsequent serialization capacity. Arriving packets can forward in the next step.
- Every queued packet waits in the queue of its route's next communication link. `queue_capacity` is the maximum number of waiting packets per link; overflow drops the incoming packet. Both directions share the same link queue and bandwidth.
- Link scheduling is strict emergency-first, with FIFO by queue arrival within each class. The ordering changes which packet actually consumes link bandwidth; latency is never adjusted merely for display. A normal packet whose serialization has already begun is not preempted, but emergency packets overtake all normal packets still waiting on that link. Normal traffic can starve under sustained emergencies. Hospital, ambulance, police, fire, and rescue traffic automatically receives emergency priority; explicitly downgrading it is rejected.
- Dijkstra uses propagation latency plus a nonnegative congestion penalty: congestion weight times the actual queued byte demand on a link divided by bandwidth. Unfinished serialization contributes remaining bytes. Weight zero selects minimum propagation latency. This heuristic does not guarantee minimum end-to-end delivery time.
- Each queued packet recalculates its route before forwarding. Failed links and nodes, including endpoints, are excluded. Failure and restoration controls also immediately recalculate queued routes.
- A `route_recalculated` event is recorded whenever a packet's planned remaining route actually changes. It includes the previous route, replacement route, and the reason; health-triggered changes also identify the failed or restored component. An empty replacement route is recorded before the packet is dropped as unreachable.
- A packet with no available route is dropped with reason `unreachable`, at injection, failure recalculation, forwarding, or arrival at an intermediate node. Recovery allows new traffic; it does not resurrect dropped packets.
- Node failure drops its queued packets and all packets serializing or propagating on incident links. Link failure drops packets on that link. Other in-flight packets complete their current hop and recalculate there.
- Packet lifetime is checked at tick boundaries before delivery. Arrival exactly at the deadline expires. Source-equals-destination delivers immediately if operational, without link usage.
- Configuration and control inputs are validated before mutation. Deterministic tie-breaking and event ordering make runs reproducible.

## Disaster presets

Disasters are understandable infrastructure-failure presets, not physical or scientific hazard models. Selection occurs in `Simulator.trigger_disaster`; every selected component is failed through the same `Network` health methods used by manual controls, so existing packet, routing, event, and metric behavior remains authoritative. Low, medium, and high intensity use increasing fractions of currently operational candidates. A seed makes demonstrations reproducible.

- Earthquake selects both nodes and links when those categories are available.
- Flood selects a small cluster nearest a seeded anchor using node positions and link midpoints; without coordinates it falls back to a deterministic mixed selection.
- Cyclone selects primarily links and a smaller number of nodes.
- Cyberattack selects primarily router and switch nodes, with a small secondary link effect.

The engine emits `disaster_triggered`, ordinary component failure and route-change events, and `recalculating_routes`. Failed components remain in topology snapshots. Packets that still have alternate paths reroute; unreachable packets follow the normal drop path. Recovery remains manual and does not revive dropped packets.

## Measured metrics

All metrics derive from packet events and actual byte transmission; none are synthetic placeholders.

- `average_latency_seconds`: mean delivery time minus creation time for delivered packets; null before any delivery. `mean_latency_seconds` is retained as an alias.
- `emergency_packet_latency_seconds` and `normal_packet_latency_seconds`: independently measured mean delivery latency for delivered packets in each class; null until that class has a delivery. `traffic_classes` also reports generated, delivered, dropped, pending, and mean latency counts by class.
- `throughput_bps`: total delivered packet bytes times eight divided by elapsed seconds; zero at time zero. Lost or pending bytes do not count as delivered throughput.
- `packet_loss_percentage`: dropped packets divided by injected packets times 100; zero before injection. `packet_loss_ratio` exposes the same fraction without scaling.
- Link `utilization`: cumulative transmitted bytes divided by cumulative available bytes. Capacity accrues only when the link and both endpoints are operational. Null if no capacity has accrued. `last_tick_utilization` uses only the last tick's usage/capacity; `current_load` records that tick's transmitted bytes. Link metrics also expose queue depth, capacity, and per-class waiting counts. A later failure does not erase capacity already consumed.
- Packet conservation: injected = delivered + dropped + pending. Pending packets do not count as losses.

## Validation and demonstration

Run `.venv/bin/python -m unittest discover -s tests -v` for the full engine and API suite: model/graph controls, editor CRUD and reset persistence, disaster selection and real failure mutation, shortest paths, failure exclusions, rerouting, unreachable drops, recovery, real per-link emergency priority under heavy normal traffic, variable-size serialization, nonpreemption, shared bandwidth, queue overflow, per-class latency, exact throughput/utilization, conservation, deterministic execution, API lifecycle/background ticking, traffic injection, health controls, schemas, validation, and snapshot isolation.

Run `npm install` and `npm run build` inside `frontend/` for dependency and strict TypeScript/production-bundle verification. `npm run dev` serves the development UI on port 5173; `npm run preview` serves the production bundle on port 4173.

Run `python3 -m simulator` for a reproducible terminal demonstration of prioritized traffic, a failed primary link, backup routing, and restoration. It prints events, packet state, and measured metrics as JSON.

## Deliberate simplifications

This is an educational simulator, not a real network emulator. It uses whole-second tick resolution, undirected shared-bandwidth links, centralized instantaneous route computation, and disaster presets based on component categories/proximity rather than physical models. It does not model sockets, TCP retransmission, routing-protocol convergence, fragmentation, geographic hazard propagation, or real cyberattack mechanics. The current API owns one in-memory simulation process and has no authentication or disk persistence; bounded demonstration runs are expected. Future service work should add sessions, authentication where appropriate, persistence, and history limits.
