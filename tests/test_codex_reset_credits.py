import importlib.util
import sys
import types
from pathlib import Path
from unittest import TestCase


API_PATH = Path(__file__).parents[1] / "plugins" / "llm-usage" / "dashboard" / "plugin_api.py"


class _Router:
    def get(self, _path):
        return lambda fn: fn


if "fastapi" not in sys.modules:
    fastapi_stub = types.ModuleType("fastapi")
    setattr(fastapi_stub, "APIRouter", _Router)
    sys.modules["fastapi"] = fastapi_stub

spec = importlib.util.spec_from_file_location("llm_usage_plugin_api", API_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("could not load plugin API module")
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)


class CodexResetCreditsTests(TestCase):
    def test_parse_rate_limit_reset_credits(self):
        payload = {
            "rateLimitResetCredits": {
                "availableCount": 1,
                "credits": [
                    {
                        "id": "RateLimitResetCredit_test",
                        "resetType": "codexRateLimits",
                        "status": "available",
                        "grantedAt": 1783964426,
                        "expiresAt": 1786556426,
                        "title": "Full reset",
                        "description": "Thanks for using Codex!",
                    }
                ],
            }
        }
        capacity = api.parse_codex_reset_credits(payload)
        self.assertEqual(capacity["usage_resets"]["available_count"], 1)
        self.assertEqual(capacity["usage_resets"]["nearest_expires_at"], 1786556426.0)
        self.assertEqual(capacity["usage_resets"]["items"][0]["title"], "Full reset")
        self.assertEqual(capacity["usage_resets"]["items"][0]["status"], "available")

    def test_parse_missing_reset_credits_is_none(self):
        self.assertIsNone(api.parse_codex_reset_credits({"rateLimits": {}}))
        self.assertIsNone(api.parse_codex_reset_credits({"rateLimitResetCredits": {"availableCount": 0, "credits": []}}))
