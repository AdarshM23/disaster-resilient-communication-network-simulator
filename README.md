# Adaptive Disaster-Resilient Communication Network Simulator

Python simulation engine and FastAPI backend for a Computer Networks academic project. Python 3.10 or newer.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m simulator
.venv/bin/python -m uvicorn backend.app:app --reload
cd frontend
npm install
npm run dev
```

The API documentation is available at `http://127.0.0.1:8000/docs`. It provides topology and frontend state, topology CRUD, disaster presets, start/pause/reset controls, normal and emergency traffic injection, node/link failure and recovery, measured metrics, and simulation events. `POST /simulation/start` accepts an optional topology and simulation configuration; without a body it resumes the current simulation.

The React application is available at `http://127.0.0.1:5173`. Its React Flow editor can add routers, switches, and emergency-service nodes; connect them; persist node positions; inspect, fail, recover, update, and delete components; and trigger earthquake, flood, cyclone, or cyberattack presets at three intensities. Failed components remain visible. All topology, packets, routes, failures, events, and metrics are read back from FastAPI. Set `VITE_API_BASE_URL` when the backend is not at `http://127.0.0.1:8000`. For production verification, run `npm run build` followed by `npm run preview` inside `frontend/`.

The demonstration prints packet events, routes, failures/recovery, and measured metrics as JSON. Packets wait in finite per-link queues, where emergency traffic is genuinely transmitted before waiting normal traffic. Queued packets reroute around failed components; unreachable packets are dropped with an explicit reason. Congestion-aware Dijkstra routing uses actual queued byte demand as a cost penalty.

```python
from simulator import Link, Network, Node, Simulator

network = Network()
network.add_node(Node("hospital", "City Hospital"))
network.add_node(Node("rescue", "Rescue Center"))
network.add_link(Link(
    "radio", source="hospital", destination="rescue",
    bandwidth=1024, latency=2,
))
sim = Simulator(network)
packet = sim.generate_packet(
    "hospital", "rescue", size=2048, priority="emergency",
)
sim.step(4)  # 2 seconds serialization + 2 seconds propagation
assert packet.status == "delivered"
print(sim.metrics())

sim.network.fail_link("radio")
lost = sim.inject("hospital", "rescue", traffic="ambulance")
assert lost.drop_reason == "unreachable"
sim.network.recover_link("radio")
```

Bandwidth is bytes per simulated second; packet size is bytes. Link `current_load` is bytes transmitted in the last tick, and utilization is a fraction from 0 to 1. Metrics report overall and per-class latency in seconds, throughput in bits/second, packet counts/loss, link utilization, and queue depth. Emergency services are `hospital`, `ambulance`, `police`, `fire`, and `rescue`; the generic `emergency` class is also accepted.

Use network methods to add, update, or remove topology components and change health. Each simulator owns an independent graph copy; modifying the original network does not alter an existing simulation. `snapshot()` returns detached JSON-serializable state. Emergency services are generic routing vertices with a descriptive node type, not hidden routers.

The link configuration uses `source`, `destination`, `bandwidth`, and `latency`. See [PROJECT_SPEC.md](PROJECT_SPEC.md) for the full simulation, API, and frontend contract.
