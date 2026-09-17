import unittest

from simulator import Link, Network, Simulator


class TrafficPriorityIntegrationTests(unittest.TestCase):
    def test_emergency_packet_overtakes_normal_packets_on_congested_link(self):
        sim = Simulator(
            Network(["source", "destination"], [
                Link("bottleneck", "source", "destination", bandwidth=1024),
            ]),
            queue_capacity=10,
            congestion_weight=0,
        )
        normal_packets = [
            sim.inject("source", "destination", size=1024) for _ in range(5)
        ]

        sim.step()  # One normal packet starts; four remain in the link queue.
        emergency = sim.inject("source", "destination", "ambulance", size=1024)

        self.assertEqual(sim.link_queues["bottleneck"], [2, 3, 4, 5, emergency.id])
        sim.step()

        transmissions = [event for event in sim.events if event["kind"] == "transmitted"]
        self.assertEqual([event["packet"] for event in transmissions[:2]],
                         [normal_packets[0].id, emergency.id])
        self.assertEqual(transmissions[1]["priority"], "emergency")
        self.assertTrue(all(packet.status == "queued" for packet in normal_packets[1:]))

        while any(packet.status in {"queued", "in_flight"}
                  for packet in normal_packets + [emergency]):
            sim.step()

        self.assertEqual(emergency.packet_class, "emergency")
        self.assertEqual(emergency.latency_seconds, 2)
        self.assertTrue(all(emergency.delivery_time < packet.delivery_time
                            for packet in normal_packets[1:]))

        metrics = sim.metrics()
        self.assertEqual(metrics["packets_generated"], 6)
        self.assertEqual(metrics["packets_delivered"], 6)
        self.assertEqual(metrics["packets_dropped"], 0)
        self.assertEqual(metrics["emergency_packet_latency_seconds"], 2)
        self.assertEqual(metrics["normal_packet_latency_seconds"], 4.8)
        self.assertGreater(metrics["normal_packet_latency_seconds"],
                           metrics["emergency_packet_latency_seconds"])
        self.assertAlmostEqual(metrics["throughput_bps"], 6 * 1024 * 8 / 7)
        self.assertAlmostEqual(metrics["links"]["bottleneck"]["utilization"], 6 / 7)
        emergency_snapshot = sim.snapshot()["packets"][emergency.id - 1]
        self.assertEqual(emergency_snapshot["latency_seconds"], 2)
        self.assertEqual(emergency_snapshot["packet_class"], "emergency")
        self.assertEqual(metrics["traffic_classes"]["emergency"], {
            "generated": 1,
            "delivered": 1,
            "dropped": 0,
            "pending": 0,
            "average_latency_seconds": 2,
        })

    def test_generic_and_service_emergency_traffic_map_to_emergency_class(self):
        services = ["EMERGENCY", "hospital", "ambulance", "police", "fire", "rescue"]
        for service in services:
            with self.subTest(service=service):
                sim = Simulator(Network(["A", "B"], [Link("ab", "A", "B")]))
                packet = sim.inject("A", "B", service)
                self.assertEqual(packet.packet_class, "emergency")
                self.assertEqual(sim.link_queues["ab"], [packet.id])


if __name__ == "__main__":
    unittest.main()
