import importlib.util
import sys
import types
from pathlib import Path
from unittest import TestCase


API_PATH = Path(__file__).parents[1] / "plugins" / "llm-usage" / "dashboard" / "plugin_api.py"


class _Router:
    def get(self, _path):
        return lambda fn: fn


# The standalone plugin tests only need route decoration; avoid importing the
# dashboard's optional FastAPI/Pydantic stack just to exercise the classifier.
if "fastapi" not in sys.modules:
    fastapi_stub = types.ModuleType("fastapi")
    setattr(fastapi_stub, "APIRouter", _Router)
    sys.modules["fastapi"] = fastapi_stub
spec = importlib.util.spec_from_file_location("llm_usage_plugin_api", API_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("could not load plugin API module")
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)


class AvailabilityTests(TestCase):
    def test_verified_when_windows_exist(self):
        self.assertEqual(api._availability("ok", None), "verified")
        self.assertEqual(api._availability("ok", "some non-fatal warning"), "verified")

    def test_auth_error_on_recognized_credential_failures(self):
        for error in (
            "Nous Portal is not logged in or account usage is unavailable",
            "Venice rejected this key. Billing needs an Admin key, not an inference key.",
            "Add a Venice Admin key to ~/.hermes/.env as VENICE_API_KEY",
            "could not start Claude usage session: not signed in",
            "Venice billing failed (HTTP 401): invalid token",
        ):
            self.assertEqual(
                api._availability("error", error),
                "auth_error",
                f"expected auth_error for {error!r}",
            )

    def test_ambiguous_errors_stay_unknown(self):
        for error in (
            "claude CLI not found on PATH",
            "parsed zero windows from Claude /usage (CLI UI may have changed)",
            "could not request Grok /usage",
            "Codex returned no rate-limit windows",
            "Venice billing is unreachable",
        ):
            self.assertEqual(
                api._availability("error", error),
                "unknown",
                f"expected unknown for {error!r}",
            )

    def test_exhausted_is_distinct_from_auth(self):
        self.assertEqual(api._availability("exhausted", None), "exhausted")

    def test_unknown_when_nothing_verified(self):
        self.assertEqual(api._availability("unknown", None), "unknown")

    def test_provider_payload_carries_availability_and_checked_at(self):
        provider = api._provider(
            id_="anthropic",
            name="Claude Code",
            source="Claude Code CLI /usage",
            windows=[{"label": "Session", "used_pct": 12.0}],
            error=None,
        )
        self.assertEqual(provider["availability"], "verified")
        self.assertEqual(provider["status"], "ok")
        self.assertTrue(provider["checked_at"])
        self.assertEqual(provider["confidence"], "actual")

        failing = api._provider(
            id_="nous",
            name="Nous Research",
            source="Hermes Portal account API",
            windows=[],
            error="Nous Portal is not logged in or account usage is unavailable",
        )
        self.assertEqual(failing["availability"], "auth_error")
        self.assertEqual(failing["status"], "error")
        self.assertEqual(failing["confidence"], "unavailable")
        self.assertTrue(failing["checked_at"])

    def test_nous_exhausted_keeps_orange_while_topup_remains(self):
        provider = api._provider(
            id_="nous",
            name="Nous Research",
            source="Hermes Portal account API",
            windows=[{"label": "Monthly Plus", "used_pct": 100.0}],
            error=None,
            capacity={"topup_remaining_usd": 16.84},
        )
        self.assertEqual(provider["availability"], "exhausted")
        self.assertEqual(api._nous_availability(provider)["availability"], "exhausted")

    def test_nous_exhausted_turns_red_when_topup_is_gone(self):
        provider = api._provider(
            id_="nous",
            name="Nous Research",
            source="Hermes Portal account API",
            windows=[{"label": "Monthly Plus", "used_pct": 100.0}],
            error=None,
            capacity={"topup_remaining_usd": 0.0},
        )
        self.assertEqual(api._nous_availability(provider)["availability"], "depleted")

        no_topup = api._provider(
            id_="nous",
            name="Nous Research",
            source="Hermes Portal account API",
            windows=[{"label": "Monthly Plus", "used_pct": 100.0}],
            error=None,
            capacity={"topup_remaining_usd": None},
        )
        # No top-up reported: raw exhausted signal stays (orange, not red).
        self.assertEqual(api._nous_availability(no_topup)["availability"], "exhausted")

    def test_nous_refinement_leaves_other_providers_alone(self):
        provider = api._provider(
            id_="anthropic",
            name="Claude Code",
            source="Claude Code CLI /usage",
            windows=[{"label": "Session", "used_pct": 100.0}],
            error=None,
            capacity={"topup_remaining_usd": 0.0},
        )
        self.assertEqual(api._nous_availability(provider)["availability"], "exhausted")


if __name__ == "__main__":
    import unittest

    unittest.main()
