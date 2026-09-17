import unittest

from simulator import Link, Network, Simulator


def resilient_network() -> Simulator:
    """Three routes from S to D, ordered from primary to tertiary."""
    return Simulator(Network(["S", "A", "B", "C", "D"], [
        Link("sa", "S", "A", bandwidth=4096, latency=1),
        Link("ad", "A", "D", bandwidth=4096, latency=1),
        Link("sb", "S", "B", bandwidth=4096, latency=2),
        Link("bd", "B", "D", bandwidth=4096, latency=2),
        Link("sc", "S", "C", bandwidth=4096, latency=3),
        Link("cd", "C", "D", bandwidth=4096, latency=3),
        Link("ab", "A", "B", bandwidth=4096, latency=1),
    ]), congestion_weight=0)


def run_until_terminal(sim: Simulator, packet_ids: list[int], max_ticks: int = 30) -> None:
    for _ in range(max_ticks):
        if all(sim.packets[packet_id].status in {"delivered", "dropped"}
               for packet_id in packet_ids):
            return
        sim.step()
    raise AssertionError(f"packets did not terminate within {max_ticks} ticks")


def route_events(sim: Simulator, packet_id: int) -> list[dict]:
    return [event for event in sim.events
            if event["kind"] == "route_recalculated" and event["packet"] == packet_id]


class DisasterResilienceIntegrationTests(unittest.TestCase):
    def test_normal_network_delivers_packets_on_shortest_route(self):
        sim = resilient_network()
        packets = [sim.inject("S", "D", size=256) for _ in range(3)]

        run_until_terminal(sim, [packet.id for packet in packets])

        self.assertTrue(all(packet.status == "delivered" for packet in packets))
        self.assertTrue(all(packet.path == ["S", "A", "D"] for packet in packets))
        self.assertEqual(sim.metrics()["dropped"], 0)

    def test_link_failure_reroutes_packet_and_never_uses_failed_link(self):
        sim = resilient_network()
        packet = sim.inject("S", "D", size=256)
        sim.step(2)  # Packet reaches A with A-D as its remaining shortest route.
        self.assertEqual(packet.route, ["A", "D"])

        sim.network.fail_link("ad")

        self.assertEqual(packet.route, ["A", "B", "D"])
        change = route_events(sim, packet.id)[-1]
        self.assertEqual(change["previous_route"], ["A", "D"])
        self.assertEqual(change["route"], ["A", "B", "D"])
        self.assertEqual((change["reason"], change["component"]), ("link_failed", "ad"))

        run_until_terminal(sim, [packet.id])

        used_links = [event["link"] for event in sim.events
                      if event["kind"] == "transmitted" and event["packet"] == packet.id]
        self.assertNotIn("ad", used_links)
        self.assertEqual(packet.path, ["S", "A", "B", "D"])
        self.assertEqual(packet.status, "delivered")

    def test_node_failure_excludes_router_and_uses_alternate_route(self):
        sim = resilient_network()
        packet = sim.inject("S", "D", size=256)
        self.assertEqual(packet.route, ["S", "A", "D"])

        sim.network.fail_node("A")

        self.assertEqual(packet.route, ["S", "B", "D"])
        change = route_events(sim, packet.id)[-1]
        self.assertEqual(change["previous_route"], ["S", "A", "D"])
        self.assertEqual(change["route"], ["S", "B", "D"])
        self.assertEqual((change["reason"], change["component"]), ("node_failed", "A"))

        run_until_terminal(sim, [packet.id])

        self.assertNotIn("A", packet.path)
        self.assertEqual(packet.path, ["S", "B", "D"])
        self.assertEqual(packet.status, "delivered")

    def test_multiple_link_failures_keep_connected_graph_routable(self):
        sim = resilient_network()
        packet = sim.inject("S", "D", size=256)

        sim.network.fail_link("ad")
        sim.network.fail_link("bd")

        self.assertEqual(sim.network.route("S", "D"), ["S", "C", "D"])
        self.assertEqual(packet.route, ["S", "C", "D"])
        changes = route_events(sim, packet.id)
        self.assertEqual([event["route"] for event in changes], [
            ["S", "B", "D"],
            ["S", "C", "D"],
        ])

        run_until_terminal(sim, [packet.id])

        used_links = {event["link"] for event in sim.events
                      if event["kind"] == "transmitted" and event["packet"] == packet.id}
        self.assertTrue(used_links.isdisjoint({"ad", "bd"}))
        self.assertEqual(packet.path, ["S", "C", "D"])
        self.assertEqual(packet.status, "delivered")

    def test_network_partition_drops_packet_as_unreachable(self):
        sim = resilient_network()
        packet = sim.inject("S", "D", size=256)

        for link_id in ("ad", "bd", "cd"):
            sim.network.fail_link(link_id)

        self.assertEqual(sim.network.route("S", "D"), [])
        self.assertEqual(packet.status, "dropped")
        self.assertEqual(packet.drop_reason, "unreachable")
        change = route_events(sim, packet.id)[-1]
        self.assertEqual(change["previous_route"], ["S", "C", "D"])
        self.assertEqual(change["route"], [])
        self.assertEqual(change["reason"], "link_failed")
        self.assertTrue(any(event["kind"] == "dropped"
                            and event["packet"] == packet.id
                            and event["reason"] == "unreachable"
                            for event in sim.events))

    def test_recovered_link_and_node_become_usable_again(self):
        for component_kind, component_id in (("link", "ad"), ("node", "A")):
            with self.subTest(component=component_kind):
                sim = resilient_network()
                packet = sim.inject("S", "D", size=256)
                fail = sim.network.fail_link if component_kind == "link" else sim.network.fail_node
                recover = (sim.network.recover_link if component_kind == "link"
                           else sim.network.recover_node)

                fail(component_id)
                self.assertEqual(packet.route, ["S", "B", "D"])
                recover(component_id)

                self.assertEqual(packet.route, ["S", "A", "D"])
                recovery_event = route_events(sim, packet.id)[-1]
                self.assertEqual(recovery_event["reason"], f"{component_kind}_restored")
                self.assertEqual(recovery_event["component"], component_id)
                run_until_terminal(sim, [packet.id])

                self.assertEqual(packet.path, ["S", "A", "D"])
                self.assertEqual(packet.status, "delivered")
                if component_kind == "link":
                    self.assertGreater(sim.network.links[component_id].transmitted_bytes, 0)
                else:
                    self.assertIn(component_id, packet.path)


if __name__ == "__main__":
    unittest.main()
