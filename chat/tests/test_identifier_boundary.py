import copy
import unittest

from operations.identifiers import OPAQUE_FIELDS, public_value, storage_value


class IdentifierBoundaryTests(unittest.TestCase):
    def test_all_id_keyed_evidence_maps_resolve_and_roundtrip(self):
        record = "DEMO-SHP-000064-SCAN-005"
        other = "DEMO-SHP-000194-CUST-003"
        original = {
            "evidence_ids": [record, other],
            "evidence_index": {record: {"scope": "shipment"}, other: {"scope": "other_shipment"}},
            "computed_results": {"DEMO-CMP-1": {"input_ids": [record, other]}},
            "cited_records": {record: {"package_id": "DEMO-SHP-000064-PKG-01"}},
            "cited_external_records": {other: {"from_id": "DEMO-VEH-1"}},
        }
        before = copy.deepcopy(original)
        public = public_value(original)
        for ref in public["evidence_ids"]:
            self.assertIn(ref, public["evidence_index"])
        self.assertEqual(public["evidence_index"]["SYN-SHP-000194-CUST-003"]["scope"], "other_shipment")
        self.assertEqual(public["computed_results"]["SYN-CMP-1"]["input_ids"], public["evidence_ids"])
        self.assertIn(public["evidence_ids"][0], public["cited_records"])
        self.assertIn(public["evidence_ids"][1], public["cited_external_records"])
        self.assertEqual(storage_value(public), original)
        self.assertEqual(original, before)

    def test_key_collision_fails_closed_in_either_direction(self):
        for convert in (public_value, storage_value):
            for rows in ({"DEMO-X": 1, "SYN-X": 2}, {"SYN-X": 1, "DEMO-X": 1}):
                with self.assertRaisesRegex(ValueError, "collision"):
                    convert({"evidence_index": rows})

    def test_schema_keys_and_opaque_tokens_remain_exact(self):
        original = {"schema_demo_name": "ordinary", **{key: "DEMO-signed-SYN-token" for key in OPAQUE_FIELDS}}
        self.assertEqual(public_value(original), original)
        self.assertEqual(storage_value(original), original)
        self.assertEqual(public_value({"demo": True, "synthetic": True}), {"synthetic": True})


if __name__ == "__main__":
    unittest.main()
