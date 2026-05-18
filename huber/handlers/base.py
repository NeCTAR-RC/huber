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

import abc
import fnmatch


class HandlerBase(abc.ABC):
    """Base class for huber notification handlers.

    Subclasses declare which event types they care about by setting
    ``event_types`` to a list of patterns. Patterns support fnmatch globs,
    so ``compute.instance.*`` matches every ``compute.instance.…`` event
    and ``*`` matches everything.
    """

    event_types: list[str] = []

    def matches(self, event_type):
        for pattern in self.event_types:
            if fnmatch.fnmatchcase(event_type, pattern):
                return True
        return False

    @abc.abstractmethod
    def handle(self, event):
        """Run the handler's action for one Event."""
