"""Validated API request and response models."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


HealthStatus = Literal["operational", "failed"]
SimulationStatus = Literal["running", "paused"]
PacketStatus = Literal["queued", "in_flight", "delivered", "dropped"]
NodeType = Literal["router", "switch", "hospital", "police", "fire", "rescue", "ambulance"]
DisasterType = Literal["earthquake", "flood", "cyclone", "cyberattack"]
DisasterIntensity = Literal["low", "medium", "high"]


class NodeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    name: str | None = None
    status: HealthStatus = "operational"
    type: NodeType = "router"
    x: float | None = Field(default=None, allow_inf_nan=False)
    y: float | None = Field(default=None, allow_inf_nan=False)


class LinkConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    destination: str = Field(min_length=1)
    bandwidth: int = Field(default=1024, gt=0)
    latency: int = Field(default=1, gt=0)
    status: HealthStatus = "operational"


class TopologyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nodes: list[NodeConfig] = Field(default_factory=list)
    links: list[LinkConfig] = Field(default_factory=list)


class NodeUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1)
    type: NodeType | None = None
    x: float | None = Field(default=None, allow_inf_nan=False)
    y: float | None = Field(default=None, allow_inf_nan=False)


class LinkUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bandwidth: int | None = Field(default=None, gt=0)
    latency: int | None = Field(default=None, gt=0)


class DisasterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    disaster: DisasterType
    intensity: DisasterIntensity = "medium"
    seed: int = 0


class SimulationStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topology: TopologyConfig | None = None
    tick_interval_seconds: float = Field(default=1.0, gt=0)
    queue_capacity: int = Field(default=100, gt=0)
    packet_bytes: int = Field(default=1024, gt=0)
    packet_lifetime: int = Field(default=60, gt=0)
    congestion_weight: float = Field(default=1.0, ge=0)


class TrafficRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1)
    destination: str = Field(min_length=1)
    size: int | None = Field(default=None, gt=0)
    count: int = Field(default=1, ge=1, le=1000)


class EmergencyTrafficRequest(TrafficRequest):
    service: Literal["emergency", "hospital", "ambulance", "police", "fire", "rescue"] = (
        "emergency"
    )


class NodeState(BaseModel):
    id: str
    name: str
    status: HealthStatus
    type: NodeType
    x: float | None
    y: float | None


class LinkState(BaseModel):
    id: str
    source: str
    destination: str
    bandwidth: int
    latency: int
    status: HealthStatus
    current_load: int
    transmitted_bytes: int
    available_bytes: int
    last_available_bytes: int
    utilization: float | None
    queue: list[int]


class PacketState(BaseModel):
    id: int
    source: str
    destination: str
    size: int
    priority: Literal["normal", "emergency"]
    packet_class: Literal["normal", "emergency"]
    traffic: str
    creation_time: int
    deadline: int
    node: str | None
    delivery_time: int | None
    latency_seconds: int | None
    route: list[str]
    status: PacketStatus
    path: list[str]
    link: str | None
    queued_link: str | None
    next_node: str | None
    arrives_at: int | None
    remaining_bytes: int
    drop_reason: str | None
    queue_order: int


class ActiveRoute(BaseModel):
    packet: int
    status: Literal["queued", "in_flight"]
    route: list[str]
    path: list[str]
    node: str | None
    link: str | None
    queued_link: str | None


class FailureState(BaseModel):
    component_type: Literal["node", "link"]
    component: str


class SimulationEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    time: int
    kind: str


class TopologyResponse(BaseModel):
    time: int
    simulation_status: SimulationStatus
    nodes: list[NodeState]
    links: list[LinkState]
    active_routes: list[ActiveRoute]
    packets: list[PacketState]
    failures: list[FailureState]
    routing_changes: list[SimulationEvent]


class DisasterResponse(BaseModel):
    disaster: DisasterType
    intensity: DisasterIntensity
    failed_nodes: list[str]
    failed_links: list[str]
    topology: TopologyResponse


class ControlResponse(BaseModel):
    simulation_status: SimulationStatus
    time: int
    message: str


class TrafficResponse(BaseModel):
    accepted: int
    packets: list[PacketState]


class TrafficClassMetrics(BaseModel):
    generated: int
    delivered: int
    dropped: int
    pending: int
    average_latency_seconds: float | None


class LinkMetrics(BaseModel):
    transmitted_bytes: int
    available_bytes: int
    current_load: int
    utilization: float | None
    queue_depth: int
    queue_capacity: int
    queued_normal: int
    queued_emergency: int
    last_tick_utilization: float | None


class MetricsResponse(BaseModel):
    elapsed_seconds: int
    injected: int
    delivered: int
    dropped: int
    packets_generated: int
    packets_delivered: int
    packets_dropped: int
    pending: int
    average_latency_seconds: float | None
    mean_latency_seconds: float | None
    packet_latency_seconds: float | None
    emergency_packet_latency_seconds: float | None
    normal_packet_latency_seconds: float | None
    emergency_average_latency_seconds: float | None
    normal_average_latency_seconds: float | None
    throughput_bps: float
    packet_loss_ratio: float
    packet_loss_percentage: float
    traffic_classes: dict[str, TrafficClassMetrics]
    links: dict[str, LinkMetrics]


class EventsResponse(BaseModel):
    count: int
    events: list[SimulationEvent]


class ErrorResponse(BaseModel):
    detail: str
