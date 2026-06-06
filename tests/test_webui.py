import io
import tarfile
import tempfile
import unittest
from types import SimpleNamespace
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
    def make_archive(self, files):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        backup_dir = Path(tmp.name)
        name = "emby-nginx-manager-20260102030405.tar.gz"
        archive = backup_dir / name
        with tarfile.open(archive, "w:gz") as tar:
            for arcname, data in files.items():
                payload = data.encode("utf-8") if isinstance(data, str) else data
                info = tarfile.TarInfo(arcname)
                info.size = len(payload)
                tar.addfile(info, io.BytesIO(payload))
        return backup_dir, name

    def member(self, name, size=1):
        return SimpleNamespace(
            name=name,
            size=size,
            isdir=lambda: False,
            isfile=lambda: True,
        )

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

    def test_restore_modes_are_forced_by_path(self):
        cases = {
            "etc/nginx/certs/emby.example.com/key": 0o600,
            "etc/nginx/certs/emby.example.com/cert": 0o644,
            "etc/nginx/ssl/emby.example.com/privkey.pem": 0o600,
            "etc/nginx/ssl/emby.example.com/fullchain.pem": 0o644,
            "etc/nginx/conf.d/emby.example.com-443.conf": 0o640,
            "etc/systemd/system/emby-nginx-webui.service": 0o644,
            "etc/nginx/.htpasswd-emby-webui": 0o640,
        }

        for arcname, mode in cases.items():
            with self.subTest(arcname=arcname):
                self.assertEqual(webui.restore_mode_for_arcname(arcname), mode)

    def test_managed_nginx_config_restore_content_is_allowed(self):
        member = self.member("etc/nginx/conf.d/emby.example.com-443.conf")
        data = b"# nre_emby_managed=true\nserver { listen 443 ssl; }\n"

        webui.validate_restore_member(member, data)

    def test_unmanaged_nginx_config_restore_content_is_rejected(self):
        member = self.member("etc/nginx/conf.d/evil.example.com.conf")
        data = b"server { listen 80; server_name evil.example.com; }\n"

        with self.assertRaises(webui.WebUIError):
            webui.validate_restore_member(member, data)

    def test_oversized_restore_member_is_rejected(self):
        member = self.member(
            "etc/nginx/conf.d/emby.example.com-443.conf",
            size=webui.RESTORE_MAX_MEMBER_BYTES + 1,
        )

        with self.assertRaises(webui.WebUIError):
            webui.validate_restore_member(member)

    def test_certificate_restore_requires_managed_config_reference(self):
        backup_dir, name = self.make_archive(
            {
                "etc/nginx/certs/other.example.com/key": b"secret",
            }
        )

        with self.assertRaises(webui.WebUIError):
            webui.preview_backup_archive(backup_dir, name)

    def test_certificate_restore_allows_managed_config_reference(self):
        backup_dir, name = self.make_archive(
            {
                "etc/nginx/conf.d/emby.example.com-443.conf": (
                    "# nre_emby_managed=true\n"
                    "server {\n"
                    "  ssl_certificate /etc/nginx/certs/emby.example.com/cert;\n"
                    "  ssl_certificate_key /etc/nginx/certs/emby.example.com/key;\n"
                    "}\n"
                ),
                "etc/nginx/certs/emby.example.com/cert": b"cert",
                "etc/nginx/certs/emby.example.com/key": b"key",
            }
        )

        result = webui.preview_backup_archive(backup_dir, name)

        self.assertTrue(result["ok"])
        self.assertEqual(len(result["files"]), 3)


class RequestSafetyTests(unittest.TestCase):
    class DummyHandler:
        def __init__(self, headers, access_key="secret"):
            self.headers = headers
            self.server = type("Server", (), {"access_key": access_key})()

    def same_origin(self, headers, access_key="secret"):
        handler = self.DummyHandler(headers, access_key=access_key)
        return webui.Handler.same_origin_request(handler)

    def test_missing_origin_requires_frontend_header(self):
        self.assertFalse(self.same_origin({"Host": "127.0.0.1:8765"}))
        self.assertTrue(
            self.same_origin({"Host": "127.0.0.1:8765", "X-Requested-With": "EmbyNginxManager"})
        )

    def test_internal_key_header_is_allowed(self):
        self.assertTrue(self.same_origin({"Host": "web.example.com", "X-Emby-Webui-Key": "secret"}))

    def test_cross_origin_is_rejected(self):
        self.assertFalse(
            self.same_origin({"Host": "web.example.com", "Origin": "https://evil.example.com"})
        )
        self.assertFalse(
            self.same_origin(
                {
                    "Host": "web.example.com",
                    "Origin": "https://evil.example.com",
                    "X-Emby-Webui-Key": "secret",
                }
            )
        )
        self.assertFalse(
            self.same_origin(
                {
                    "Host": "web.example.com",
                    "Sec-Fetch-Site": "cross-site",
                    "X-Requested-With": "EmbyNginxManager",
                }
            )
        )
        self.assertTrue(
            self.same_origin({"Host": "web.example.com", "Origin": "https://web.example.com"})
        )

    def test_forwarded_origin_is_accepted_behind_reverse_proxy(self):
        self.assertTrue(
            self.same_origin(
                {
                    "Host": "127.0.0.1:8765",
                    "Origin": "https://web.example.com",
                    "X-Forwarded-Host": "web.example.com",
                    "X-Forwarded-Proto": "https",
                }
            )
        )

    def test_forwarded_origin_scheme_must_match(self):
        self.assertFalse(
            self.same_origin(
                {
                    "Host": "127.0.0.1:8765",
                    "Origin": "http://web.example.com",
                    "X-Forwarded-Host": "web.example.com",
                    "X-Forwarded-Proto": "https",
                }
            )
        )

    def test_access_cookie_is_secure_when_forwarded_https(self):
        handler = self.DummyHandler({"X-Forwarded-Proto": "https"}, access_key="secret")
        cookie = webui.Handler.access_cookie_header(handler)

        self.assertIn("Secure", cookie)
        self.assertIn("HttpOnly", cookie)


class StaticSafetyTests(unittest.TestCase):
    def test_no_server_side_redirect_proxy_without_allowlist(self):
        root = Path(__file__).resolve().parents[1]
        deploy = (root / "deploy.sh").read_text(encoding="utf-8")

        self.assertNotIn("proxy_pass $saved_redirect_location", deploy)
        self.assertNotIn("proxy_intercept_errors on;", deploy)


if __name__ == "__main__":
    unittest.main()
