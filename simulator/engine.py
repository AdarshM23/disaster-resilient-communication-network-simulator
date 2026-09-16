"""Deterministic graph routing and store-and-forward packet simulation.

One tick is one simulated second. Sizes and bandwidth use bytes and bytes/second.
"""

from copy import deepcopy
from dataclasses import asdict, dataclass, field
import heapq
import math
from typing import Callable


def positive_integer(value: int, name: str) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def valid_id(value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("IDs must be nonempty strings")


def valid_status(status: str) -> None:
    if status not in ("operational", "failed"):
        raise ValueError("status must be operational or failed")


@dataclass
class Node:
    id: str
    name: str
    status: str = "operational"

    def __post_init__(self):
        valid_id(self.id)
        valid_id(self.name)
        valid_status(self.status)


@dataclass
class Link:
    id: str
    source: str
    destination: str
    bandwidth: int = 1024
    latency: int = 1
    status: str = "operational"
    current_load: int = field(default=0, init=False)
    transmitted_bytes: int = field(default=0, init=False)
    available_bytes: int = field(default=0, init=False)
    last_available_bytes: int = field(default=0, init=False)

    def __post_init__(self):
        for value in (self.id, self.source, self.destination):
            valid_id(value)
        if self.source == self.destination:
            raise ValueError("link endpoints must be distinct")
        positive_integer(self.bandwidth, "bandwidth")
        positive_integer(self.latency, "latency")
        valid_status(self.status)

    @property
    def utilization(self) -> float | None:
        """Cumulative fraction of operational bandwidth consumed."""
        return self.transmitted_bytes / self.available_bytes if self.available_bytes else None


class Network:
    """Simple undirected graph with validated topology and health controls."""

    def __init__(self, nodes: list[Node | str] | None = None,
                 links: list[Link] | None = None):
        self.nodes: dict[str, Node] = {}
        self.links: dict[str, Link] = {}
        self.adjacency: dict[str, dict[str, str]] = {}
        self._on_change: Callable | None = None
        for node in nodes or []:
            self.add_node(node)
        for link in links or []:
            self.add_link(link)

    def add_node(self, node: Node | str) -> Node:
        node = Node(node, node) if isinstance(node, str) else Node(**asdict(node))
        if node.id in self.nodes:
            raise ValueError("duplicate node ID")
        self.nodes[node.id] = node
        self.adjacency[node.id] = {}
        self._notify("node_added", node.id)
        return node

    def add_link(self, link: Link) -> Link:
        link = Link(link.id, link.source, link.destination, link.bandwidth,
                    link.latency, link.status)
        if link.id in self.links:
            raise ValueError("duplicate link ID")
        if link.source not in self.nodes or link.destination not in self.nodes:
            raise ValueError("unknown link endpoint")
        if link.destination in self.adjacency[link.source]:
            raise ValueError("parallel links are not supported")
        self.links[link.id] = link
        self.adjacency[link.source][link.destination] = link.id
        self.adjacency[link.destination][link.source] = link.id
        self._notify("link_added", link.id)
        return link

    @classmethod
    def from_dict(cls, configuration: dict) -> "Network":
        nodes = [Node(**n) if isinstance(n, dict) else n for n in configuration["nodes"]]
        return cls(nodes, [Link(**item) for item in configuration["links"]])

    def _notify(self, kind: str, component: str) -> None:
        if self._on_change is not None:
            self._on_change(kind, component)

    def _set_status(self, components: dict, component: str, status: str, kind: str) -> None:
        if component not in components:
            raise ValueError(f"unknown {kind} ID")
        if components[component].status == status:
            return
        components[component].status = status
        self._notify(f"{kind}_{'failed' if status == 'failed' else 'restored'}", component)

    def fail_node(self, node_id: str) -> None:
        self._set_status(self.nodes, node_id, "failed", "node")

    def recover_node(self, node_id: str) -> None:
        self._set_status(self.nodes, node_id, "operational", "node")

    def fail_link(self, link_id: str) -> None:
        self._set_status(self.links, link_id, "failed", "link")

    def recover_link(self, link_id: str) -> None:
        self._set_status(self.links, link_id, "operational", "link")

    def operational(self, link: Link) -> bool:
        return (link.status == "operational"
                and self.nodes[link.source].status == "operational"
                and self.nodes[link.destination].status == "operational")

    def route(self, source: str, destination: str,
              penalties: dict[str, float] | None = None) -> list[str]:
        """Dijkstra using link latency plus optional nonnegative congestion costs."""
        if source not in self.nodes or destination not in self.nodes:
            raise ValueError("unknown routing endpoint")
        penalties = penalties or {}
        if any(not math.isfinite(v) or v < 0 for v in penalties.values()):
            raise ValueError("routing penalties must be finite and nonnegative")
        if any(self.nodes[n].status == "failed" for n in (source, destination)):
            return []
        distances = {source: 0.0}
        previous: dict[str, str] = {}
        heap = [(0.0, source)]
        while heap:
            distance, node = heapq.heappop(heap)
            if distance != distances[node]:
                continue
            if node == destination:
                path = [node]
                while node != source:
                    node = previous[node]
                    path.append(node)
                return path[::-1]
            for neighbor, link_id in sorted(self.adjacency[node].items()):
                link = self.links[link_id]
                if not self.operational(link):
                    continue
                candidate = distance + link.latency + penalties.get(link_id, 0)
                if candidate < distances.get(neighbor, math.inf):
                    distances[neighbor] = candidate
                    previous[neighbor] = node
                    heapq.heappush(heap, (candidate, neighbor))
        return []


@dataclass
class Packet:
    id: int
    source: str
    destination: str
    size: int
    priority: str
    creation_time: int
    deadline: int
    node: str | None
    traffic: str = "normal"
    delivery_time: int | None = None
    route: list[str] = field(default_factory=list)
    status: str = "queued"
    path: list[str] = field(default_factory=list)
    link: str | None = None
    next_node: str | None = None
    arrives_at: int | None = None
    remaining_bytes: int = 0
    drop_reason: str | None = None
    queue_order: int = 0

    @property
    def created_at(self) -> int:
        return self.creation_time

    @property
    def delivered_at(self) -> int | None:
        return self.delivery_time


class Simulator:
    EMERGENCY = frozenset({"hospital", "police", "fire", "rescue", "ambulance"})

    def __init__(self, network: Network, queue_capacity: int = 100,
                 packet_bytes: int = 1024, lifetime: int = 60,
                 congestion_weight: float = 1.0):
        for name, value in (("queue_capacity", queue_capacity),
                            ("packet_bytes", packet_bytes), ("lifetime", lifetime)):
            positive_integer(value, name)
        if not math.isfinite(congestion_weight) or congestion_weight < 0:
            raise ValueError("congestion_weight must be finite and nonnegative")
        self.network = Network(list(network.nodes.values()), list(network.links.values()))
        self.queue_capacity = queue_capacity
        self.packet_bytes = packet_bytes
        self.lifetime = lifetime
        self.congestion_weight = congestion_weight
        self.time = 0
        self.packets: dict[int, Packet] = {}
        self.queues: dict[str, list[int]] = {node: [] for node in network.nodes}
        self.events: list[dict] = []
        self._queue_sequence = 0
        self.network._on_change = self._network_changed

    def _event(self, kind: str, **details) -> None:
        self.events.append({"time": self.time, "kind": kind, **details})

    def inject(self, source: str, destination: str, traffic: str = "normal", *,
               size: int | None = None, priority: str | None = None) -> Packet:
        if source not in self.network.nodes or destination not in self.network.nodes:
            raise ValueError("unknown packet endpoint")
        if traffic not in self.EMERGENCY | {"normal"}:
            raise ValueError("unknown traffic class")
        size = self.packet_bytes if size is None else size
        positive_integer(size, "packet size")
        priority = ("emergency" if traffic in self.EMERGENCY else "normal") if priority is None else priority
        if priority not in ("normal", "emergency"):
            raise ValueError("priority must be normal or emergency")
        if traffic in self.EMERGENCY and priority != "emergency":
            raise ValueError("emergency traffic must have emergency priority")
        packet = Packet(len(self.packets) + 1, source, destination, size, priority,
                        self.time, self.time + self.lifetime, source, traffic=traffic,
                        path=[source], route=self.network.route(source, destination))
        self.packets[packet.id] = packet
        self._event("injected", packet=packet.id)
        if self.network.nodes[source].status == "failed":
            self._drop(packet, "source_failed")
        elif not packet.route:
            self._drop(packet, "unreachable")
        elif source == destination:
            self._deliver(packet)
        else:
            self._enqueue(packet, source)
        return packet

    def generate_packet(self, source: str, destination: str, *, size: int | None = None,
                        priority: str = "normal") -> Packet:
        return self.inject(source, destination, size=size, priority=priority)

    def _enqueue(self, packet: Packet, node: str) -> None:
        packet.node = node
        if len(self.queues[node]) >= self.queue_capacity:
            self._drop(packet, "queue_overflow")
        else:
            packet.status = "queued"
            self._queue_sequence += 1
            packet.queue_order = self._queue_sequence
            self.queues[node].append(packet.id)

    def _drop(self, packet: Packet, reason: str) -> None:
        if packet.node is not None and packet.id in self.queues[packet.node]:
            self.queues[packet.node].remove(packet.id)
        packet.status = "dropped"
        packet.drop_reason = reason
        packet.link = packet.next_node = packet.arrives_at = None
        packet.remaining_bytes = 0
        self._event("dropped", packet=packet.id, reason=reason)

    def _deliver(self, packet: Packet) -> None:
        packet.status = "delivered"
        packet.delivery_time = self.time
        self._event("delivered", packet=packet.id)

    def _network_changed(self, kind: str, component: str) -> None:
        self._event(kind, component=component)
        if kind == "node_added":
            self.queues[component] = []
        if kind not in ("node_failed", "link_failed"):
            return
        for packet in self.packets.values():
            if packet.status not in ("queued", "in_flight"):
                continue
            if kind == "node_failed":
                incident = packet.link is not None and component in (
                    self.network.links[packet.link].source,
                    self.network.links[packet.link].destination)
                affected = packet.node == component or incident
            else:
                affected = packet.link == component
            if affected:
                self._drop(packet, kind)
            elif packet.status == "queued":
                packet.route = self.network.route(packet.node, packet.destination)
                if not packet.route:
                    self._drop(packet, "unreachable")
                else:
                    self._event("route_recalculated", packet=packet.id, route=list(packet.route))

    def set_node_active(self, node: str, active: bool) -> None:
        if type(active) is not bool:
            raise ValueError("active must be boolean")
        (self.network.recover_node if active else self.network.fail_node)(node)

    def set_link_active(self, link_id: str, active: bool) -> None:
        if type(active) is not bool:
            raise ValueError("active must be boolean")
        (self.network.recover_link if active else self.network.fail_link)(link_id)

    def _penalties(self) -> dict[str, float]:
        demand = dict.fromkeys(self.network.links, 0)
        for node, queue in self.queues.items():
            for packet_id in queue:
                packet = self.packets[packet_id]
                path = self.network.route(node, packet.destination)
                if len(path) > 1:
                    demand[self.network.adjacency[node][path[1]]] += packet.size
        for packet in self.packets.values():
            if packet.status == "in_flight":
                demand[packet.link] += packet.remaining_bytes
        return {key: self.congestion_weight * count / self.network.links[key].bandwidth
                for key, count in demand.items()}

    def _transmit_bytes(self, packet: Packet, link: Link) -> None:
        amount = min(packet.remaining_bytes, link.bandwidth - link.current_load)
        packet.remaining_bytes -= amount
        link.current_load += amount
        link.transmitted_bytes += amount
        self._event("bytes_transmitted", packet=packet.id, link=link.id, size=amount)
        if packet.remaining_bytes == 0:
            # Serialization occupies this tick; propagation starts at its end.
            packet.arrives_at = self.time + 1 + link.latency

    def step(self, ticks: int = 1) -> None:
        positive_integer(ticks, "ticks")
        for _ in range(ticks):
            for link in self.network.links.values():
                link.current_load = 0
                link.last_available_bytes = link.bandwidth if self.network.operational(link) else 0
                link.available_bytes += link.last_available_bytes
            # Complete serialization already started; transmission is not preempted.
            for packet in self.packets.values():
                if packet.status == "in_flight" and packet.remaining_bytes:
                    self._transmit_bytes(packet, self.network.links[packet.link])
            penalties = self._penalties()
            waiting = [self.packets[i] for queue in self.queues.values() for i in queue]
            waiting.sort(key=lambda p: (p.priority != "emergency", p.queue_order))
            for packet in waiting:
                packet.route = self.network.route(packet.node, packet.destination, penalties)
                if not packet.route:
                    self._drop(packet, "unreachable")
                    continue
                link = self.network.links[self.network.adjacency[packet.route[0]][packet.route[1]]]
                if link.current_load >= link.bandwidth:
                    continue
                self.queues[packet.node].remove(packet.id)
                packet.status = "in_flight"
                packet.node = None
                packet.link = link.id
                packet.next_node = packet.route[1]
                packet.remaining_bytes = packet.size
                self._event("transmitted", packet=packet.id, link=link.id, route=list(packet.route))
                self._transmit_bytes(packet, link)
            self.time += 1
            for packet in self.packets.values():
                if packet.status in {"queued", "in_flight"} and packet.deadline <= self.time:
                    self._drop(packet, "lifetime_expired")
                elif packet.status == "in_flight" and packet.arrives_at == self.time:
                    node = packet.next_node
                    packet.path.append(node)
                    packet.node = node
                    packet.link = packet.next_node = packet.arrives_at = None
                    self._event("arrived", packet=packet.id, node=node)
                    if node == packet.destination:
                        self._deliver(packet)
                    else:
                        packet.route = self.network.route(node, packet.destination)
                        if not packet.route:
                            self._drop(packet, "unreachable")
                        else:
                            self._enqueue(packet, node)

    def metrics(self) -> dict:
        delivered = [p for p in self.packets.values() if p.status == "delivered"]
        dropped = sum(p.status == "dropped" for p in self.packets.values())
        count = len(self.packets)
        average_latency = (sum(p.delivery_time - p.creation_time for p in delivered)
                           / len(delivered) if delivered else None)
        return {
            "elapsed_seconds": self.time,
            "injected": count, "delivered": len(delivered), "dropped": dropped,
            "pending": count - len(delivered) - dropped,
            "average_latency_seconds": average_latency,
            "mean_latency_seconds": average_latency,
            "throughput_bps": sum(p.size for p in delivered) * 8 / self.time if self.time else 0,
            "packet_loss_ratio": dropped / count if count else 0,
            "packet_loss_percentage": 100 * dropped / count if count else 0,
            "links": {key: {
                "transmitted_bytes": link.transmitted_bytes,
                "available_bytes": link.available_bytes,
                "current_load": link.current_load,
                "utilization": link.utilization,
                "last_tick_utilization": (link.current_load / link.last_available_bytes
                                          if link.last_available_bytes else None),
            } for key, link in self.network.links.items()},
        }

    def snapshot(self) -> dict:
        return {
            "time": self.time,
            "nodes": {key: asdict(node) for key, node in self.network.nodes.items()},
            "links": [dict(asdict(link), utilization=link.utilization)
                      for link in self.network.links.values()],
            "queues": {node: list(queue) for node, queue in self.queues.items()},
            "packets": [asdict(packet) for packet in self.packets.values()],
            "metrics": self.metrics(), "events": deepcopy(self.events),
        }
