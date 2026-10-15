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

    def test_a_rescan_is_targeted_where_this_shipments_package_was_misread(self):
        def n(id, kind, **properties):
            return SimpleNamespace(id=id, kind=kind, properties=properties)
        nodes = {k.id: k for k in (
            n("P", "Package", shipment_id="S", manifest_barcode="M"),
            n("Q", "Package", shipment_id="OTHER", manifest_barcode="M"),
            n("F-MISREAD", "Hub"), n("F-READ", "Hub"), n("F-FOREIGN", "Hub"), n("VAN", "Vehicle"),
            n("S1", "ScanEvent", shipment_id="S", package_id="P", facility_id="F-MISREAD", observed_barcode="X", device_ref="D1"),
            n("S2", "ScanEvent", shipment_id="S", package_id="P", facility_id="F-READ", observed_barcode="M", device_ref="D2"),
            n("S3", "ScanEvent", shipment_id="S", package_id="P", facility_id="VAN", observed_barcode="X", device_ref="D3"),
            n("S4", "ScanEvent", shipment_id="OTHER", package_id="Q", facility_id="F-FOREIGN", observed_barcode="X"))}
        t = tools(nodes=nodes)
        t.sid = "S"
        target = action_target(t, [], "REQUEST_RESCAN")
        # Only the facility of this shipment's own mismatched read: not a matching read, not a non-facility location,
        # not another shipment's record.
        self.assertEqual(target["facility_ids"], ["F-MISREAD"])
        self.assertEqual(target["baseline_device_ids"], ["D1", "D3"])   # unchanged: the devices of the mismatched reads
        for other in (None, "INITIATE_CUSTODY_RECONCILIATION", "REQUEST_DEVICE_SYNC"):
            self.assertEqual(action_target(t, [], other)["facility_ids"], [])   # other actions' targets are unchanged


if __name__ == "__main__":
    unittest.main()
