import json
import unittest

from simulator import Link, Network, Node, Simulator


def pair(**kwargs):
    return Simulator(Network(["A", "B"], [Link("ab", "A", "B")]), **kwargs)


def diamond(weight=0):
    return Simulator(Network(["A", "B", "C", "D"], [
        Link("ab", "A", "B"), Link("bd", "B", "D"),
        Link("ac", "A", "C", latency=2), Link("cd", "C", "D"),
    ]), congestion_weight=weight)


class NetworkTests(unittest.TestCase):
    def test_add_named_nodes_and_link(self):
        network = Network()
        network.add_node(Node("A", "Hospital"))
        network.add_node(Node("B", "Rescue"))
        link = network.add_link(Link("radio", "A", "B", bandwidth=500, latency=3))
        self.assertEqual(network.nodes["A"].name, "Hospital")
        self.assertEqual(network.nodes["A"].status, "operational")
        self.assertEqual(network.adjacency, {"A": {"B": "radio"}, "B": {"A": "radio"}})
        self.assertEqual((link.bandwidth, link.latency, link.current_load), (500, 3, 0))
        self.assertIsNone(link.utilization)

    def test_fail_and_recover_components(self):
        network = pair().network
        network.fail_link("ab")
        self.assertEqual(network.links["ab"].status, "failed")
        self.assertEqual(network.route("A", "B"), [])
        network.recover_link("ab")
        network.fail_node("B")
        self.assertEqual(network.nodes["B"].status, "failed")
        self.assertEqual(network.route("A", "B"), [])
        self.assertEqual(network.route("B", "B"), [])
        network.recover_node("B")
        self.assertEqual(network.route("A", "B"), ["A", "B"])

    def test_add_during_simulation(self):
        sim = Simulator(Network(["A"]))
        sim.network.add_node(Node("B", "Police"))
        sim.network.add_link(Link("ab", "A", "B"))
        packet = sim.inject("A", "B")
        sim.step(2)
        self.assertEqual(packet.status, "delivered")

    def test_configuration_and_independent_runs(self):
        network = Network.from_dict({"nodes": [{"id": "A", "name": "Hospital"}, "B"],
                                     "links": [{"id": "ab", "source": "A", "destination": "B"}]})
        first, second = Simulator(network), Simulator(network)
        first.network.fail_node("A")
        self.assertEqual(second.network.route("A", "B"), ["A", "B"])
        self.assertEqual(network.nodes["A"].status, "operational")

    def test_editor_metadata_updates_and_topology_deletion(self):
        sim = diamond()
        sim.network.update_node("A", name="Hospital", type="hospital", x=25, y=40)
        self.assertEqual((sim.network.nodes["A"].name, sim.network.nodes["A"].type,
                          sim.network.nodes["A"].x, sim.network.nodes["A"].y),
                         ("Hospital", "hospital", 25, 40))
        sim.network.update_link("ab", bandwidth=2048, latency=3)
        self.assertEqual((sim.network.links["ab"].bandwidth,
                          sim.network.links["ab"].latency), (2048, 3))

        packet = sim.inject("A", "D")
        self.assertEqual(packet.route, ["A", "C", "D"])
        sim.network.remove_link("ac")
        self.assertEqual(packet.route, ["A", "B", "D"])
        self.assertNotIn("ac", sim.link_queues)
        sim.network.remove_node("B")
        self.assertEqual(packet.status, "dropped")
        self.assertNotIn("B", sim.network.nodes)
        self.assertNotIn("ab", sim.network.links)
        self.assertNotIn("bd", sim.network.links)

    def test_deleting_destination_drops_active_packet(self):
        sim = pair()
        packet = sim.inject("A", "B")
        sim.network.remove_node("B")
        self.assertEqual((packet.status, packet.drop_reason),
                         ("dropped", "endpoint_deleted"))
        self.assertEqual(sim.queues["A"], [])


class RoutingTests(unittest.TestCase):
    def test_dijkstra_weighted_shortest_path(self):
        sim = diamond()
        sim.network.add_link(Link("ad", "A", "D", latency=10))
        self.assertEqual(sim.network.route("A", "D"), ["A", "B", "D"])
        self.assertEqual(sim.network.route("D", "A"), ["D", "B", "A"])
        self.assertEqual(sim.network.route("A", "A"), ["A"])

    def test_failed_intermediate_node_and_link_excluded(self):
        sim = diamond()
        sim.network.fail_node("B")
        self.assertEqual(sim.network.route("A", "D"), ["A", "C", "D"])
        sim.network.fail_link("cd")
        self.assertEqual(sim.network.route("A", "D"), [])

    def test_queued_route_recalculated_after_failure(self):
        sim = diamond()
        packet = sim.inject("A", "D")
        sim.network.fail_link("ab")
        self.assertEqual(packet.route, ["A", "C", "D"])
        sim.step(5)
        self.assertEqual(packet.path, ["A", "C", "D"])
        self.assertEqual(packet.status, "delivered")

    def test_failure_after_first_hop(self):
        sim = diamond()
        packet = sim.inject("A", "D")
        sim.step(2)
        sim.network.fail_link("bd")
        self.assertEqual(packet.route, ["B", "A", "C", "D"])
        sim.step(7)
        self.assertEqual(packet.path, ["A", "B", "A", "C", "D"])
        self.assertEqual(packet.status, "delivered")

    def test_congestion_changes_route(self):
        sim = diamond(weight=1)
        for _ in range(4):
            sim.inject("A", "D")
        sim.step()
        transmissions = [e for e in sim.events if e["kind"] == "transmitted"]
        self.assertEqual(transmissions[0]["route"], ["A", "C", "D"])


class SimulationTests(unittest.TestCase):
    def test_packet_fields_and_delivery(self):
        sim = pair()
        packet = sim.generate_packet("A", "B", size=512, priority="emergency")
        self.assertEqual((packet.id, packet.source, packet.destination, packet.size), (1, "A", "B", 512))
        self.assertEqual(packet.priority, "emergency")
        self.assertEqual(packet.creation_time, 0)
        self.assertIsNone(packet.delivery_time)
        self.assertEqual(packet.route, ["A", "B"])
        sim.step()
        self.assertEqual(packet.status, "in_flight")
        sim.step()
        self.assertEqual(packet.delivery_time, 2)
        self.assertEqual(packet.status, "delivered")

    def test_emergency_priority(self):
        for traffic in Simulator.EMERGENCY:
            with self.subTest(traffic=traffic):
                sim = pair()
                normal = sim.inject("A", "B")
                emergency = sim.inject("A", "B", traffic)
                sim.step()
                self.assertEqual(emergency.status, "in_flight")
                self.assertEqual(normal.status, "queued")
                sim.step(2)
                self.assertLess(emergency.delivery_time, normal.delivery_time)

    def test_shared_bandwidth_fifo(self):
        sim = pair()
        first = sim.inject("B", "A")
        second = sim.inject("A", "B")
        sim.step()
        self.assertEqual(first.status, "in_flight")
        self.assertEqual(second.status, "queued")
        self.assertEqual(sim.network.links["ab"].current_load, 1024)

    def test_large_packet_serialization_and_nonpreemption(self):
        sim = pair()
        large = sim.inject("A", "B", size=2500)
        sim.step()
        self.assertEqual(large.remaining_bytes, 1476)
        urgent = sim.inject("B", "A", size=100, priority="emergency")
        sim.step()
        self.assertEqual(large.remaining_bytes, 452)
        self.assertEqual(urgent.status, "queued")
        sim.step()
        self.assertEqual(sim.network.links["ab"].current_load, 552)
        sim.step()
        self.assertEqual(large.delivery_time, 4)
        self.assertEqual(urgent.delivery_time, 4)
        self.assertEqual(sim.network.links["ab"].transmitted_bytes, 2600)

    def test_small_packets_share_tick_bandwidth(self):
        sim = pair()
        packets = [sim.inject("A", "B", size=256) for _ in range(4)]
        sim.step(2)
        self.assertTrue(all(p.delivery_time == 2 for p in packets))
        self.assertEqual(sim.network.links["ab"].transmitted_bytes, 1024)

    def test_unreachable_dropped_and_recovery_allows_new_packet(self):
        sim = pair()
        sim.network.fail_node("B")
        packet = sim.inject("A", "B")
        self.assertEqual(packet.drop_reason, "unreachable")
        sim.step(2)
        self.assertIsNone(sim.network.links["ab"].utilization)
        sim.network.recover_node("B")
        fresh = sim.inject("A", "B")
        sim.step(2)
        self.assertEqual(fresh.status, "delivered")
        self.assertEqual(packet.status, "dropped")

    def test_disconnection_drops_queued_packet(self):
        sim = pair()
        packet = sim.inject("A", "B")
        sim.network.fail_link("ab")
        self.assertEqual(packet.drop_reason, "unreachable")
        self.assertEqual(sim.queues["A"], [])

    def test_unreachable_on_arrival(self):
        sim = Simulator(Network(["A", "B", "C"], [Link("ab", "A", "B"), Link("bc", "B", "C")]))
        packet = sim.inject("A", "C")
        sim.step()
        sim.network.fail_link("bc")
        sim.step()
        self.assertEqual(packet.path, ["A", "B"])
        self.assertEqual(packet.drop_reason, "unreachable")

    def test_inflight_failure_and_restore(self):
        for component in ("node", "link"):
            for size in (512, 5000):
                with self.subTest(component=component, size=size):
                    sim = pair()
                    packet = sim.inject("A", "B", size=size)
                    sim.step()
                    if component == "node":
                        sim.network.fail_node("A")
                        sim.network.recover_node("A")
                    else:
                        sim.network.fail_link("ab")
                        sim.network.recover_link("ab")
                    self.assertEqual(packet.drop_reason, component + "_failed")
                    fresh = sim.inject("A", "B")
                    sim.step(2)
                    self.assertEqual(fresh.status, "delivered")
                    self.assertEqual(packet.status, "dropped")

    def test_queue_overflow_and_node_failure(self):
        sim = pair(queue_capacity=1)
        first = sim.inject("A", "B")
        self.assertEqual(sim.inject("A", "B").drop_reason, "queue_overflow")
        sim.network.fail_node("A")
        self.assertEqual(first.drop_reason, "node_failed")
        self.assertEqual(sim.inject("A", "B").drop_reason, "source_failed")

    def test_lifetime_queue_and_inflight(self):
        sim = pair(lifetime=1)
        first = sim.inject("A", "B")
        second = sim.inject("A", "B")
        sim.step()
        self.assertEqual(first.drop_reason, "lifetime_expired")
        self.assertEqual(second.drop_reason, "lifetime_expired")

    def test_local_delivery(self):
        sim = pair()
        self.assertEqual(sim.inject("A", "A").status, "delivered")
        self.assertEqual(sim.metrics()["average_latency_seconds"], 0)
        self.assertEqual(sim.network.links["ab"].transmitted_bytes, 0)

    def test_disaster_presets_fail_real_components_deterministically(self):
        nodes = [
            Node("R1", "Router 1", type="router", x=0, y=0),
            Node("R2", "Router 2", type="router", x=10, y=0),
            Node("H", "Hospital", type="hospital", x=100, y=100),
            Node("P", "Police", type="police", x=110, y=100),
        ]
        links = [
            Link("r1-r2", "R1", "R2"), Link("r1-h", "R1", "H"),
            Link("r2-p", "R2", "P"), Link("h-p", "H", "P"),
        ]

        def run(kind):
            sim = Simulator(Network(nodes, links))
            result = sim.trigger_disaster(kind, "medium", seed=7)
            for node_id in result["failed_nodes"]:
                self.assertEqual(sim.network.nodes[node_id].status, "failed")
            for link_id in result["failed_links"]:
                self.assertEqual(sim.network.links[link_id].status, "failed")
            self.assertEqual(sim.events[0]["kind"], "disaster_triggered")
            self.assertEqual(sim.events[-1]["kind"], "recalculating_routes")
            return result

        for disaster in ("earthquake", "flood", "cyclone", "cyberattack"):
            with self.subTest(disaster=disaster):
                self.assertEqual(run(disaster), run(disaster))
        cyber = run("cyberattack")
        self.assertTrue(cyber["failed_nodes"])
        self.assertTrue(all(node_id in {"R1", "R2"}
                            for node_id in cyber["failed_nodes"]))


class MetricsTests(unittest.TestCase):
    def test_exact_variable_size_metrics(self):
        sim = pair(queue_capacity=2)
        sim.inject("A", "B", size=512)
        sim.inject("A", "B", size=1024)
        sim.inject("A", "B")  # queue overflow
        sim.step(3)
        metrics = sim.metrics()
        self.assertEqual(metrics["average_latency_seconds"], 2.5)
        self.assertEqual(metrics["throughput_bps"], 4096)
        self.assertAlmostEqual(metrics["packet_loss_percentage"], 100 / 3)
        self.assertEqual(metrics["links"]["ab"]["utilization"], 0.5)
        self.assertEqual(metrics["pending"], 0)
        self.assertEqual(metrics["links"]["ab"]["last_tick_utilization"], 0)

    def test_failure_utilization_keeps_consumed_bytes(self):
        sim = pair()
        sim.inject("A", "B", size=3000)
        sim.step()
        sim.network.fail_link("ab")
        sim.step(2)
        self.assertEqual(sim.network.links["ab"].transmitted_bytes, 1024)
        self.assertEqual(sim.network.links["ab"].available_bytes, 1024)
        self.assertEqual(sim.metrics()["packet_loss_percentage"], 100)
        self.assertEqual(sim.metrics()["throughput_bps"], 0)
        self.assertIsNone(sim.metrics()["links"]["ab"]["last_tick_utilization"])

    def test_snapshot_and_empty_metrics(self):
        sim = pair()
        self.assertIsNone(sim.metrics()["average_latency_seconds"])
        self.assertEqual(sim.metrics()["throughput_bps"], 0)
        self.assertEqual(sim.metrics()["packet_loss_percentage"], 0)
        sim.inject("A", "B")
        sim.step()
        snapshot = sim.snapshot()
        json.dumps(snapshot, allow_nan=False)
        snapshot["nodes"]["A"]["name"] = "changed"
        snapshot["packets"][0]["path"].clear()
        snapshot["events"][1]["route"].clear()
        self.assertEqual(sim.network.nodes["A"].name, "A")
        self.assertEqual(sim.packets[1].path, ["A"])
        self.assertEqual(sim.events[1]["route"], ["A", "B"])

    def test_packet_conservation_capacity_and_determinism(self):
        def run():
            sim = diamond(weight=1)
            for tick in range(30):
                sim.inject("A", "D", "rescue" if tick % 3 == 0 else "normal", size=300 + tick * 100)
                if tick == 5:
                    sim.network.fail_node("B")
                if tick == 12:
                    sim.network.recover_node("B")
                sim.step()
                m = sim.metrics()
                self.assertEqual(m["injected"], m["delivered"] + m["dropped"] + m["pending"])
                for link in sim.network.links.values():
                    self.assertLessEqual(link.current_load, link.last_available_bytes)
                    self.assertLessEqual(link.transmitted_bytes, link.available_bytes)
            return sim.snapshot()
        self.assertEqual(run(), run())


class ValidationTests(unittest.TestCase):
    def test_invalid_topology_and_atomic_add(self):
        for factory in [lambda: Node("", "Name"), lambda: Node("A", ""),
                        lambda: Node("A", "Name", "broken"),
                        lambda: Link("x", "A", "A"),
                        lambda: Link("x", "A", "B", bandwidth=0),
                        lambda: Link("x", "A", "B", latency=True),
                        lambda: Network(["A", "A"])]:
            with self.assertRaises(ValueError):
                factory()
        network = pair().network
        before = dict(network.adjacency["A"])
        for link in [Link("x", "A", "C"), Link("other", "B", "A")]:
            with self.assertRaises(ValueError):
                network.add_link(link)
        self.assertEqual(network.adjacency["A"], before)
        self.assertEqual(len(network.links), 1)

    def test_invalid_controls_do_not_mutate(self):
        sim = pair()
        for kwargs in [dict(size=0), dict(size=True), dict(priority="urgent"),
                       dict(traffic="unknown"), dict(traffic="hospital", priority="normal")]:
            with self.assertRaises(ValueError):
                sim.inject("A", "B", **kwargs)
        with self.assertRaises(ValueError):
            sim.inject("A", "unknown")
        self.assertEqual(sim.metrics()["injected"], 0)
        for ticks in [0, -1, 1.5, True]:
            with self.assertRaises(ValueError):
                sim.step(ticks)
        with self.assertRaises(ValueError):
            pair(congestion_weight=float("nan"))
        for control in (sim.network.fail_node, sim.network.recover_node,
                        sim.network.fail_link, sim.network.recover_link):
            with self.assertRaises(ValueError):
                control("unknown")
        with self.assertRaises(ValueError):
            sim.set_node_active("A", 1)
        with self.assertRaises(ValueError):
            sim.network.route("A", "B", {"ab": -1})


if __name__ == "__main__":
    unittest.main()
