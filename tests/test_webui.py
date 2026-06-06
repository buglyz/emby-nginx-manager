import unittest
from pathlib import Path

import webui


class DeployArgsTests(unittest.TestCase):
    def base_payload(self):
        return {
            "frontend": "emby.example.com",
            "backend": "127.0.0.1:8096",
        }

    def test_proxy_redirect_is_disabled_by_default(self):
        args = webui.deploy_args(self.base_payload())

        self.assertNotIn("--proxy-redirect", args)
        self.assertNotIn("--no-proxy-redirect", args)

    def test_proxy_redirect_must_be_enabled_explicitly(self):
        payload = self.base_payload()
        payload["enable_proxy_redirect"] = True

        self.assertIn("--proxy-redirect", webui.deploy_args(payload))

    def test_legacy_no_proxy_redirect_payload_is_accepted(self):
        payload = self.base_payload()
        payload["no_proxy_redirect"] = True

        self.assertIn("--no-proxy-redirect", webui.deploy_args(payload))

    def test_bad_frontend_host_is_rejected(self):
        payload = self.base_payload()
        payload["frontend"] = "emby.example.com;root=/"

        with self.assertRaises(webui.WebUIError):
            webui.deploy_args(payload)


class RestorePathTests(unittest.TestCase):
    def test_certificate_restore_paths_are_allowed(self):
        allowed = [
            "etc/nginx/certs/emby.example.com/cert",
            "etc/nginx/certs/emby.example.com/key",
            "etc/nginx/ssl/emby.example.com/fullchain.pem",
            "etc/nginx/ssl/emby.example.com/privkey.pem",
        ]

        for arcname in allowed:
            with self.subTest(arcname=arcname):
                self.assertTrue(webui.restore_allowed_path(arcname))

    def test_unrelated_restore_paths_are_rejected(self):
        rejected = [
            "/etc/nginx/certs/emby.example.com/key",
            "etc/nginx/certs/emby.example.com/../../shadow",
            "etc/shadow",
            "etc/nginx/ssl/emby.example.com/account.key",
        ]

        for arcname in rejected:
            with self.subTest(arcname=arcname):
                self.assertFalse(webui.restore_allowed_path(arcname))


class StaticSafetyTests(unittest.TestCase):
    def test_no_server_side_redirect_proxy_without_allowlist(self):
        root = Path(__file__).resolve().parents[1]
        deploy = (root / "deploy.sh").read_text(encoding="utf-8")

        self.assertNotIn("proxy_pass $saved_redirect_location", deploy)
        self.assertNotIn("proxy_intercept_errors on;", deploy)


if __name__ == "__main__":
    unittest.main()
