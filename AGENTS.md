# Project requirements and coding rules

Project: Adaptive Disaster-Resilient Communication Network Simulator.
Prioritize a reliable, demonstrable academic project and understandable code for a Computer Networks viva.

## Required final functionality
- Configurable graph of routers and communication links.
- Node and link failure and restoration.
- Dynamic routing around failures using Dijkstra shortest paths.
- Congestion-aware routing and traffic scheduling.
- Emergency priority for hospital, police, fire, rescue, and ambulance traffic.
- Visualization of packets, routes, failures, and restoration.
- Measured latency, throughput, packet loss, and link utilization. Never fabricate metrics.

## Architecture and scope
- Python simulation engine independent of networking APIs and visualization.
- Planned FastAPI backend and React frontend. Do not add unnecessary technologies.
- Current authorized implementation: core simulation engine and its tests only; no frontend or API yet.
- Document architecture, assumptions, metric definitions, and future implementation in PROJECT_SPEC.md.

## Coding rules
- Prefer small, readable functions, explicit types, and standard-library facilities.
- Routing must exclude failed nodes and links, including failed endpoints.
- Recompute routes for queued packets so failures and congestion affect subsequent transmissions.
- Drop unreachable packets with a recorded reason; recovery permits new traffic without reviving dropped packets.
- Model packet size in bytes and link bandwidth in bytes per simulated second; derive utilization from transmitted bytes.
- Change topology and health through Network methods so simulation state and events remain consistent.
- Distinguish simulated time and simulated traffic measurements from real network measurements.
- Use deterministic behavior and validate configuration before mutating state.
- Test core routing, congestion, priority, failures, restoration, and metric arithmetic.
- Run `python3 -m unittest discover -s tests -v` after engine changes.
- Keep documentation consistent with implemented behavior and explain simplifications honestly.
