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

from unittest import mock

from huber.handlers import common
from huber.tests.unit import base as test_base


class TestRefId(test_base.TestCase):
    def test_extracts_id_from_dict(self):
        self.assertEqual("abc", common.ref_id({"id": "abc"}))

    def test_returns_scalar_unchanged(self):
        self.assertEqual("abc", common.ref_id("abc"))

    def test_dict_without_id_returns_none(self):
        self.assertIsNone(common.ref_id({}))


class TestDisplayName(test_base.TestCase):
    def test_prefers_full_name(self):
        obj = mock.Mock(full_name="Alice Smith", name="alice", id="u-1")
        self.assertEqual("Alice Smith", common.display_name(obj))

    def test_falls_back_to_name(self):
        obj = mock.Mock(spec=["name", "id"], name="alice", id="u-1")
        obj.name = "alice"
        self.assertEqual("alice", common.display_name(obj))

    def test_falls_back_to_id(self):
        obj = mock.Mock(spec=["id"], id="u-1")
        self.assertEqual("u-1", common.display_name(obj))

    def test_unknown_when_nothing_set(self):
        obj = mock.Mock(spec=[])
        self.assertEqual("(unknown)", common.display_name(obj))
