import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("fqapp_state", Path(__file__).with_name("fqapp_state.py"))
state = importlib.util.module_from_spec(spec)
spec.loader.exec_module(state)


def device(identity, uses=1):
    return {"device_id": str(identity), "install_id": str(identity), "secret_key": "fixture-only-key", "use_count": uses, "last_used": str(uses)}


class SnapshotTests(unittest.TestCase):
    def test_concurrent_instance_snapshots_merge(self):
        first = state.merge_pool({"android": []}, {"android": [device(1)]}, [])
        second = state.merge_pool(first, {"android": [device(2)]}, [])
        self.assertEqual({d["device_id"] for d in second["android"]}, {"1", "2"})

    def test_old_instance_does_not_rollback_usage(self):
        result = state.merge_pool({"android": [device(1, 5)]}, {"android": [device(1, 1)]}, [])
        self.assertEqual(result["android"][0]["use_count"], 5)

    def test_failed_device_removed_while_other_instance_survives(self):
        result = state.merge_pool({"android": [device(1), device(2)]}, {"android": [device(3)]}, ["1"])
        self.assertEqual({d["device_id"] for d in result["android"]}, {"2", "3"})

    def test_pool_is_bounded(self):
        result = state.merge_pool({"android": [device(i) for i in range(1, 21)]}, {"android": [device(21)]}, [])
        self.assertEqual(len(result["android"]), 20)

    def test_invalid_snapshots_rejected(self):
        for payload in [{}, {"android": {}}, {"android": [{"device_id": "bad"}]}, {"android": [device(1)] * 21}]:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    state.merge_pool({"android": []}, payload, [])

    def test_empty_device_key_rejected(self):
        d = device(1)
        d["secret_key"] = ""
        with self.assertRaises(ValueError):
            state.merge_pool({"android": []}, {"android": [d]}, [])


if __name__ == "__main__":
    unittest.main()
