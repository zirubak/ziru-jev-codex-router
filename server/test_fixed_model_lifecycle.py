"""Fixed routing decisions expire on selection and prerequisite changes."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading
import time
import unittest
import urllib.error
from unittest import mock

import jev_server as jev
import test_per_call_routing as fixture
from test_fixed_model_routes import effort_answer
from test_per_call_routing import Edge, message, payload_for, tool_call, tool_step


class FixedModelLifecycleHttp(unittest.TestCase):
    def setUp(self) -> None:
        fixture.PerCallEndToEnd.setUp(self)
        self.judge = self.enterContext(mock.patch.object(
            jev, "call_jev_routed", return_value=effort_answer("low", "user_turn"),
        ))

    tearDown = fixture.PerCallEndToEnd.tearDown
    call = fixture.PerCallEndToEnd.call

    def test_switch_back_rejudges_instead_of_restoring_previous_lease(self) -> None:
        for first, middle in (("sol", "astra"), ("astra", "sol"), ("sol", "auto")):
            with self.subTest(first=first, middle=middle):
                history = [message("user", "Inspect fixture")]
                key = f"switch-{first}-{middle}"
                self.judge.return_value = effort_answer("low", "user_turn")
                self.call(payload_for(history, cache_key=key, model=first))
                history += [tool_call("c1"), tool_step("c1", "ok")]
                self.judge.return_value = fixture.answer(jev.SOL_61, "max")
                self.call(payload_for(history, cache_key=key, model=middle))
                before = self.judge.call_count
                history += [tool_call("c2"), tool_step("c2", "ok")]
                self.call(payload_for(history, cache_key=key, model=first))
                self.assertEqual(self.judge.call_count, before + 1)
                self.assertEqual(self.records[-1]["effort"], "max")

    def test_switch_in_another_session_preserves_clean_lease(self) -> None:
        history = [message("user", "Inspect fixture")]
        self.call(payload_for(history, cache_key="one", model="sol"))
        self.call(payload_for(history, cache_key="two", model="astra"))
        continuation = history + [tool_call("c1"), tool_step("c1", "ok")]
        self.call(payload_for(continuation, cache_key="one", model="sol"))
        self.assertEqual(self.judge.call_count, 2)
        self.assertEqual(self.records[-1]["decision_source"], "lease")

    def test_missing_key_discards_lease_and_rejudges_when_key_returns(self) -> None:
        for slug in ("sol", "astra"):
            with self.subTest(slug=slug):
                history = [message("user", "Inspect fixture")]
                self.call(payload_for(history, cache_key=slug, model=slug))
                history += [tool_call("c1"), tool_step("c1", "ok")]
                with mock.patch.object(jev, "load_key", return_value=None):
                    self.call(payload_for(history, cache_key=slug, model=slug))
                self.assertEqual(self.records[-1]["effort"], "high")
                self.assertEqual(self.records[-1]["decision_source"], "technical_fallback")
                before = self.judge.call_count
                self.call(payload_for(history, cache_key=slug, model=slug))
                self.assertEqual(self.judge.call_count, before + 1)

    def test_superseded_inflight_call_cannot_change_newer_lease(self) -> None:
        for old_fails in (False, True):
            with self.subTest(old_fails=old_fails):
                self._check_superseded_call(old_fails)

    def _check_superseded_call(self, old_fails: bool) -> None:
        entered, release = threading.Event(), threading.Event()
        first = True

        def judge(*args: object, **kwargs: object) -> dict:
            nonlocal first
            if first:
                first = False
                entered.set()
                if not release.wait(10):
                    raise TimeoutError("test did not release the first judgment")
                if old_fails:
                    raise RuntimeError("superseded judgment failed")
                return effort_answer("low", "user_turn")
            return effort_answer("max", "user_turn" if old_fails else "one_call")

        self.judge.side_effect = judge
        before = self.judge.call_count
        history = [message("user", "Inspect fixture")]
        key = f"inflight-{old_fails}"
        with ThreadPoolExecutor(max_workers=1) as pool:
            old = pool.submit(self.call, payload_for(history, cache_key=key, model="sol"))
            try:
                self.assertTrue(entered.wait(3))
                continuation = history + [tool_call("c1"), tool_step("c1", "ok")]
                self.call(payload_for(continuation, cache_key=key, model="astra"))
                self.call(payload_for(continuation, cache_key=key, model="sol"))
            finally:
                release.set()
            self.assertEqual(old.result(timeout=10)[0], 200)
        self.call(payload_for(continuation, cache_key=key, model="sol"))
        self.assertEqual(self.judge.call_count - before, 3 if old_fails else 4)
        self.assertEqual(self.records[-1]["effort"], "max")

    def test_superseded_prelookup_request_preserves_current_lease(self) -> None:
        entered, release = threading.Event(), threading.Event()
        first = True

        def key() -> str:
            nonlocal first
            if first:
                first = False
                entered.set()
                if not release.wait(10):
                    raise TimeoutError("test did not release the first key lookup")
            return "fixture-key"

        history = [message("user", "Inspect fixture")]
        self.judge.return_value = effort_answer("max", "user_turn")
        with mock.patch.object(jev, "load_key", side_effect=key):
            with ThreadPoolExecutor(max_workers=1) as pool:
                old = pool.submit(self.call, payload_for(history, model="sol"))
                try:
                    self.assertTrue(entered.wait(3))
                    continuation = history + [tool_call("c1"), tool_step("c1", "ok")]
                    self.call(payload_for(continuation, model="astra"))
                    self.call(payload_for(continuation, model="sol"))
                finally:
                    release.set()
                self.assertEqual(old.result(timeout=10)[0], 200)
            self.call(payload_for(continuation, model="sol"))
        self.assertEqual(self.judge.call_count, 3)
        self.assertEqual(self.records[-1]["decision_source"], "lease")

    def test_evicted_session_cannot_restore_old_selection_lease(self) -> None:
        history = [message("user", "Inspect fixture")]
        with mock.patch.object(jev, "ROUTE_REQUEST_LIMIT", 2):
            for key in ("one", "two", "three"):
                self.call(payload_for(history, cache_key=key, model="sol"))
            continuation = history + [tool_call("c1"), tool_step("c1", "ok")]
            self.judge.return_value = effort_answer("max")
            self.call(payload_for(continuation, cache_key="one", model="astra"))
            self.call(payload_for(continuation, cache_key="one", model="sol"))
        self.assertEqual(self.judge.call_count, 5)
        self.assertEqual(self.records[-1]["effort"], "max")

    def test_failed_or_missing_terminal_retains_automatic_quota_state(self) -> None:
        created = b'data: {"type":"response.created","response":{"id":"r"}}\n\n'
        for slug in ("sol", "astra"):
            for lite in (False, True):
                for terminal in ("response.failed", "response.incomplete", None):
                    with self.subTest(slug=slug, lite=lite, terminal=terminal):
                        body = created
                        if terminal:
                            body += ('data: {"type":"' + terminal + '","response":'
                                     '{"id":"r","error":{"code":"usage_limit_reached"}}}\n\n').encode()
                        body += b'data: [DONE]\n\n'
                        with mock.patch.object(jev, "native_dry", new=self.saved[3]), mock.patch.object(
                            fixture, "COMPLETED", body,
                        ), mock.patch.object(jev, "fallback_candidates") as candidates:
                            self.assertTrue(jev.mark_native_dry("quota", time.time() + 3600))
                            before = len(Edge.payloads)
                            headers = {"x-openai-internal-codex-responses-lite": "true"} if lite else {}
                            request = payload_for([message("user", "Inspect")], model=slug)
                            if terminal is None:
                                with self.assertRaises(urllib.error.HTTPError) as error:
                                    self.call(request, headers)
                                self.assertEqual(error.exception.code, 502)
                                error.exception.close()
                                self.assertTrue(self.logged.wait(3))
                            else:
                                self.call(request, headers)
                            self.assertTrue(Path(jev.DRY_STATE_PATH).exists())
                            self.assertNotEqual(self.records[-1]["dry"], "cleared")
                            self.assertEqual(len(Edge.payloads), before + 1)
                            candidates.assert_not_called()


if __name__ == "__main__":
    unittest.main()
