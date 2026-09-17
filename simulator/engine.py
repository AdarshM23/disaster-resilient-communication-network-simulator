"""Deterministic graph routing and store-and-forward packet simulation.

One tick is one simulated second. Sizes and bandwidth use bytes and bytes/second.
"""

from copy import deepcopy
from dataclasses import asdict, dataclass, field
import heapq
import math
import random
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


NODE_TYPES = frozenset({
    "router", "switch", "hospital", "police", "fire", "rescue", "ambulance",
})


def valid_node_type(node_type: str) -> None:
    if node_type not in NODE_TYPES:
        raise ValueError("unknown node type")


def valid_coordinate(value: float | None, name: str) -> None:
    if value is not None and (isinstance(value, bool)
                              or not isinstance(value, (int, float))
                              or not math.isfinite(value)):
        raise ValueError(f"{name} must be a finite number or null")


@dataclass
class Node:
    id: str
    name: str
    status: str = "operational"
    type: str = "router"
    x: float | None = None
    y: float | None = None

    def __post_init__(self):
        valid_id(self.id)
        valid_id(self.name)
        valid_status(self.status)
        valid_node_type(self.type)
        valid_coordinate(self.x, "x")
        valid_coordinate(self.y, "y")


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

    def update_node(self, node_id: str, *, name: str, type: str,
                    x: float | None, y: float | None) -> Node:
        """Update editor metadata without bypassing graph change notifications."""
        if node_id not in self.nodes:
            raise ValueError("unknown node ID")
        candidate = Node(node_id, name, self.nodes[node_id].status, type, x, y)
        node = self.nodes[node_id]
        node.name, node.type, node.x, node.y = (
            candidate.name, candidate.type, candidate.x, candidate.y,
        )
        self._notify("node_updated", node_id)
        return node

    def update_link(self, link_id: str, *, bandwidth: int, latency: int) -> Link:
        """Update link capacity/cost after validating the complete replacement."""
        if link_id not in self.links:
            raise ValueError("unknown link ID")
        link = self.links[link_id]
        candidate = Link(link.id, link.source, link.destination, bandwidth, latency,
                         link.status)
        link.bandwidth, link.latency = candidate.bandwidth, candidate.latency
        self._notify("link_updated", link_id)
        return link

    def remove_link(self, link_id: str) -> None:
        if link_id not in self.links:
            raise ValueError("unknown link ID")
        link = self.links[link_id]
        self._notify("link_removing", link_id)
        del self.adjacency[link.source][link.destination]
        del self.adjacency[link.destination][link.source]
        del self.links[link_id]
        self._notify("link_deleted", link_id)

    def remove_node(self, node_id: str) -> None:
        if node_id not in self.nodes:
            raise ValueError("unknown node ID")
        incident_links = sorted(self.adjacency[node_id].values())
        self._notify("node_removing", node_id)
        for link_id in incident_links:
            self.remove_link(link_id)
        del self.adjacency[node_id]
        del self.nodes[node_id]
        self._notify("node_deleted", node_id)

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
    queued_link: str | None = None

    @property
    def created_at(self) -> int:
        return self.creation_time

    @property
    def delivered_at(self) -> int | None:
        return self.delivery_time

    @property
    def packet_class(self) -> str:
        return self.priority

    @property
    def latency_seconds(self) -> int | None:
        if self.delivery_time is None:
            return None
        return self.delivery_time - self.creation_time


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
        self.link_queues: dict[str, list[int]] = {link: [] for link in network.links}
        self.events: list[dict] = []
        self._queue_sequence = 0
        self.network._on_change = self._network_changed

    def _event(self, kind: str, **details) -> None:
        self.events.append({"time": self.time, "kind": kind, **details})

    def inject(self, source: str, destination: str, traffic: str = "normal", *,
               size: int | None = None, priority: str | None = None) -> Packet:
        if source not in self.network.nodes or destination not in self.network.nodes:
            raise ValueError("unknown packet endpoint")
        if not isinstance(traffic, str):
            raise ValueError("unknown traffic class")
        traffic = traffic.lower()
        if traffic not in self.EMERGENCY | {"normal", "emergency"}:
            raise ValueError("unknown traffic class")
        size = self.packet_bytes if size is None else size
        positive_integer(size, "packet size")
        emergency = traffic == "emergency" or traffic in self.EMERGENCY
        if priority is not None and not isinstance(priority, str):
            raise ValueError("priority must be normal or emergency")
        priority = priority.lower() if priority is not None else None
        priority = ("emergency" if emergency else "normal") if priority is None else priority
        if priority not in ("normal", "emergency"):
            raise ValueError("priority must be normal or emergency")
        if emergency and priority != "emergency":
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
        packet.status = "queued"
        self._queue_sequence += 1
        packet.queue_order = self._queue_sequence
        self.queues[node].append(packet.id)
        self._assign_link_queue(packet)

    def _remove_from_queues(self, packet: Packet) -> None:
        if packet.node is not None and packet.id in self.queues[packet.node]:
            self.queues[packet.node].remove(packet.id)
        if (packet.queued_link is not None
                and packet.id in self.link_queues[packet.queued_link]):
            self.link_queues[packet.queued_link].remove(packet.id)
        packet.queued_link = None

    def _assign_link_queue(self, packet: Packet) -> None:
        """Place a queued packet on the output link selected by its route."""
        if packet.status != "queued" or packet.node is None or len(packet.route) < 2:
            return
        link_id = self.network.adjacency[packet.node][packet.route[1]]
        if packet.queued_link == link_id:
            return
        if packet.queued_link is not None:
            self.link_queues[packet.queued_link].remove(packet.id)
            packet.queued_link = None
        if len(self.link_queues[link_id]) >= self.queue_capacity:
            self._drop(packet, "queue_overflow")
            return
        packet.queued_link = link_id
        self.link_queues[link_id].append(packet.id)
        self._event("queued", packet=packet.id, node=packet.node, link=link_id,
                    priority=packet.priority, route=list(packet.route))

    def _drop(self, packet: Packet, reason: str) -> None:
        self._remove_from_queues(packet)
        packet.status = "dropped"
        packet.drop_reason = reason
        packet.link = packet.next_node = packet.arrives_at = None
        packet.remaining_bytes = 0
        self._event("dropped", packet=packet.id, reason=reason)

    def _deliver(self, packet: Packet) -> None:
        packet.status = "delivered"
        packet.delivery_time = self.time
        self._event("delivered", packet=packet.id)

    def _update_route(self, packet: Packet, route: list[str], reason: str, *,
                      component: str | None = None,
                      previous_route: list[str] | None = None) -> None:
        """Store a route and emit an event only when the remaining route changes."""
        old_route = list(packet.route if previous_route is None else previous_route)
        packet.route = list(route)
        if old_route == packet.route:
            return
        details = {
            "packet": packet.id,
            "previous_route": old_route,
            "route": list(packet.route),
            "reason": reason,
        }
        if component is not None:
            details["component"] = component
        self._event("route_recalculated", **details)

    def _network_changed(self, kind: str, component: str) -> None:
        if kind not in {"link_removing", "node_removing"}:
            self._event(kind, component=component)
        if kind == "node_added":
            self.queues[component] = []
        elif kind == "link_added":
            self.link_queues[component] = []
        elif kind == "link_removing":
            for packet in list(self.packets.values()):
                if packet.status == "in_flight" and packet.link == component:
                    self._drop(packet, "link_deleted")
            return
        elif kind == "node_removing":
            for packet in list(self.packets.values()):
                if packet.status not in {"queued", "in_flight"}:
                    continue
                incident = packet.link is not None and component in (
                    self.network.links[packet.link].source,
                    self.network.links[packet.link].destination,
                )
                if component in {packet.source, packet.destination}:
                    self._drop(packet, "endpoint_deleted")
                elif packet.node == component or incident:
                    self._drop(packet, "node_deleted")
            return
        elif kind == "link_deleted":
            for packet_id in self.link_queues.pop(component, []):
                packet = self.packets[packet_id]
                if packet.status == "queued":
                    packet.queued_link = None
        elif kind == "node_deleted":
            self.queues.pop(component, None)
            for packet in list(self.packets.values()):
                if (packet.status in {"queued", "in_flight"}
                        and component in {packet.source, packet.destination}):
                    self._drop(packet, "endpoint_deleted")

        route_changes = {
            "node_failed", "link_failed", "node_restored", "link_restored",
            "link_updated", "link_deleted", "node_deleted",
        }
        if kind not in route_changes:
            return
        for packet in self.packets.values():
            if packet.status not in ("queued", "in_flight"):
                continue
            if kind == "node_failed":
                incident = packet.link is not None and component in (
                    self.network.links[packet.link].source,
                    self.network.links[packet.link].destination)
                affected = packet.node == component or incident
            elif kind == "link_failed":
                affected = packet.link == component
            else:
                affected = False
            if affected:
                self._drop(packet, kind)
            elif packet.status == "queued":
                route = self.network.route(packet.node, packet.destination)
                self._update_route(packet, route, kind, component=component)
                if not packet.route:
                    self._drop(packet, "unreachable")
                else:
                    self._assign_link_queue(packet)

    def trigger_disaster(self, disaster: str, intensity: str = "medium", *,
                         seed: int = 0) -> dict[str, list[str] | str]:
        """Fail real components using deterministic, educational disaster presets."""
        if not isinstance(disaster, str) or disaster.lower() not in {
            "earthquake", "flood", "cyclone", "cyberattack",
        }:
            raise ValueError("unknown disaster type")
        if not isinstance(intensity, str) or intensity.lower() not in {
            "low", "medium", "high",
        }:
            raise ValueError("unknown disaster intensity")
        if type(seed) is not int:
            raise ValueError("disaster seed must be an integer")
        disaster = disaster.lower()
        intensity = intensity.lower()
        fraction = {"low": 0.2, "medium": 0.4, "high": 0.65}[intensity]
        rng = random.Random(seed)
        nodes = sorted(node.id for node in self.network.nodes.values()
                       if node.status == "operational")
        links = sorted(link.id for link in self.network.links.values()
                       if link.status == "operational")

        def choose(values: list[str], count: int) -> list[str]:
            count = min(len(values), max(0, count))
            return sorted(rng.sample(values, count)) if count else []

        failed_nodes: list[str] = []
        failed_links: list[str] = []
        if disaster == "earthquake":
            failed_nodes = choose(nodes, math.ceil(len(nodes) * fraction / 2))
            failed_links = choose(links, math.ceil(len(links) * fraction / 2))
        elif disaster == "cyclone":
            failed_links = choose(links, math.ceil(len(links) * fraction))
            failed_nodes = choose(nodes, round(len(nodes) * fraction * 0.2))
        elif disaster == "cyberattack":
            infrastructure = [node_id for node_id in nodes
                              if self.network.nodes[node_id].type in {"router", "switch"}]
            failed_nodes = choose(infrastructure,
                                  math.ceil(len(infrastructure) * fraction))
            failed_links = choose(links, round(len(links) * fraction * 0.15))
        else:
            components: list[tuple[float, float, str, str]] = []
            for node_id in nodes:
                node = self.network.nodes[node_id]
                if node.x is not None and node.y is not None:
                    components.append((float(node.x), float(node.y), "node", node_id))
            for link_id in links:
                link = self.network.links[link_id]
                source, destination = (self.network.nodes[link.source],
                                       self.network.nodes[link.destination])
                if None not in (source.x, source.y, destination.x, destination.y):
                    components.append(((source.x + destination.x) / 2,
                                       (source.y + destination.y) / 2,
                                       "link", link_id))
            count = math.ceil((len(nodes) + len(links)) * fraction * 0.6)
            if components:
                anchor = rng.choice(components)
                nearby = sorted(components, key=lambda item: (
                    (item[0] - anchor[0]) ** 2 + (item[1] - anchor[1]) ** 2,
                    item[2], item[3],
                ))[:count]
                failed_nodes = sorted(item[3] for item in nearby if item[2] == "node")
                failed_links = sorted(item[3] for item in nearby if item[2] == "link")
            else:
                combined = [("node", item) for item in nodes] + [
                    ("link", item) for item in links
                ]
                selected = rng.sample(combined, min(len(combined), count)) if count else []
                failed_nodes = sorted(item for kind, item in selected if kind == "node")
                failed_links = sorted(item for kind, item in selected if kind == "link")

        self._event("disaster_triggered", disaster=disaster,
                    intensity=intensity, seed=seed)
        for node_id in failed_nodes:
            self.network.fail_node(node_id)
        for link_id in failed_links:
            self.network.fail_link(link_id)
        self._event("recalculating_routes", disaster=disaster)
        return {
            "disaster": disaster,
            "intensity": intensity,
            "failed_nodes": failed_nodes,
            "failed_links": failed_links,
        }

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
        for link_id, queue in self.link_queues.items():
            demand[link_id] += sum(self.packets[packet_id].size for packet_id in queue)
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
            waiting.sort(key=lambda p: p.queue_order)
            for packet in waiting:
                route = self.network.route(packet.node, packet.destination, penalties)
                self._update_route(packet, route, "forwarding")
                if not packet.route:
                    self._drop(packet, "unreachable")
                    continue
                self._assign_link_queue(packet)
            for link_id, queue in self.link_queues.items():
                link = self.network.links[link_id]
                ordered = sorted(queue, key=lambda packet_id: (
                    self.packets[packet_id].priority != "emergency",
                    self.packets[packet_id].queue_order,
                ))
                for packet_id in ordered:
                    if link.current_load >= link.bandwidth:
                        break
                    packet = self.packets[packet_id]
                    self._remove_from_queues(packet)
                    packet.status = "in_flight"
                    packet.node = None
                    packet.link = link.id
                    packet.next_node = packet.route[1]
                    packet.remaining_bytes = packet.size
                    self._event("transmitted", packet=packet.id, link=link.id,
                                priority=packet.priority, route=list(packet.route))
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
                        expected_route = packet.route
                        if node in packet.route:
                            expected_route = packet.route[packet.route.index(node):]
                        route = self.network.route(node, packet.destination)
                        self._update_route(packet, route, "arrival",
                                           previous_route=expected_route)
                        if not packet.route:
                            self._drop(packet, "unreachable")
                        else:
                            self._enqueue(packet, node)

    def metrics(self) -> dict:
        delivered = [p for p in self.packets.values() if p.status == "delivered"]
        dropped_packets = [p for p in self.packets.values() if p.status == "dropped"]
        dropped = len(dropped_packets)
        count = len(self.packets)

        def average_latency(packets: list[Packet]) -> float | None:
            return (sum(p.delivery_time - p.creation_time for p in packets) / len(packets)
                    if packets else None)

        average = average_latency(delivered)
        emergency_delivered = [p for p in delivered if p.priority == "emergency"]
        normal_delivered = [p for p in delivered if p.priority == "normal"]
        emergency_latency = average_latency(emergency_delivered)
        normal_latency = average_latency(normal_delivered)

        def class_metrics(packet_class: str) -> dict:
            packets = [p for p in self.packets.values() if p.priority == packet_class]
            class_delivered = [p for p in packets if p.status == "delivered"]
            return {
                "generated": len(packets),
                "delivered": len(class_delivered),
                "dropped": sum(p.status == "dropped" for p in packets),
                "pending": sum(p.status in {"queued", "in_flight"} for p in packets),
                "average_latency_seconds": average_latency(class_delivered),
            }

        return {
            "elapsed_seconds": self.time,
            "injected": count, "delivered": len(delivered), "dropped": dropped,
            "packets_generated": count,
            "packets_delivered": len(delivered),
            "packets_dropped": dropped,
            "pending": count - len(delivered) - dropped,
            "average_latency_seconds": average,
            "mean_latency_seconds": average,
            "packet_latency_seconds": average,
            "emergency_packet_latency_seconds": emergency_latency,
            "normal_packet_latency_seconds": normal_latency,
            "emergency_average_latency_seconds": emergency_latency,
            "normal_average_latency_seconds": normal_latency,
            "throughput_bps": sum(p.size for p in delivered) * 8 / self.time if self.time else 0,
            "packet_loss_ratio": dropped / count if count else 0,
            "packet_loss_percentage": 100 * dropped / count if count else 0,
            "traffic_classes": {
                "normal": class_metrics("normal"),
                "emergency": class_metrics("emergency"),
            },
            "links": {key: {
                "transmitted_bytes": link.transmitted_bytes,
                "available_bytes": link.available_bytes,
                "current_load": link.current_load,
                "utilization": link.utilization,
                "queue_depth": len(self.link_queues[key]),
                "queue_capacity": self.queue_capacity,
                "queued_normal": sum(self.packets[packet_id].priority == "normal"
                                     for packet_id in self.link_queues[key]),
                "queued_emergency": sum(self.packets[packet_id].priority == "emergency"
                                        for packet_id in self.link_queues[key]),
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
            "link_queues": {link: list(queue) for link, queue in self.link_queues.items()},
            "packets": [dict(asdict(packet), packet_class=packet.packet_class,
                             latency_seconds=packet.latency_seconds)
                        for packet in self.packets.values()],
            "metrics": self.metrics(), "events": deepcopy(self.events),
        }
