"""The planner's action target: a recommendation carries the device its own evidence names, so a device request has a recipient."""
import unittest
from types import SimpleNamespace

from operations.graph import action_target, cited_device


def node(kind, **properties):
    return SimpleNamespace(kind=kind, properties=properties)


def tools(nodes=None, external=None, milestones=(), device_reports=None):
    return SimpleNamespace(nodes=nodes or {}, external=external or {}, device_reports=device_reports or {},
                           _journey=lambda: {"milestones": list(milestones)})


class ActionTargetTests(unittest.TestCase):
    def test_cited_heartbeat_names_the_device_when_the_snapshot_names_none(self):
        t = tools(nodes={"DEMO-SCAN-1": node("ScanEvent", device_ref="DEMO-DEV-B")},
                  external={"DEMO-HB-1": {"kind": "DeviceHeartbeat", "device_id": "DEMO-DEV-A"}})
        target = action_target(t, ["DEMO-SCAN-1", "DEMO-HB-1", "DEMO-CMP-x"])
        self.assertEqual(target["device_id"], "DEMO-DEV-A")  # a cited device record wins over a cited scan's device
        self.assertEqual(target["expected_evidence"], [])

    def test_cited_scan_device_computation_and_device_node(self):
        self.assertEqual(cited_device(tools(nodes={"S": node("ScanEvent", device_ref="DEMO-DEV-B")}), ["S"]), "DEMO-DEV-B")
        self.assertEqual(cited_device(tools(external={"C": {"kind": "ComputedResult", "computation": "DEVICE_TELEMETRY",
                                                           "device_id": "DEMO-DEV-C"}}), ["C"]), "DEMO-DEV-C")
        self.assertEqual(cited_device(tools(nodes={"DEMO-DEV-D": node("Device")}), ["DEMO-DEV-D"]), "DEMO-DEV-D")
        self.assertEqual(cited_device(tools(nodes={"H": node("DeviceHeartbeat", device_id="DEMO-DEV-E")}), ["H"]), "DEMO-DEV-E")

    def test_no_device_in_the_evidence_leaves_the_target_empty(self):
        t = tools(nodes={"DEMO-SCAN-1": node("ScanEvent"), "DEMO-ATT-1": node("DeliveryAttempt", device_ref="DEMO-DEV-Z")},
                  external={"C": {"kind": "ComputedResult", "computation": "WEIGHT_COMPARISON", "device_id": "DEMO-DEV-Y"}})
        self.assertIsNone(action_target(t, ["DEMO-SCAN-1", "DEMO-ATT-1", "C", "unknown-id"])["device_id"])
        self.assertIsNone(action_target(t)["device_id"])

    def test_a_silent_expected_device_from_the_snapshot_still_comes_first(self):
        row = {"state": "missing_after_deadline", "package_id": "P", "predicate": "RECEIVED", "location_id": "L",
               "expected_device_telemetry": [{"device_id": "DEMO-DEV-S"}]}
        t = tools(external={"DEMO-HB-1": {"kind": "DeviceHeartbeat", "device_id": "DEMO-DEV-A"}}, milestones=[row],
                  device_reports={"DEMO-DEV-S": {"reporting_state": "SILENT"}})
        target = action_target(t, ["DEMO-HB-1"])
        self.assertEqual(target["device_id"], "DEMO-DEV-S")
        self.assertEqual(target["expected_evidence"], [{"package_id": "P", "predicate": "RECEIVED", "location_id": "L"}])


if __name__ == "__main__":
    unittest.main()
