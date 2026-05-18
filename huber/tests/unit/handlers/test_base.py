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

from huber.handlers import base
from huber.tests.unit import base as test_base


class _Handler(base.HandlerBase):
    def __init__(self, patterns):
        self.event_types = patterns

    def handle(self, event):
        pass


class TestHandlerBase(test_base.TestCase):
    def test_exact_match(self):
        h = _Handler(["compute.instance.create.end"])
        self.assertTrue(h.matches("compute.instance.create.end"))
        self.assertFalse(h.matches("compute.instance.delete.end"))

    def test_glob_match(self):
        h = _Handler(["compute.instance.*"])
        self.assertTrue(h.matches("compute.instance.create.end"))
        self.assertTrue(h.matches("compute.instance.delete.end"))
        self.assertFalse(h.matches("network.port.create.end"))

    def test_wildcard_match(self):
        h = _Handler(["*"])
        self.assertTrue(h.matches("anything.at.all"))

    def test_empty_patterns_match_nothing(self):
        h = _Handler([])
        self.assertFalse(h.matches("compute.instance.create.end"))

    def test_multiple_patterns(self):
        h = _Handler(["compute.*", "*.delete.end"])
        self.assertTrue(h.matches("compute.instance.create.end"))
        self.assertTrue(h.matches("network.port.delete.end"))
        self.assertFalse(h.matches("identity.user.create.end"))
