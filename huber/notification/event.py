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

import dataclasses
from typing import Any


@dataclasses.dataclass(frozen=True)
class Event:
    """A single notification as unwrapped from the ceilometer envelope.

    ceilometer's event_pipeline publishes a list of events; each one is a
    dict with ``event_type``, ``traits`` (a list of ``[name, type, value]``
    triples), ``message_id``, ``generated`` and ``raw``. Huber flattens
    ``traits`` into a ``dict[str, Any]`` for handler convenience, but keeps
    the original event under ``raw_payload`` for handlers that need types
    or trait metadata.
    """

    event_type: str
    traits: dict[str, Any]
    message_id: str | None
    generated: str | None
    raw_payload: dict[str, Any]


def from_ceilometer_payload(payload):
    """Build Event objects from a ceilometer notification payload.

    The payload is a list of event dicts; ceilometer batches events so a
    single notification may carry several. Malformed entries are skipped
    with a warning rather than aborting the whole batch.
    """
    if not isinstance(payload, list):
        raise ValueError(
            f"Expected ceilometer payload to be a list, got {type(payload)}"
        )

    events = []
    for entry in payload:
        event_type = entry.get("event_type")
        if not event_type:
            continue
        traits = {}
        for trait in entry.get("traits") or []:
            # ceilometer traits are [name, type_id, value]; we only need
            # name and value here.
            if len(trait) >= 3:
                traits[trait[0]] = trait[2]
        events.append(
            Event(
                event_type=event_type,
                traits=traits,
                message_id=entry.get("message_id"),
                generated=entry.get("generated"),
                raw_payload=entry,
            )
        )
    return events
