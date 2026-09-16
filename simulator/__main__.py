"""Run a small, reproducible disaster and restoration demonstration."""

import json

from .engine import Link, Network, Simulator


def main():
    sim = Simulator(Network(["Hospital", "Router", "Backup", "Rescue"], [
        Link("primary", "Hospital", "Router"),
        Link("uplink", "Router", "Rescue"),
        Link("backup", "Hospital", "Backup", latency=2),
        Link("backup-uplink", "Backup", "Rescue"),
    ]), congestion_weight=0.25)
    sim.inject("Hospital", "Rescue")
    sim.inject("Hospital", "Rescue", "ambulance")
    sim.step()
    sim.set_link_active("primary", False)
    sim.inject("Hospital", "Rescue", "hospital")
    sim.step(7)
    sim.set_link_active("primary", True)
    sim.inject("Hospital", "Rescue", "rescue")
    sim.step(5)
    print(json.dumps(sim.snapshot(), indent=2))


if __name__ == "__main__":
    main()
