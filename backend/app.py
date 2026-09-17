"""HTTP API that exposes, but does not reimplement, the simulation engine."""

import asyncio
from contextlib import asynccontextmanager, suppress
from copy import deepcopy
import os
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware

from simulator import Link, Network, Node, Simulator

from .models import (
    ControlResponse,
    DisasterRequest,
    DisasterResponse,
    EmergencyTrafficRequest,
    ErrorResponse,
    EventsResponse,
    LinkConfig,
    LinkUpdateRequest,
    MetricsResponse,
    NodeConfig,
    NodeUpdateRequest,
    SimulationStartRequest,
    TopologyConfig,
    TopologyResponse,
    TrafficRequest,
    TrafficResponse,
)


DEFAULT_START = SimulationStartRequest.model_validate({
    "topology": {
        "nodes": [
            {"id": "hospital", "name": "Hospital", "type": "hospital", "x": 70, "y": 170},
            {"id": "router", "name": "Primary Router", "x": 300, "y": 40},
            {"id": "backup", "name": "Backup Router", "x": 300, "y": 300},
            {"id": "rescue", "name": "Rescue Center", "type": "rescue", "x": 530, "y": 170},
        ],
        "links": [
            {"id": "hospital-router", "source": "hospital", "destination": "router"},
            {"id": "router-rescue", "source": "router", "destination": "rescue"},
            {"id": "hospital-backup", "source": "hospital", "destination": "backup",
             "latency": 2},
            {"id": "backup-rescue", "source": "backup", "destination": "rescue"},
        ],
    },
})

DEFAULT_FRONTEND_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
)


def _frontend_origins() -> list[str]:
    configured = os.getenv("FRONTEND_ORIGINS")
    if configured is None:
        return list(DEFAULT_FRONTEND_ORIGINS)
    return [origin.strip() for origin in configured.split(",") if origin.strip()]


def _build_simulator(config: SimulationStartRequest) -> Simulator:
    topology = config.topology
    if topology is None:
        raise ValueError("a topology is required to create a simulation")
    nodes = [Node(node.id, node.name or node.id, node.status, node.type, node.x, node.y)
             for node in topology.nodes]
    links = [Link(link.id, link.source, link.destination, link.bandwidth,
                  link.latency, link.status) for link in topology.links]
    return Simulator(
        Network(nodes, links),
        queue_capacity=config.queue_capacity,
        packet_bytes=config.packet_bytes,
        lifetime=config.packet_lifetime,
        congestion_weight=config.congestion_weight,
    )


class SimulationManager:
    """Serializes API mutations and owns the background simulated-time clock."""

    def __init__(self, default_config: SimulationStartRequest = DEFAULT_START):
        self._config = default_config.model_copy(deep=True)
        self.simulator = _build_simulator(self._config)
        self.running = False
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    @property
    def status(self) -> str:
        return "running" if self.running else "paused"

    async def start(self, request: SimulationStartRequest | None) -> dict:
        task = await self._stop_clock()
        await self._finish_task(task)
        async with self._lock:
            if request is not None:
                config = request.model_copy(deep=True)
                if config.topology is None:
                    config.topology = self._config.topology.model_copy(deep=True)
                self.simulator = _build_simulator(config)
                self._config = config
            self.running = True
            self._task = asyncio.create_task(self._clock())
            return self.control("simulation running")

    async def pause(self) -> dict:
        task = await self._stop_clock()
        await self._finish_task(task)
        return self.control("simulation paused")

    async def reset(self) -> dict:
        task = await self._stop_clock()
        await self._finish_task(task)
        async with self._lock:
            self.simulator = _build_simulator(self._config)
            return self.control("simulation reset")

    async def shutdown(self) -> None:
        task = await self._stop_clock()
        await self._finish_task(task)

    async def _stop_clock(self) -> asyncio.Task | None:
        async with self._lock:
            self.running = False
            task, self._task = self._task, None
            if task is not None:
                task.cancel()
            return task

    @staticmethod
    async def _finish_task(task: asyncio.Task | None) -> None:
        if task is not None:
            with suppress(asyncio.CancelledError):
                await task

    async def _clock(self) -> None:
        try:
            while True:
                await asyncio.sleep(self._config.tick_interval_seconds)
                async with self._lock:
                    if not self.running:
                        return
                    self.simulator.step()
        except asyncio.CancelledError:
            raise

    def control(self, message: str) -> dict:
        return {
            "simulation_status": self.status,
            "time": self.simulator.time,
            "message": message,
        }

    def topology(self) -> dict:
        snapshot = self.simulator.snapshot()
        links = []
        for link in snapshot["links"]:
            link = dict(link)
            link["queue"] = list(snapshot["link_queues"][link["id"]])
            links.append(link)
        packets = snapshot["packets"]
        active_routes = [{
            "packet": packet["id"],
            "status": packet["status"],
            "route": list(packet["route"]),
            "path": list(packet["path"]),
            "node": packet["node"],
            "link": packet["link"],
            "queued_link": packet["queued_link"],
        } for packet in packets if packet["status"] in {"queued", "in_flight"}]
        failures = [
            {"component_type": "node", "component": node["id"]}
            for node in snapshot["nodes"].values() if node["status"] == "failed"
        ] + [
            {"component_type": "link", "component": link["id"]}
            for link in links if link["status"] == "failed"
        ]
        return {
            "time": snapshot["time"],
            "simulation_status": self.status,
            "nodes": list(snapshot["nodes"].values()),
            "links": links,
            "active_routes": active_routes,
            "packets": packets,
            "failures": failures,
            "routing_changes": [event for event in snapshot["events"]
                                if event["kind"] == "route_recalculated"],
        }

    def inject(self, request: TrafficRequest, traffic: str) -> list[dict]:
        packets = [
            self.simulator.inject(
                request.source,
                request.destination,
                traffic,
                size=request.size,
            )
            for _ in range(request.count)
        ]
        snapshot_packets = {packet["id"]: packet for packet in self.simulator.snapshot()["packets"]}
        return [snapshot_packets[packet.id] for packet in packets]

    def sync_topology_config(self) -> None:
        """Keep editor topology for reset while treating failures as run-time state."""
        network = self.simulator.network
        self._config.topology = TopologyConfig(
            nodes=[NodeConfig(
                id=node.id, name=node.name, status="operational", type=node.type,
                x=node.x, y=node.y,
            ) for node in network.nodes.values()],
            links=[LinkConfig(
                id=link.id, source=link.source, destination=link.destination,
                bandwidth=link.bandwidth, latency=link.latency, status="operational",
            ) for link in network.links.values()],
        )


def _manager(request: Request) -> SimulationManager:
    return request.app.state.manager


def _http_error(exc: ValueError) -> HTTPException:
    detail = str(exc)
    code = status.HTTP_404_NOT_FOUND if detail.startswith("unknown ") else status.HTTP_400_BAD_REQUEST
    return HTTPException(status_code=code, detail=detail)


def create_app(default_config: SimulationStartRequest | None = None) -> FastAPI:
    manager = SimulationManager(default_config or DEFAULT_START)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        await manager.shutdown()

    application = FastAPI(
        title="Disaster Network Simulator API",
        version="1.0.0",
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=_frontend_origins(),
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type"],
    )
    application.state.manager = manager

    @application.get("/topology", response_model=TopologyResponse)
    async def get_topology(request: Request) -> dict:
        simulation = _manager(request)
        async with simulation._lock:
            return simulation.topology()

    @application.post("/simulation/start", response_model=ControlResponse,
                      responses={400: {"model": ErrorResponse}})
    async def start_simulation(request: Request,
                               settings: SimulationStartRequest | None = None) -> dict:
        try:
            return await _manager(request).start(settings)
        except ValueError as exc:
            raise _http_error(exc) from exc

    @application.post("/simulation/pause", response_model=ControlResponse)
    async def pause_simulation(request: Request) -> dict:
        return await _manager(request).pause()

    @application.post("/simulation/reset", response_model=ControlResponse)
    async def reset_simulation(request: Request) -> dict:
        try:
            return await _manager(request).reset()
        except ValueError as exc:
            raise _http_error(exc) from exc

    async def inject_traffic(request: Request, traffic_request: TrafficRequest,
                             traffic: str) -> dict:
        simulation = _manager(request)
        async with simulation._lock:
            try:
                packets = simulation.inject(traffic_request, traffic)
            except ValueError as exc:
                raise _http_error(exc) from exc
        return {"accepted": len(packets), "packets": packets}

    @application.post("/traffic/normal", response_model=TrafficResponse,
                      responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}})
    async def normal_traffic(request: Request, traffic: TrafficRequest) -> dict:
        return await inject_traffic(request, traffic, "normal")

    @application.post("/traffic/emergency", response_model=TrafficResponse,
                      responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}})
    async def emergency_traffic(request: Request, traffic: EmergencyTrafficRequest) -> dict:
        return await inject_traffic(request, traffic, traffic.service)

    async def set_component_health(request: Request, kind: str, component: str,
                                   failed: bool) -> dict:
        simulation = _manager(request)
        async with simulation._lock:
            try:
                if kind == "node":
                    operation = (simulation.simulator.network.fail_node if failed
                                 else simulation.simulator.network.recover_node)
                else:
                    operation = (simulation.simulator.network.fail_link if failed
                                 else simulation.simulator.network.recover_link)
                operation(component)
                return simulation.topology()
            except ValueError as exc:
                raise _http_error(exc) from exc

    @application.post("/nodes/{id}/fail", response_model=TopologyResponse,
                      responses={404: {"model": ErrorResponse}})
    async def fail_node(id: str, request: Request) -> dict:
        return await set_component_health(request, "node", id, True)

    @application.post("/nodes/{id}/recover", response_model=TopologyResponse,
                      responses={404: {"model": ErrorResponse}})
    async def recover_node(id: str, request: Request) -> dict:
        return await set_component_health(request, "node", id, False)

    @application.post("/nodes", response_model=TopologyResponse, status_code=201,
                      responses={400: {"model": ErrorResponse}})
    async def create_node(node: NodeConfig, request: Request) -> dict:
        simulation = _manager(request)
        async with simulation._lock:
            try:
                simulation.simulator.network.add_node(Node(
                    node.id, node.name or node.id, node.status, node.type, node.x, node.y,
                ))
                simulation.sync_topology_config()
                return simulation.topology()
            except ValueError as exc:
                raise _http_error(exc) from exc

    @application.patch("/nodes/{id}", response_model=TopologyResponse,
                       responses={400: {"model": ErrorResponse},
                                  404: {"model": ErrorResponse}})
    async def update_node(id: str, update: NodeUpdateRequest, request: Request) -> dict:
        simulation = _manager(request)
        async with simulation._lock:
            try:
                network = simulation.simulator.network
                if id not in network.nodes:
                    raise ValueError("unknown node ID")
                current = network.nodes[id]
                fields = update.model_fields_set
                network.update_node(
                    id,
                    name=update.name if "name" in fields and update.name is not None else current.name,
                    type=update.type if "type" in fields and update.type is not None else current.type,
                    x=update.x if "x" in fields else current.x,
                    y=update.y if "y" in fields else current.y,
                )
                simulation.sync_topology_config()
                return simulation.topology()
            except ValueError as exc:
                raise _http_error(exc) from exc

    @application.delete("/nodes/{id}", response_model=TopologyResponse,
                        responses={404: {"model": ErrorResponse}})
    async def delete_node(id: str, request: Request) -> dict:
        simulation = _manager(request)
        async with simulation._lock:
            try:
                simulation.simulator.network.remove_node(id)
                simulation.sync_topology_config()
                return simulation.topology()
            except ValueError as exc:
                raise _http_error(exc) from exc

    @application.post("/links/{id}/fail", response_model=TopologyResponse,
                      responses={404: {"model": ErrorResponse}})
    async def fail_link(id: str, request: Request) -> dict:
        return await set_component_health(request, "link", id, True)

    @application.post("/links/{id}/recover", response_model=TopologyResponse,
                      responses={404: {"model": ErrorResponse}})
    async def recover_link(id: str, request: Request) -> dict:
        return await set_component_health(request, "link", id, False)

    @application.post("/links", response_model=TopologyResponse, status_code=201,
                      responses={400: {"model": ErrorResponse}})
    async def create_link(link: LinkConfig, request: Request) -> dict:
        simulation = _manager(request)
        async with simulation._lock:
            try:
                simulation.simulator.network.add_link(Link(
                    link.id, link.source, link.destination, link.bandwidth,
                    link.latency, link.status,
                ))
                simulation.sync_topology_config()
                return simulation.topology()
            except ValueError as exc:
                raise _http_error(exc) from exc

    @application.patch("/links/{id}", response_model=TopologyResponse,
                       responses={400: {"model": ErrorResponse},
                                  404: {"model": ErrorResponse}})
    async def update_link(id: str, update: LinkUpdateRequest, request: Request) -> dict:
        simulation = _manager(request)
        async with simulation._lock:
            try:
                network = simulation.simulator.network
                if id not in network.links:
                    raise ValueError("unknown link ID")
                current = network.links[id]
                network.update_link(
                    id,
                    bandwidth=(update.bandwidth if update.bandwidth is not None
                               else current.bandwidth),
                    latency=update.latency if update.latency is not None else current.latency,
                )
                simulation.sync_topology_config()
                return simulation.topology()
            except ValueError as exc:
                raise _http_error(exc) from exc

    @application.delete("/links/{id}", response_model=TopologyResponse,
                        responses={404: {"model": ErrorResponse}})
    async def delete_link(id: str, request: Request) -> dict:
        simulation = _manager(request)
        async with simulation._lock:
            try:
                simulation.simulator.network.remove_link(id)
                simulation.sync_topology_config()
                return simulation.topology()
            except ValueError as exc:
                raise _http_error(exc) from exc

    @application.post("/disasters/trigger", response_model=DisasterResponse,
                      responses={400: {"model": ErrorResponse}})
    async def trigger_disaster(disaster: DisasterRequest, request: Request) -> dict:
        simulation = _manager(request)
        async with simulation._lock:
            try:
                result = simulation.simulator.trigger_disaster(
                    disaster.disaster, disaster.intensity, seed=disaster.seed,
                )
                return {**result, "topology": simulation.topology()}
            except ValueError as exc:
                raise _http_error(exc) from exc

    @application.get("/metrics", response_model=MetricsResponse)
    async def get_metrics(request: Request) -> dict:
        simulation = _manager(request)
        async with simulation._lock:
            return deepcopy(simulation.simulator.metrics())

    @application.get("/events", response_model=EventsResponse)
    async def get_events(request: Request,
                         since: int = Query(default=0, ge=0),
                         limit: int = Query(default=1000, ge=1, le=10000)) -> dict[str, Any]:
        simulation = _manager(request)
        async with simulation._lock:
            events = deepcopy(simulation.simulator.events[since:since + limit])
            return {"count": len(events), "events": events}

    return application


app = create_app()
