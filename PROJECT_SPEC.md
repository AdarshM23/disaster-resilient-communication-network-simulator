# Adaptive Disaster-Resilient Communication Network Simulator

## Architecture and implementation plan

The core is a deterministic Python engine with no third-party runtime dependencies. `simulator/engine.py` contains the models, adjacency-map graph, heap-based Dijkstra routing, queues, transmissions, measurements, and structured events. Networking logic is independent of web frameworks and visualization. Unit tests use Python unittest.

Implementation order:
1. Core models, configurable graph, Dijkstra, packet generation, transmission, and delivery — implemented.
2. Failure/recovery, congestion-aware routing, emergency scheduling, measured metrics, and core tests — implemented.
3. Later: FastAPI topology, packet injection, stepping, failure/recovery, and snapshot endpoints. One engine per simulation, serialized mutations.
4. Later: React graph visualization using snapshots/events, controls, and metric charts.

Only steps 1 and 2 are currently authorized. No API or frontend is implemented.

## Models and public controls

- `Node`: string `id`, display `name`, and `status` (`operational` or `failed`). String-only node configuration uses the ID as its name.
- `Link`: `id`, `source`, `destination`, positive integer `bandwidth` in bytes/second, positive integer propagation `latency` in seconds, and component `status`. `current_load` is bytes transmitted during the most recently processed tick. `utilization` is the cumulative fraction of available byte capacity consumed.
- `Packet`: generated integer `id`, source/destination IDs, `size` in bytes, `priority`/`packet_class` (`normal` or `emergency`), `creation_time`, nullable `delivery_time`, `route`, and `status` (`queued`, `in_flight`, `delivered`, or `dropped`). `route` is the latest planned route from a forwarding node; `path` is the actual sequence of visited nodes. Position, selected link queue, remaining serialization bytes, deadline, drop reason, and measured delivery latency are also exposed.
- `Network`: `nodes`, `links`, and `adjacency` dictionaries; `add_node`, `add_link`, `fail_node`, `recover_node`, `fail_link`, `recover_link`, and `route` methods. Links are undirected; self-loops and parallel links are rejected. An empty network can be populated incrementally. `from_dict` accepts node IDs or node objects and link configuration dictionaries.
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

## Measured metrics

All metrics derive from packet events and actual byte transmission; none are synthetic placeholders.

- `average_latency_seconds`: mean delivery time minus creation time for delivered packets; null before any delivery. `mean_latency_seconds` is retained as an alias.
- `emergency_packet_latency_seconds` and `normal_packet_latency_seconds`: independently measured mean delivery latency for delivered packets in each class; null until that class has a delivery. `traffic_classes` also reports generated, delivered, dropped, pending, and mean latency counts by class.
- `throughput_bps`: total delivered packet bytes times eight divided by elapsed seconds; zero at time zero. Lost or pending bytes do not count as delivered throughput.
- `packet_loss_percentage`: dropped packets divided by injected packets times 100; zero before injection. `packet_loss_ratio` exposes the same fraction without scaling.
- Link `utilization`: cumulative transmitted bytes divided by cumulative available bytes. Capacity accrues only when the link and both endpoints are operational. Null if no capacity has accrued. `last_tick_utilization` uses only the last tick's usage/capacity; `current_load` records that tick's transmitted bytes. Link metrics also expose queue depth, capacity, and per-class waiting counts. A later failure does not erase capacity already consumed.
- Packet conservation: injected = delivered + dropped + pending. Pending packets do not count as losses.

## Validation and demonstration

Run `python3 -m unittest discover -s tests -v` for model/graph controls, shortest paths, failure exclusions, rerouting, unreachable drops, recovery, real per-link emergency priority under heavy normal traffic, variable-size serialization, nonpreemption, shared bandwidth, queue overflow, per-class latency, exact throughput/utilization, conservation, deterministic execution, input validation, and snapshot isolation.

Run `python3 -m simulator` for a reproducible terminal demonstration of prioritized traffic, a failed primary link, backup routing, and restoration. It prints events, packet state, and measured metrics as JSON.

## Deliberate simplifications

This is an educational simulator, not a real network emulator. It uses whole-second tick resolution, undirected shared-bandwidth links, and centralized instantaneous route computation. It does not model sockets, TCP retransmission, routing-protocol convergence, or fragmentation. Histories remain in memory; bounded demonstration runs are expected. Future service work should add session and history limits.
