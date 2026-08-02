import importlib.util
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch


API_PATH = Path(__file__).parents[1] / "plugins" / "llm-usage" / "dashboard" / "plugin_api.py"
class _Router:
    def get(self, _path):
        return lambda fn: fn


# The standalone plugin tests only need route decoration; avoid importing the
# dashboard's optional FastAPI/Pydantic stack just to exercise provider mapping.
if "fastapi" not in sys.modules:
    fastapi_stub = types.ModuleType("fastapi")
    setattr(fastapi_stub, "APIRouter", _Router)
    sys.modules["fastapi"] = fastapi_stub
spec = importlib.util.spec_from_file_location("llm_usage_plugin_api", API_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("could not load plugin API module")
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)


class NousProviderTests(TestCase):
    def test_iso_renewal_is_converted_to_epoch(self):
        expected = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc).timestamp()
        self.assertEqual(api._parse_iso_epoch("2026-08-31T12:00:00Z"), expected)

    def test_nous_usage_maps_plan_and_topup_bars(self):
        class Bar:
            pct_used = 25
            remaining_usd = 15.0
            total_usd = 20.0

        model = types.SimpleNamespace(
            available=True,
            plan_bar=Bar(),
            topup_bar=types.SimpleNamespace(remaining_usd=4.5),
            plan_name="Plus",
            renews_at="2026-08-31T12:00:00Z",
            renews_display="Aug 31, 2026",
            status="healthy",
            subscription_remaining_usd=15.0,
            topup_remaining_usd=4.5,
            total_spendable_usd=19.5,
        )
        billing_usage = types.ModuleType("agent.billing_usage")
        setattr(billing_usage, "build_usage_model", lambda timeout=15.0: model)
        with patch.dict(sys.modules, {"agent.billing_usage": billing_usage}):
            windows, error, capacity = api.fetch_nous_portal_usage()

        self.assertIsNone(error)
        self.assertEqual([w["id"] for w in windows], ["monthly_plan", "topup_balance"])
        self.assertEqual(windows[0]["used_pct"], 25.0)
        self.assertEqual(windows[0]["detail"], "$15.00 of $20.00 left")
        self.assertEqual(capacity["plan_name"], "Plus")

    def test_current_cache_requires_nous_provider(self):
        payload = {"providers": [{"id": provider} for provider in ("anthropic", "grok", "codex", "venice")]}
        self.assertFalse(api._providers_look_complete(payload))
        payload["providers"].append({"id": "nous"})
        self.assertTrue(api._providers_look_complete(payload))