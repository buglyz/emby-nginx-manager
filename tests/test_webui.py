import io
import sys
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

    def test_custom_nginx_conf_dir_restore_path_is_allowed(self):
        original = webui.os.environ.get("NGINX_CONF_DIR")
        try:
            webui.os.environ["NGINX_CONF_DIR"] = "/opt/nginx/sites-enabled"
            self.assertTrue(webui.restore_allowed_path("opt/nginx/sites-enabled/emby.example.com.conf"))
            self.assertFalse(webui.restore_allowed_path("opt/nginx/other/emby.example.com.conf"))
        finally:
            if original is None:
                webui.os.environ.pop("NGINX_CONF_DIR", None)
            else:
                webui.os.environ["NGINX_CONF_DIR"] = original

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

    def test_weak_webui_service_restore_content_is_rejected(self):
        member = self.member("etc/systemd/system/emby-nginx-webui.service")
        data = b"Description=Emby Nginx Manager WebUI\nExecStart=/usr/bin/python3 webui.py\n"

        with self.assertRaises(webui.WebUIError):
            webui.validate_restore_member(member, data)

    def test_webui_service_restore_requires_wrapper_script_argument(self):
        member = self.member("etc/systemd/system/emby-nginx-webui.service")
        data = (
            b"Description=Emby Nginx Manager WebUI\n"
            b"Environment=EMBY_WEBUI_SHOW_KEY_URL=0\n"
            b"ExecStart=/usr/bin/python3 /opt/emby-nginx-manager/webui.py --host 127.0.0.1\n"
            b"NoNewPrivileges=true\n"
            b"PrivateTmp=true\n"
        )

        with self.assertRaises(webui.WebUIError):
            webui.validate_restore_member(member, data)

    def test_hardened_webui_service_restore_content_is_allowed(self):
        member = self.member("etc/systemd/system/emby-nginx-webui.service")
        data = (
            b"Description=Emby Nginx Manager WebUI\n"
            b"Environment=EMBY_WEBUI_SHOW_KEY_URL=0\n"
            b"ExecStart=/usr/bin/python3 /opt/emby-nginx-manager/webui.py "
            b"--script /opt/emby-nginx-manager/deploy.sh\n"
            b"NoNewPrivileges=true\n"
            b"PrivateTmp=true\n"
        )

        webui.validate_restore_member(member, data)

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

    def test_restore_writes_custom_nginx_conf_dir_members(self):
        original_env = webui.os.environ.get("NGINX_CONF_DIR")
        original_run = webui.run_system_command
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conf_dir = root / "sites-enabled"
            conf = conf_dir / "emby.example.com.conf"
            arcname = str(conf).lstrip("/")
            backup_dir, name = self.make_archive(
                {
                    arcname: "# nre_emby_managed=true\nserver { listen 443 ssl; }\n",
                }
            )

            try:
                webui.os.environ["NGINX_CONF_DIR"] = str(conf_dir)
                webui.run_system_command = lambda *args, **kwargs: {"ok": True, "output": ""}
                result = webui.restore_backup_archive(backup_dir, name)
            finally:
                webui.run_system_command = original_run
                if original_env is None:
                    webui.os.environ.pop("NGINX_CONF_DIR", None)
                else:
                    webui.os.environ["NGINX_CONF_DIR"] = original_env

            self.assertTrue(result["ok"])
            self.assertEqual(conf.read_text(encoding="utf-8"), "# nre_emby_managed=true\nserver { listen 443 ssl; }\n")

    def test_restore_rejects_symlink_targets(self):
        original_env = webui.os.environ.get("NGINX_CONF_DIR")
        original_run = webui.run_system_command
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conf_dir = root / "sites-enabled"
            conf_dir.mkdir()
            outside = root / "outside.conf"
            conf = conf_dir / "emby.example.com.conf"
            outside.write_text("original\n", encoding="utf-8")
            conf.symlink_to(outside)
            arcname = str(conf).lstrip("/")
            backup_dir, name = self.make_archive(
                {
                    arcname: "# nre_emby_managed=true\nserver { listen 443 ssl; }\n",
                }
            )

            try:
                webui.os.environ["NGINX_CONF_DIR"] = str(conf_dir)
                webui.run_system_command = lambda *args, **kwargs: {"ok": True, "output": ""}
                with self.assertRaises(webui.WebUIError):
                    webui.restore_backup_archive(backup_dir, name)
            finally:
                webui.run_system_command = original_run
                if original_env is None:
                    webui.os.environ.pop("NGINX_CONF_DIR", None)
                else:
                    webui.os.environ["NGINX_CONF_DIR"] = original_env

            self.assertTrue(conf.is_symlink())
            self.assertEqual(outside.read_text(encoding="utf-8"), "original\n")

    def test_restore_rolls_back_after_mid_restore_failure(self):
        original_env = webui.os.environ.get("NGINX_CONF_DIR")
        original_run = webui.run_system_command
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conf_dir = root / "sites-enabled"
            conf_dir.mkdir()
            first = conf_dir / "aaa.example.com.conf"
            second = conf_dir / "zzz.example.com.conf"
            outside = root / "outside.conf"
            first.write_text("original\n", encoding="utf-8")
            outside.write_text("outside\n", encoding="utf-8")
            second.symlink_to(outside)
            backup_dir, name = self.make_archive(
                {
                    str(first).lstrip("/"): "# nre_emby_managed=true\nserver { listen 443 ssl; }\n",
                    str(second).lstrip("/"): "# nre_emby_managed=true\nserver { listen 443 ssl; }\n",
                }
            )

            try:
                webui.os.environ["NGINX_CONF_DIR"] = str(conf_dir)
                webui.run_system_command = lambda *args, **kwargs: {"ok": True, "output": ""}
                with self.assertRaises(webui.WebUIError):
                    webui.restore_backup_archive(backup_dir, name)
            finally:
                webui.run_system_command = original_run
                if original_env is None:
                    webui.os.environ.pop("NGINX_CONF_DIR", None)
                else:
                    webui.os.environ["NGINX_CONF_DIR"] = original_env

            self.assertEqual(first.read_text(encoding="utf-8"), "original\n")
            self.assertEqual(outside.read_text(encoding="utf-8"), "outside\n")

    def test_restore_rejects_symlink_parent_directories(self):
        original_env = webui.os.environ.get("NGINX_CONF_DIR")
        original_run = webui.run_system_command
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root / "outside"
            outside.mkdir()
            conf_dir = root / "sites-enabled"
            conf_dir.symlink_to(outside, target_is_directory=True)
            conf = conf_dir / "emby.example.com.conf"
            arcname = str(conf).lstrip("/")
            backup_dir, name = self.make_archive(
                {
                    arcname: "# nre_emby_managed=true\nserver { listen 443 ssl; }\n",
                }
            )

            try:
                webui.os.environ["NGINX_CONF_DIR"] = str(conf_dir)
                webui.run_system_command = lambda *args, **kwargs: {"ok": True, "output": ""}
                with self.assertRaises(webui.WebUIError):
                    webui.restore_backup_archive(backup_dir, name)
            finally:
                webui.run_system_command = original_run
                if original_env is None:
                    webui.os.environ.pop("NGINX_CONF_DIR", None)
                else:
                    webui.os.environ["NGINX_CONF_DIR"] = original_env

            self.assertFalse((outside / "emby.example.com.conf").exists())


class BackupArchiveTests(unittest.TestCase):
    def test_collect_backup_files_uses_configured_nginx_conf_dir(self):
        original = webui.os.environ.get("NGINX_CONF_DIR")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conf_dir = root / "sites-enabled"
            conf_dir.mkdir()
            managed = conf_dir / "emby.example.com.conf"
            unmanaged = conf_dir / "other.example.com.conf"
            managed.write_text("# nre_emby_managed=true\nserver {}\n", encoding="utf-8")
            unmanaged.write_text("server {}\n", encoding="utf-8")

            try:
                webui.os.environ["NGINX_CONF_DIR"] = str(conf_dir)
                files = webui.collect_backup_files()
            finally:
                if original is None:
                    webui.os.environ.pop("NGINX_CONF_DIR", None)
                else:
                    webui.os.environ["NGINX_CONF_DIR"] = original

        self.assertIn(managed, files)
        self.assertNotIn(unmanaged, files)

    def test_collect_backup_files_skips_symlinked_configs(self):
        original = webui.os.environ.get("NGINX_CONF_DIR")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conf_dir = root / "sites-enabled"
            conf_dir.mkdir()
            target = root / "target.conf"
            symlink = conf_dir / "emby.example.com.conf"
            target.write_text("# nre_emby_managed=true\nserver {}\n", encoding="utf-8")
            symlink.symlink_to(target)

            try:
                webui.os.environ["NGINX_CONF_DIR"] = str(conf_dir)
                files = webui.collect_backup_files()
            finally:
                if original is None:
                    webui.os.environ.pop("NGINX_CONF_DIR", None)
                else:
                    webui.os.environ["NGINX_CONF_DIR"] = original

        self.assertNotIn(symlink, files)

    def test_add_backup_file_skips_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "target.conf"
            symlink = root / "link.conf"
            archive = root / "backup.tar"
            target.write_text("# nre_emby_managed=true\nserver {}\n", encoding="utf-8")
            symlink.symlink_to(target)

            with tarfile.open(archive, "w") as tar:
                webui.add_backup_file(tar, symlink)
            with tarfile.open(archive, "r") as tar:
                self.assertEqual(tar.getmembers(), [])

    def test_backup_archive_scrubs_owner_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conf = root / "emby.example.com-443.conf"
            conf.write_text("# nre_emby_managed=true\nserver {}\n", encoding="utf-8")
            backup_dir = root / "backups"

            original_collect = webui.collect_backup_files
            webui.collect_backup_files = lambda: [conf]
            try:
                result = webui.create_backup_archive(backup_dir)
            finally:
                webui.collect_backup_files = original_collect

            with tarfile.open(result["path"], "r:gz") as tar:
                for member in tar.getmembers():
                    with self.subTest(member=member.name):
                        self.assertEqual(member.uid, 0)
                        self.assertEqual(member.gid, 0)
                        self.assertEqual(member.uname, "")
                        self.assertEqual(member.gname, "")

    def test_backup_archive_names_do_not_collide_with_same_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conf = root / "emby.example.com-443.conf"
            conf.write_text("# nre_emby_managed=true\nserver {}\n", encoding="utf-8")
            backup_dir = root / "backups"

            original_collect = webui.collect_backup_files
            original_time_ns = webui.time.time_ns
            webui.collect_backup_files = lambda: [conf]
            webui.time.time_ns = lambda: 1760000000123456789
            try:
                first = webui.create_backup_archive(backup_dir)
                second = webui.create_backup_archive(backup_dir)
            finally:
                webui.collect_backup_files = original_collect
                webui.time.time_ns = original_time_ns

            self.assertNotEqual(first["name"], second["name"])
            self.assertTrue(Path(first["path"]).is_file())
            self.assertTrue(Path(second["path"]).is_file())
            self.assertRegex(first["name"], webui.BACKUP_NAME_RE)
            self.assertRegex(second["name"], webui.BACKUP_NAME_RE)


class ConfigParsingTests(unittest.TestCase):
    def test_env_int_falls_back_for_invalid_values(self):
        original = webui.os.environ.get("TEST_WEBUI_INT")
        try:
            webui.os.environ["TEST_WEBUI_INT"] = "not-a-number"
            self.assertEqual(webui.env_int("TEST_WEBUI_INT", 20, minimum=1), 20)
            webui.os.environ["TEST_WEBUI_INT"] = "0"
            self.assertEqual(webui.env_int("TEST_WEBUI_INT", 20, minimum=1), 20)
            webui.os.environ["TEST_WEBUI_INT"] = "7"
            self.assertEqual(webui.env_int("TEST_WEBUI_INT", 20, minimum=1), 7)
        finally:
            if original is None:
                webui.os.environ.pop("TEST_WEBUI_INT", None)
            else:
                webui.os.environ["TEST_WEBUI_INT"] = original

    def test_parse_args_uses_safe_default_port_env(self):
        original_env = webui.os.environ.get("EMBY_WEBUI_PORT")
        original_argv = sys.argv[:]
        try:
            webui.os.environ["EMBY_WEBUI_PORT"] = "invalid"
            sys.argv = ["webui.py"]
            self.assertEqual(webui.parse_args().port, 8765)
        finally:
            sys.argv = original_argv
            if original_env is None:
                webui.os.environ.pop("EMBY_WEBUI_PORT", None)
            else:
                webui.os.environ["EMBY_WEBUI_PORT"] = original_env


class RequestSafetyTests(unittest.TestCase):
    class DummyHandler:
        def __init__(self, headers, access_key="secret", body=b""):
            self.headers = headers
            self.rfile = io.BytesIO(body)
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

    def test_negative_content_length_is_rejected(self):
        handler = self.DummyHandler({"Content-Length": "-1"}, body=b'{"ok": true}')

        with self.assertRaises(webui.WebUIError):
            webui.Handler.read_json_body(handler)


class RedactionTests(unittest.TestCase):
    def test_sensitive_values_are_redacted(self):
        text = (
            "GET /?key=abc&token=def "
            "X-Emby-Webui-Key: secret "
            "EMBY_WEBUI_KEY=hidden "
            '{"password":"pw","nested_token":"tok"}'
        )

        redacted = webui.redact_sensitive_text(text)

        self.assertNotIn("abc", redacted)
        self.assertNotIn("def", redacted)
        self.assertNotIn("secret", redacted)
        self.assertNotIn("hidden", redacted)
        self.assertNotIn("pw", redacted)
        self.assertNotIn(':"tok"', redacted)
        self.assertGreaterEqual(redacted.count("<redacted>"), 6)

    def test_history_entry_redacts_target_and_command(self):
        entry = webui.history_entry(
            "preview",
            {
                "ok": False,
                "exit_code": 400,
                "duration_ms": 0,
                "command": "deploy --token abc --password=secret",
                "output": "failed",
            },
            {
                "frontend": "https://emby.example.com/path?token=abc",
                "backend": "http://127.0.0.1:8096/?password=secret",
            },
        )

        self.assertNotIn("abc", entry["target"])
        self.assertNotIn("secret", entry["target"])
        self.assertNotIn("abc", entry["command"])
        self.assertNotIn("secret", entry["command"])
        self.assertIn("<redacted>", entry["target"])
        self.assertIn("<redacted>", entry["command"])


class StaticSafetyTests(unittest.TestCase):
    def test_webui_does_not_reprint_result_after_refresh(self):
        self.assertNotIn("printOutput(result);\n        await refreshList(false);\n        await refreshHistory(false);\n        printOutput(result);", webui.HTML)

    def test_acme_installer_uses_tempfile(self):
        root = Path(__file__).resolve().parents[1]
        deploy = (root / "deploy.sh").read_text(encoding="utf-8")

        self.assertNotIn('TMP_INSTALL_SCRIPT="./acme.sh"', deploy)
        self.assertNotIn("trap \"rm -f '$TMP_INSTALL_SCRIPT'\" RETURN", deploy)
        self.assertIn("TMP_INSTALL_SCRIPT=$(mktemp)", deploy)

    def test_webui_service_unit_has_sandbox_flags(self):
        root = Path(__file__).resolve().parents[1]
        wrapper = (root / "bin" / "emby").read_text(encoding="utf-8")

        for flag in (
            "PrivateDevices=true",
            "ProtectClock=true",
            "ProtectHostname=true",
            "RemoveIPC=true",
            "RestrictNamespaces=true",
        ):
            with self.subTest(flag=flag):
                self.assertIn(flag, wrapper)

    def test_no_server_side_redirect_proxy_without_allowlist(self):
        root = Path(__file__).resolve().parents[1]
        deploy = (root / "deploy.sh").read_text(encoding="utf-8")

        self.assertNotIn("proxy_pass $saved_redirect_location", deploy)
        self.assertNotIn("proxy_intercept_errors on;", deploy)

    def test_remove_uses_configured_nginx_conf_dir_for_cert_refs(self):
        root = Path(__file__).resolve().parents[1]
        deploy = (root / "deploy.sh").read_text(encoding="utf-8")

        self.assertNotIn('grep -Rsl -F "$cert_full_path" /etc/nginx/conf.d', deploy)
        self.assertIn('conf_dir=$(get_nginx_conf_dir)', deploy)

    def test_remove_uses_actual_allowed_certificate_directory(self):
        root = Path(__file__).resolve().parents[1]
        deploy = (root / "deploy.sh").read_text(encoding="utf-8")

        self.assertIn("cert_cleanup_dir_from_path()", deploy)
        self.assertIn('/etc/nginx/ssl/*/fullchain.pem', deploy)
        self.assertIn('cert_dir="$cert_parent_dir"', deploy)
        self.assertNotIn('cert_dir="/etc/nginx/certs/$remove_cert_domain"', deploy)

    def test_remove_skips_symlink_certificate_dirs(self):
        root = Path(__file__).resolve().parents[1]
        deploy = (root / "deploy.sh").read_text(encoding="utf-8")

        self.assertIn('$SUDO [ -L "$cert_dir" ]', deploy)
        self.assertIn("证书目录是符号链接，将跳过自动删除", deploy)
        self.assertIn("cert_cleanup_note=", deploy)

    def test_deploy_doctor_uses_general_log_redaction(self):
        root = Path(__file__).resolve().parents[1]
        deploy = (root / "deploy.sh").read_text(encoding="utf-8")

        self.assertIn("redact_sensitive_stream()", deploy)
        self.assertIn("token|password|secret|access_key", deploy)
        self.assertIn("printf '%s\\n' \"$recent_errors\" | redact_sensitive_stream", deploy)

    def test_deploy_validates_lock_dir_before_rm_rf(self):
        root = Path(__file__).resolve().parents[1]
        deploy = (root / "deploy.sh").read_text(encoding="utf-8")

        self.assertIn("validate_lock_dir()", deploy)
        self.assertIn('"/"|""|*..*|*[[:space:]]*', deploy)
        self.assertIn("validate_lock_dir\n\n    $SUDO mkdir", deploy)

    def test_deploy_rejects_symlink_config_paths(self):
        root = Path(__file__).resolve().parents[1]
        deploy = (root / "deploy.sh").read_text(encoding="utf-8")

        self.assertIn('conf_path_is_regular_file()', deploy)
        self.assertIn('$SUDO [ -f "$file" ] && ! $SUDO [ -L "$file" ]', deploy)
        self.assertIn('拒绝写入非普通 Nginx 配置文件', deploy)
        self.assertIn('拒绝备份符号链接配置文件', deploy)

    def test_webui_proxy_honors_configured_nginx_conf_dir(self):
        root = Path(__file__).resolve().parents[1]
        wrapper = (root / "bin" / "emby").read_text(encoding="utf-8")

        self.assertIn('NGINX_CONF_DIR="${NGINX_CONF_DIR:-/etc/nginx/conf.d}"', wrapper)
        self.assertIn('conf_file="$NGINX_CONF_DIR/$proxy_domain-443.conf"', wrapper)
        self.assertNotIn('conf_file="/etc/nginx/conf.d/$proxy_domain-443.conf"', wrapper)

    def test_webui_proxy_password_prompt_restores_tty_state(self):
        root = Path(__file__).resolve().parents[1]
        wrapper = (root / "bin" / "emby").read_text(encoding="utf-8")

        self.assertIn("saved_tty=$(stty -g)", wrapper)
        self.assertIn('stty "$saved_tty"', wrapper)
        self.assertNotIn("stty echo", wrapper)

    def test_wrapper_tracks_temp_files_without_command_substitution(self):
        root = Path(__file__).resolve().parents[1]
        wrapper = (root / "bin" / "emby").read_text(encoding="utf-8")

        self.assertIn("cleanup_tmp_files()", wrapper)
        self.assertIn("trap cleanup_tmp_files EXIT", wrapper)
        self.assertIn("trap 'cleanup_tmp_files; exit 130' INT", wrapper)
        self.assertIn("make_tmp_file tmp_htpasswd", wrapper)
        self.assertNotIn("=$(make_tmp_file)", wrapper)

    def test_webui_uses_unique_temp_files_for_state_writes(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "webui.py").read_text(encoding="utf-8")

        self.assertIn("tempfile.NamedTemporaryFile", source)
        self.assertNotIn('history_file.with_suffix(".tmp")', source)
        self.assertNotIn('backup_dir / f".{name}.tmp"', source)


if __name__ == "__main__":
    unittest.main()
