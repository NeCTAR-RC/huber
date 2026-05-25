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

from huber.handlers import password as pw
from huber.notification import event as event_mod
from huber.tests.unit import base as test_base


def _stub(**attrs):
    obj = mock.Mock(spec=list(attrs.keys()))
    for name, value in attrs.items():
        setattr(obj, name, value)
    return obj


def _user(uid, email, name=None, enabled=True):
    return _stub(id=uid, email=email, name=name or uid, enabled=enabled)


def _event(traits, event_type=pw.UPDATED_EVENT, message_id="mid"):
    return event_mod.Event(
        event_type=event_type,
        traits=traits,
        message_id=message_id,
        generated="2026-05-25T00:00:00",
        raw_payload={},
    )


class TestPasswordHandler(test_base.TestCase):
    def setUp(self):
        super().setUp()
        self.handler = pw.PasswordHandler()
        self.ks = mock.Mock()
        self.taynac = mock.Mock()
        self.handler._ks = self.ks
        self.handler._taynac = self.taynac

    def _wire_user(self, user):
        self.ks.users.get.side_effect = lambda uid: (
            user if uid == user.id else None
        )

    def test_sends_message_to_target_user(self):
        user = _user("u-1", "alice@example.com", "Alice")
        self._wire_user(user)

        self.handler.handle(
            _event({"action": "update/password", "target_user_id": "u-1"})
        )

        self.taynac.messages.send.assert_called_once()
        call = self.taynac.messages.send.call_args
        self.assertEqual("alice@example.com", call.kwargs["recipient"])
        self.assertIn("Alice", call.kwargs["body"])

    def test_self_service_wording(self):
        user = _user("u-1", "alice@example.com", "Alice")
        self._wire_user(user)

        self.handler.handle(
            _event(
                {
                    "action": "update/password",
                    "target_user_id": "u-1",
                    "initiator_id": "u-1",
                }
            )
        )

        body = self.taynac.messages.send.call_args.kwargs["body"]
        self.assertIn("changed", body)
        self.assertNotIn("administrator", body)

    def test_admin_reset_wording(self):
        user = _user("u-1", "alice@example.com", "Alice")
        self._wire_user(user)

        self.handler.handle(
            _event(
                {
                    "action": "update/password",
                    "target_user_id": "u-1",
                    "initiator_id": "admin-u",
                }
            )
        )

        body = self.taynac.messages.send.call_args.kwargs["body"]
        self.assertIn("reset", body)
        self.assertIn("administrator", body)

    def test_falls_back_to_resource_id_trait(self):
        user = _user("u-1", "alice@example.com")
        self._wire_user(user)

        self.handler.handle(
            _event({"action": "update/password", "resource_id": "u-1"})
        )

        self.taynac.messages.send.assert_called_once()
        call = self.taynac.messages.send.call_args
        self.assertEqual("alice@example.com", call.kwargs["recipient"])

    def test_falls_back_to_user_trait(self):
        user = _user("u-1", "alice@example.com")
        self._wire_user(user)

        self.handler.handle(
            _event({"action": "update/password", "user": "u-1"})
        )

        self.taynac.messages.send.assert_called_once()

    def test_non_password_action_is_a_noop(self):
        self.handler.handle(
            _event({"action": "update", "target_user_id": "u-1"})
        )
        self.ks.users.get.assert_not_called()
        self.taynac.messages.send.assert_not_called()

    def test_missing_action_is_a_noop(self):
        self.handler.handle(_event({"target_user_id": "u-1"}))
        self.ks.users.get.assert_not_called()
        self.taynac.messages.send.assert_not_called()

    def test_missing_target_user_is_a_noop(self):
        self.handler.handle(_event({"action": "update/password"}))
        self.ks.users.get.assert_not_called()
        self.taynac.messages.send.assert_not_called()

    def test_disabled_user_skips_send(self):
        user = _user("u-1", "alice@example.com", enabled=False)
        self._wire_user(user)

        self.handler.handle(
            _event({"action": "update/password", "target_user_id": "u-1"})
        )
        self.taynac.messages.send.assert_not_called()

    def test_user_without_email_skips_send(self):
        user = _user("u-1", "")
        self._wire_user(user)

        self.handler.handle(
            _event({"action": "update/password", "target_user_id": "u-1"})
        )
        self.taynac.messages.send.assert_not_called()

    def test_taynac_failure_is_logged_not_raised(self):
        user = _user("u-1", "alice@example.com")
        self._wire_user(user)
        self.taynac.messages.send.side_effect = RuntimeError("smtp down")

        # Must not propagate.
        self.handler.handle(
            _event({"action": "update/password", "target_user_id": "u-1"})
        )
        self.taynac.messages.send.assert_called_once()

    def test_matches_only_user_updated_event(self):
        self.assertTrue(self.handler.matches(pw.UPDATED_EVENT))
        self.assertFalse(self.handler.matches("identity.user.created"))
        self.assertFalse(self.handler.matches("identity.user.deleted"))
        self.assertFalse(
            self.handler.matches("identity.role_assignment.created")
        )
