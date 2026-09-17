import time
import unittest

from fastapi.testclient import TestClient

from backend.app import create_app


TEST_TOPOLOGY = {
    "nodes": [
        {"id": "A", "name": "Hospital"},
        {"id": "B", "name": "Primary Router"},
        {"id": "C", "name": "Backup Router"},
        {"id": "D", "name": "Rescue Center"},
    ],
    "links": [
        {"id": "ab", "source": "A", "destination": "B", "bandwidth": 1024},
        {"id": "bd", "source": "B", "destination": "D", "bandwidth": 1024},
        {"id": "ac", "source": "A", "destination": "C", "bandwidth": 1024,
         "latency": 2},
        {"id": "cd", "source": "C", "destination": "D", "bandwidth": 1024},
    ],
}


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.client_context = TestClient(create_app())
        self.client = self.client_context.__enter__()

    def tearDown(self):
        self.client_context.__exit__(None, None, None)

    def start_test_simulation(self, tick_interval: float = 60) -> dict:
        response = self.client.post("/simulation/start", json={
            "topology": TEST_TOPOLOGY,
            "tick_interval_seconds": tick_interval,
            "queue_capacity": 20,
            "packet_lifetime": 100,
            "congestion_weight": 0,
        })
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_openapi_and_default_topology_expose_frontend_state(self):
        response = self.client.get("/topology")
        self.assertEqual(response.status_code, 200)
        topology = response.json()
        self.assertEqual(topology["simulation_status"], "paused")
        self.assertEqual(topology["time"], 0)
        self.assertEqual(len(topology["nodes"]), 4)
        self.assertEqual(len(topology["links"]), 4)
        self.assertEqual(topology["active_routes"], [])
        self.assertEqual(topology["packets"], [])
        self.assertEqual(topology["failures"], [])
        self.assertEqual(topology["routing_changes"], [])
        self.assertTrue(all("status" in node for node in topology["nodes"]))
        self.assertTrue(all("status" in link and "queue" in link
                            for link in topology["links"]))

        paths = self.client.get("/openapi.json").json()["paths"]
        expected = {
            "/topology", "/simulation/start", "/simulation/pause", "/simulation/reset",
            "/traffic/normal", "/traffic/emergency", "/nodes/{id}/fail",
            "/nodes/{id}/recover", "/links/{id}/fail",
            "/links/{id}/recover", "/metrics", "/events",
            "/nodes", "/links", "/disasters/trigger",
        }
        self.assertTrue(expected.issubset(paths))

        cors = self.client.options("/topology", headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        })
        self.assertEqual(cors.status_code, 200)
        self.assertEqual(cors.headers["access-control-allow-origin"],
                         "http://localhost:5173")
        preview_cors = self.client.options("/topology", headers={
            "Origin": "http://127.0.0.1:4173",
            "Access-Control-Request-Method": "GET",
        })
        self.assertEqual(preview_cors.status_code, 200)
        self.assertEqual(preview_cors.headers["access-control-allow-origin"],
                         "http://127.0.0.1:4173")

    def test_start_clock_pause_and_reset(self):
        started = self.start_test_simulation(tick_interval=0.01)
        self.assertEqual(started["simulation_status"], "running")

        deadline = time.monotonic() + 1
        metrics = self.client.get("/metrics").json()
        while metrics["elapsed_seconds"] < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
            metrics = self.client.get("/metrics").json()
        self.assertGreaterEqual(metrics["elapsed_seconds"], 2)

        paused = self.client.post("/simulation/pause").json()
        self.assertEqual(paused["simulation_status"], "paused")
        paused_time = paused["time"]
        time.sleep(0.03)
        self.assertEqual(self.client.get("/metrics").json()["elapsed_seconds"], paused_time)

        self.client.post("/traffic/normal", json={"source": "A", "destination": "D"})
        reset = self.client.post("/simulation/reset").json()
        self.assertEqual(reset, {
            "simulation_status": "paused",
            "time": 0,
            "message": "simulation reset",
        })
        self.assertEqual(self.client.get("/topology").json()["packets"], [])

    def test_normal_and_emergency_traffic_update_state_and_metrics(self):
        self.start_test_simulation()
        normal = self.client.post("/traffic/normal", json={
            "source": "A", "destination": "D", "size": 512, "count": 2,
        })
        emergency = self.client.post("/traffic/emergency", json={
            "source": "A", "destination": "D", "size": 256,
            "service": "ambulance",
        })
        self.assertEqual(normal.status_code, 200, normal.text)
        self.assertEqual(emergency.status_code, 200, emergency.text)
        self.assertEqual(normal.json()["accepted"], 2)
        self.assertTrue(all(packet["packet_class"] == "normal"
                            for packet in normal.json()["packets"]))
        self.assertEqual(emergency.json()["packets"][0]["packet_class"], "emergency")
        self.assertEqual(emergency.json()["packets"][0]["traffic"], "ambulance")

        topology = self.client.get("/topology").json()
        self.assertEqual(len(topology["packets"]), 3)
        self.assertEqual(len(topology["active_routes"]), 3)
        ab = next(link for link in topology["links"] if link["id"] == "ab")
        self.assertEqual(ab["queue"], [1, 2, 3])

        metrics = self.client.get("/metrics").json()
        self.assertEqual(metrics["packets_generated"], 3)
        self.assertEqual(metrics["traffic_classes"]["normal"]["generated"], 2)
        self.assertEqual(metrics["traffic_classes"]["emergency"]["generated"], 1)
        self.assertEqual(metrics["links"]["ab"]["queue_depth"], 3)

        events = self.client.get("/events").json()
        self.assertEqual(events["count"], 6)
        self.assertEqual([event["kind"] for event in events["events"]],
                         ["injected", "queued"] * 3)

    def test_link_failure_reroutes_and_recovery_restores_primary_route(self):
        self.start_test_simulation()
        packet = self.client.post("/traffic/normal", json={
            "source": "A", "destination": "D",
        }).json()["packets"][0]
        self.assertEqual(packet["route"], ["A", "B", "D"])

        failed = self.client.post("/links/ab/fail")
        self.assertEqual(failed.status_code, 200, failed.text)
        state = failed.json()
        self.assertIn({"component_type": "link", "component": "ab"}, state["failures"])
        self.assertEqual(state["active_routes"][0]["route"], ["A", "C", "D"])
        self.assertEqual(state["routing_changes"][-1]["reason"], "link_failed")

        recovered = self.client.post("/links/ab/recover").json()
        self.assertNotIn({"component_type": "link", "component": "ab"},
                         recovered["failures"])
        self.assertEqual(recovered["active_routes"][0]["route"], ["A", "B", "D"])
        self.assertEqual(recovered["routing_changes"][-1]["reason"], "link_restored")

    def test_node_failure_recovery_events_and_event_pagination(self):
        self.start_test_simulation()
        self.client.post("/traffic/emergency", json={
            "source": "A", "destination": "D", "service": "rescue",
        })
        failed = self.client.post("/nodes/B/fail")
        self.assertEqual(failed.status_code, 200, failed.text)
        self.assertIn({"component_type": "node", "component": "B"},
                      failed.json()["failures"])
        self.assertEqual(len(failed.json()["nodes"]), len(TEST_TOPOLOGY["nodes"]))
        self.assertEqual(len(failed.json()["links"]), len(TEST_TOPOLOGY["links"]))
        failed_node = next(node for node in failed.json()["nodes"] if node["id"] == "B")
        self.assertEqual(failed_node["status"], "failed")
        self.assertEqual(failed.json()["active_routes"][0]["route"], ["A", "C", "D"])

        recovered = self.client.post("/nodes/B/recover")
        self.assertEqual(recovered.status_code, 200, recovered.text)
        self.assertEqual(recovered.json()["failures"], [])
        page = self.client.get("/events", params={"since": 2, "limit": 2})
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.json()["count"], 2)
        self.assertEqual(page.json()["events"][0]["kind"], "node_failed")

    def test_invalid_components_endpoints_and_bodies_are_rejected(self):
        self.start_test_simulation()
        for path in ("/nodes/missing/fail", "/nodes/missing/recover",
                     "/links/missing/fail", "/links/missing/recover"):
            with self.subTest(path=path):
                response = self.client.post(path)
                self.assertEqual(response.status_code, 404)
                self.assertIn("unknown", response.json()["detail"])

        unknown_endpoint = self.client.post("/traffic/normal", json={
            "source": "missing", "destination": "D",
        })
        self.assertEqual(unknown_endpoint.status_code, 404)
        self.assertEqual(unknown_endpoint.json()["detail"], "unknown packet endpoint")

        invalid_body = self.client.post("/traffic/emergency", json={
            "source": "A", "destination": "D", "service": "vip", "count": 0,
        })
        self.assertEqual(invalid_body.status_code, 422)
        extra_field = self.client.post("/traffic/normal", json={
            "source": "A", "destination": "D", "fake_latency": 1,
        })
        self.assertEqual(extra_field.status_code, 422)

    def test_topology_editor_crud_and_reset_preserve_edited_graph(self):
        created = self.client.post("/nodes", json={
            "id": "police-1", "name": "Police Station 1", "type": "police",
            "x": 125, "y": 240,
        })
        self.assertEqual(created.status_code, 201, created.text)
        police = next(node for node in created.json()["nodes"]
                      if node["id"] == "police-1")
        self.assertEqual((police["type"], police["x"], police["y"]),
                         ("police", 125, 240))

        link = self.client.post("/links", json={
            "id": "police-router", "source": "police-1", "destination": "router",
            "bandwidth": 4096, "latency": 2,
        })
        self.assertEqual(link.status_code, 201, link.text)
        updated = self.client.patch("/links/police-router", json={
            "bandwidth": 8192, "latency": 3,
        })
        self.assertEqual(updated.status_code, 200, updated.text)
        edited_link = next(item for item in updated.json()["links"]
                           if item["id"] == "police-router")
        self.assertEqual((edited_link["bandwidth"], edited_link["latency"]),
                         (8192, 3))

        moved = self.client.patch("/nodes/police-1", json={"x": 300, "y": 90})
        moved_node = next(node for node in moved.json()["nodes"]
                          if node["id"] == "police-1")
        self.assertEqual((moved_node["x"], moved_node["y"]), (300, 90))

        self.client.post("/nodes/police-1/fail")
        self.client.post("/simulation/reset")
        reset_state = self.client.get("/topology").json()
        reset_node = next(node for node in reset_state["nodes"]
                          if node["id"] == "police-1")
        self.assertEqual(reset_node["status"], "operational")
        self.assertTrue(any(item["id"] == "police-router"
                            for item in reset_state["links"]))

        deleted_link = self.client.delete("/links/police-router")
        self.assertEqual(deleted_link.status_code, 200, deleted_link.text)
        self.assertFalse(any(item["id"] == "police-router"
                             for item in deleted_link.json()["links"]))
        deleted_node = self.client.delete("/nodes/police-1")
        self.assertEqual(deleted_node.status_code, 200, deleted_node.text)
        self.assertFalse(any(node["id"] == "police-1"
                             for node in deleted_node.json()["nodes"]))

    def test_disaster_endpoint_mutates_engine_and_records_events(self):
        self.start_test_simulation()
        response = self.client.post("/disasters/trigger", json={
            "disaster": "earthquake", "intensity": "medium", "seed": 11,
        })
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["failed_nodes"])
        self.assertTrue(body["failed_links"])
        failed = {(item["component_type"], item["component"])
                  for item in body["topology"]["failures"]}
        self.assertTrue(all(("node", node_id) in failed
                            for node_id in body["failed_nodes"]))
        self.assertTrue(all(("link", link_id) in failed
                            for link_id in body["failed_links"]))
        kinds = [event["kind"] for event in self.client.get("/events").json()["events"]]
        self.assertEqual(kinds[0], "disaster_triggered")
        self.assertEqual(kinds[-1], "recalculating_routes")

        invalid = self.client.post("/disasters/trigger", json={
            "disaster": "meteor", "intensity": "extreme",
        })
        self.assertEqual(invalid.status_code, 422)


if __name__ == "__main__":
    unittest.main()
