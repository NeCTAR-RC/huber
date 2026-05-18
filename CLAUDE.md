# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

- Run all tests: `tox -e py312`
- Run a single test: `tox -e py312 -- huber/tests/unit/notification/test_endpoints.py`
- Run with coverage: `tox -e cover`
- Run lint checks: `tox -e pep8`
- Generate config sample: `tox -e genconfig`

Always run tests before committing code.

## Project Overview

Huber is a Nectar service that consumes OpenStack notifications **forwarded by ceilometer's event_pipeline** and dispatches them to pluggable handlers. It is intentionally small: a notification listener, an event unwrapper, a dispatcher, and a stevedore-based handler registry.

Huber does not subscribe to upstream services directly. ceilometer is the fan-in point; huber listens on a single `(exchange, topic)` populated by ceilometer's pipeline.

## Architecture: One Service

### huber-notification (Event Consumer)
Entry point: `huber/cmd/notification.py`

- Subscribes to a single `Target(exchange, topic)` configured via the
  `[notification]` group (defaults: `ceilometer:huber`)
- `ConsumerService` (`huber/notification/consumer.py`): cotyledon service
  that starts an oslo.messaging notification listener
- `NotificationEndpoint` (`huber/notification/endpoints.py`): implements
  the ceilometer-pipeline `sample()` contract — each incoming message
  carries a list of event dicts in the payload
- `event.from_ceilometer_payload` (`huber/notification/event.py`): converts
  the raw payload into `Event` dataclasses with `traits` flattened into a
  `dict[str, value]`
- `Dispatcher` (`huber/handlers/dispatcher.py`): loads handlers via
  stevedore (`huber.handler` namespace), matches `event.event_type` against
  each handler's declared patterns (exact or fnmatch glob), and invokes
  `handler.handle(event)`

### Handlers

Handlers subclass `huber.handlers.base.HandlerBase` and declare:

 * `event_types` — list of strings; supports fnmatch globs (`*.delete.end`)
 * `handle(event)` — the action; `event` is a `huber.notification.event.Event`

Handlers are registered as `huber.handler` stevedore entry points in
`setup.cfg`. Only handlers listed in `[handlers] enabled` are instantiated
at startup; others stay dormant. The bundled `logging` handler matches `*`
and just logs every event — useful as a sanity check.

## Key Patterns

- Config is oslo.config, loaded by `huber.common.config.init()` from
  `/etc/huber/huber.conf` by default.
- Logging is oslo.log.
- Service lifecycle is cotyledon.
- Endpoints always return `NotificationResult.HANDLED` — re-queueing a
  poison message just loops.
- Tests are stestr + plain `unittest.TestCase`; coverage minimum 90%.

## Testing Patterns

- `huber/tests/unit/base.py` provides a `TestCase` that initialises
  oslo.config from `huber/tests/etc/huber.conf` and resets it on teardown.
- Handlers under test should be invoked directly with an `Event` — no
  message bus required.
- `_ceilometer_payload()` helpers in tests build realistic payload shapes
  matching what ceilometer's event_pipeline produces.
