# Huber

Nectar notification-driven action runner. Huber is a small spice-bee — it
consumes OpenStack notifications forwarded from ceilometer and runs
configurable handlers in response.

## Overview

Huber is a standalone service that subscribes to a topic populated by
ceilometer's event_pipeline. Each event in the batch is unwrapped from the
ceilometer envelope and dispatched to pluggable handlers. A handler can match
against one or more event types and execute arbitrary Python code when a
matching event arrives.

The intent is to give operators a single place to wire ad-hoc reactions to
cloud events (audit, cleanup, enrichment, alerting, etc.) without having to
stand up a new service every time.

## How events get to Huber

Huber does not subscribe directly to upstream services. Instead, ceilometer's
event_pipeline is configured to forward selected events to huber's own
topic. The end-to-end path:

```
nova/neutron/keystone/... → ceilometer event_pipeline →
    publishes to (exchange=ceilometer, topic=huber) →
    huber-notification consumes and dispatches to handlers
```

A minimal ceilometer `event_pipeline.yaml` sink that feeds huber:

```yaml
sources:
  - name: event_source
    events:
      - "*"
    sinks:
      - huber_sink
sinks:
  - name: huber_sink
    publishers:
      - notifier://?topic=huber
```

## Huber Concepts

### Event

An `Event` is one notification unwrapped from the ceilometer envelope:

 * `event_type` — e.g. `compute.instance.create.end`
 * `traits` — flat `dict[str, value]` (ceilometer `[name, type, value]`
   triples are collapsed to `name → value`)
 * `message_id` / `generated` — ceilometer message metadata
 * `raw_payload` — the original event dict, kept for handlers that need
   trait types or other fields

### Handlers

A handler is a Python class that declares which event types it cares about and
implements a `handle(event)` method. Handlers are registered as `huber.handler`
stevedore entry points, so adding a new handler is a matter of dropping a
package onto the Python path and listing it in `huber.conf`.

A handler can match event types either:

 * exactly — e.g. `compute.instance.create.end`
 * by glob — e.g. `compute.instance.*` or `*.delete.end`

Only handlers whose names appear in the `[handlers] enabled` config option
are loaded.

## Components

### huber-notification

Cotyledon-managed notification listener. Receives ceilometer-forwarded
messages, unwraps each event, and dispatches them to enabled handlers.

## Configuration

See `etc/huber/huber.conf.sample` (generated via `tox -e genconfig`).

A minimal config:

```ini
[DEFAULT]
transport_url = rabbit://guest:guest@rabbit:5672/

[notification]
exchange = ceilometer
topic = huber
pool = huber

[handlers]
enabled = logging
```
