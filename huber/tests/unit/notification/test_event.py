#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from huber.notification import event as event_mod
from huber.tests.unit import base as test_base


class TestFromCeilometerPayload(test_base.TestCase):
    def test_single_event(self):
        payload = [
            {
                "event_type": "compute.instance.create.end",
                "traits": [
                    ["instance_id", 1, "i-1"],
                    ["project_id", 1, "p-1"],
                ],
                "message_id": "mid",
                "generated": "2026-05-18T00:00:00",
                "raw": {},
            }
        ]
        events = event_mod.from_ceilometer_payload(payload)
        self.assertEqual(1, len(events))
        event = events[0]
        self.assertEqual("compute.instance.create.end", event.event_type)
        self.assertEqual(
            {"instance_id": "i-1", "project_id": "p-1"}, event.traits
        )
        self.assertEqual("mid", event.message_id)
        self.assertEqual("2026-05-18T00:00:00", event.generated)

    def test_batch_yields_multiple_events(self):
        payload = [
            {"event_type": "a.b.c", "traits": [], "message_id": "1"},
            {"event_type": "x.y.z", "traits": [], "message_id": "2"},
        ]
        events = event_mod.from_ceilometer_payload(payload)
        self.assertEqual(["a.b.c", "x.y.z"], [e.event_type for e in events])

    def test_entry_without_event_type_is_skipped(self):
        payload = [
            {"event_type": "", "traits": []},
            {"traits": []},
            {"event_type": "real.event", "traits": []},
        ]
        events = event_mod.from_ceilometer_payload(payload)
        self.assertEqual(["real.event"], [e.event_type for e in events])

    def test_missing_traits_treated_as_empty(self):
        payload = [{"event_type": "a.b.c"}]
        events = event_mod.from_ceilometer_payload(payload)
        self.assertEqual({}, events[0].traits)

    def test_short_trait_triples_are_skipped(self):
        payload = [
            {
                "event_type": "a.b.c",
                "traits": [
                    ["good", 1, "value"],
                    ["bad", 1],
                ],
            }
        ]
        events = event_mod.from_ceilometer_payload(payload)
        self.assertEqual({"good": "value"}, events[0].traits)

    def test_non_list_payload_raises(self):
        self.assertRaises(
            ValueError, event_mod.from_ceilometer_payload, {"not": "list"}
        )

    def test_raw_payload_preserved(self):
        entry = {
            "event_type": "a.b.c",
            "traits": [],
            "message_signature": "sig",
        }
        events = event_mod.from_ceilometer_payload([entry])
        self.assertIs(entry, events[0].raw_payload)
