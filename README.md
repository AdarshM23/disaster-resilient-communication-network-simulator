# Adaptive Disaster-Resilient Communication Network Simulator

Core Python engine for a Computer Networks academic project. Python 3.10 or newer; no external dependencies.

```sh
python3 -m unittest discover -s tests -v
python3 -m simulator
```

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

Use network methods to change topology or component health. Each simulator owns an independent graph copy; modifying the original network does not alter an existing simulation. `snapshot()` returns detached JSON-serializable state.

The link configuration now uses `source`, `destination`, `bandwidth`, and `latency` in place of the original `a`, `b`, packet `capacity`, and `delay` fields. See [PROJECT_SPEC.md](PROJECT_SPEC.md) for the full simulation contract and planned FastAPI/React architecture. No frontend or API is implemented.
