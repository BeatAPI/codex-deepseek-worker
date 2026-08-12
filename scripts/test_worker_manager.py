#!/usr/bin/env python3

from __future__ import annotations

import copy
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "codex-deepseek-worker"
    / "scripts"
    / "deepseek_worker.py"
)
spec = importlib.util.spec_from_file_location("deepseek_worker", SCRIPT)
manager = importlib.util.module_from_spec(spec)
assert spec.loader
sys.modules[spec.name] = manager
spec.loader.exec_module(manager)


class ManagerTests(unittest.TestCase):
    def test_cli_status_runs_on_python_3_9_and_newer(self) -> None:
        if sys.version_info < (3, 9):
            self.skipTest("Python 3.9 is the oldest supported bootstrap runtime")
        with tempfile.TemporaryDirectory() as directory:
            codex_home = Path(directory)
            (codex_home / "config.toml").write_text('model = "gpt-test"\n')
            proc = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    str(SCRIPT),
                    "status",
                    "--codex-home",
                    str(codex_home),
                    "--codex-bin",
                    sys.executable,
                    "--json",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            payload = json.loads(proc.stdout)
        self.assertNotEqual(payload["status"], "unsupported_python")
        self.assertTrue(payload["checks"]["config_valid"])

    def test_managed_block_is_idempotent(self) -> None:
        original = 'model = "gpt-5.6-sol"\n\n[features]\nmulti_agent = true\n'
        with tempfile.TemporaryDirectory() as directory:
            paths = manager.resolve_paths(directory)
            first = original.rstrip() + "\n" + manager.managed_provider_block()
            second = manager.remove_managed_blocks(first).rstrip() + "\n" + manager.managed_provider_block()
            self.assertEqual(first, second)
            manager.parse_toml_text(second)

    def test_top_level_catalog_stays_before_tables(self) -> None:
        source = '[features]\nmulti_agent = true\n'
        updated = manager.set_top_level_key(source, "model_catalog_json", "/tmp/models.json")
        parsed = manager.parse_toml_text(updated)
        self.assertEqual(parsed["model_catalog_json"], "/tmp/models.json")
        self.assertEqual(parsed["features"]["multi_agent"], True)

    def test_top_level_key_escapes_windows_paths(self) -> None:
        source = '[features]\nmulti_agent = true\n'
        windows_path = r"C:\Users\oil\.codex\models-with-deepseek.json"
        updated = manager.set_top_level_key(source, "model_catalog_json", windows_path)
        self.assertEqual(
            manager.parse_toml_text(updated)["model_catalog_json"],
            windows_path,
        )
        self.assertEqual(manager.top_level_key(updated, "model_catalog_json"), windows_path)
        removed = manager.remove_top_level_key_if_value(
            updated,
            "model_catalog_json",
            windows_path,
        )
        self.assertNotIn("model_catalog_json", manager.parse_toml_text(removed))

    def test_desktop_multi_agent_v2_can_be_disabled_and_removed(self) -> None:
        source = '[features]\nmulti_agent = true\nmulti_agent_v2 = true\n'
        updated = manager.set_table_bool(source, "features", "multi_agent_v2", False)
        self.assertFalse(manager.parse_toml_text(updated)["features"]["multi_agent_v2"])
        removed = manager.remove_table_bool_if_value(
            updated,
            "features",
            "multi_agent_v2",
            False,
        )
        self.assertNotIn("multi_agent_v2", manager.parse_toml_text(removed)["features"])

    def test_quoted_features_table_is_updated_without_duplication(self) -> None:
        source = '["features"]\nmulti_agent = true\nmulti_agent_v2 = true\n'
        updated = manager.set_table_bool(source, "features", "multi_agent_v2", False)
        self.assertFalse(manager.parse_toml_text(updated)["features"]["multi_agent_v2"])
        self.assertEqual(updated.count('["features"]'), 1)
        self.assertNotIn("[features]", updated)
        restored = manager.set_table_bool(updated, "features", "multi_agent_v2", True)
        self.assertTrue(manager.parse_toml_text(restored)["features"]["multi_agent_v2"])

    def test_version_text_is_diagnostic_not_semver_gate(self) -> None:
        proc = SimpleNamespace(returncode=0, stdout="desktop-codex nightly\n", stderr="")
        with mock.patch.object(manager.subprocess, "run", return_value=proc):
            self.assertEqual(manager.codex_version_text("desktop-codex"), "desktop-codex nightly")

    def test_merged_catalog_preserves_models_and_pins_parent_v1(self) -> None:
        base = {
            "models": [
                {"slug": "gpt-test", "name": "OpenAI test"},
                {"slug": "gpt-5.6-sol", "old": True},
            ]
        }
        merged = manager.merged_catalog(base, {"slug": manager.MODEL, "new": True}, "gpt-5.6-sol")
        by_slug = {item["slug"]: item for item in merged["models"]}
        self.assertEqual(
            set(by_slug),
            {"gpt-test", "gpt-5.6-sol", manager.MODEL, manager.PRO_MODEL},
        )
        self.assertEqual(by_slug["gpt-test"]["name"], "OpenAI test")
        self.assertTrue(by_slug["gpt-5.6-sol"]["old"])
        self.assertEqual(by_slug["gpt-5.6-sol"]["multi_agent_version"], manager.PARENT_MULTI_AGENT_VERSION)
        self.assertEqual(
            by_slug[manager.MODEL],
            {
                "slug": manager.MODEL,
                "new": True,
                "multi_agent_version": manager.PARENT_MULTI_AGENT_VERSION,
            },
        )
        self.assertEqual(by_slug[manager.PRO_MODEL]["slug"], manager.PRO_MODEL)
        self.assertEqual(
            by_slug[manager.PRO_MODEL]["multi_agent_version"],
            manager.PARENT_MULTI_AGENT_VERSION,
        )

    def test_merged_catalog_pins_deepseek_child_v1_for_desktop_handoff(self) -> None:
        merged = manager.merged_catalog(
            {"models": [{"slug": "gpt-5.6-sol"}]},
            {"slug": manager.MODEL, "multi_agent_version": "v2"},
            "gpt-5.6-sol",
        )
        by_slug = {item["slug"]: item for item in merged["models"]}
        self.assertEqual(
            by_slug[manager.MODEL]["multi_agent_version"],
            manager.PARENT_MULTI_AGENT_VERSION,
        )
        self.assertEqual(
            by_slug[manager.PRO_MODEL]["multi_agent_version"],
            manager.PARENT_MULTI_AGENT_VERSION,
        )

    def test_merged_catalog_errors_when_parent_is_missing(self) -> None:
        with self.assertRaises(manager.ManagerError) as raised:
            manager.merged_catalog({"models": [{"slug": "gpt-test"}]}, {"slug": manager.MODEL}, "missing-parent")
        self.assertEqual(raised.exception.code, "parent_model_missing")

    def test_parent_model_has_no_hardcoded_fallback(self) -> None:
        self.assertEqual(
            manager.configured_parent_model({"model": "gpt-future-parent"}),
            "gpt-future-parent",
        )
        self.assertIsNone(manager.configured_parent_model({}))
        self.assertIsNone(manager.configured_parent_model({"model": manager.MODEL}))

    def test_agent_is_standalone_text_only_high_reasoning(self) -> None:
        text = manager.expected_agent_text()
        self.assertEqual(manager.ROLE, "DeepSeek-v4-flash")
        self.assertIn('name = "DeepSeek-v4-flash"', text)
        self.assertIn('nickname_candidates = ["DeepSeek-v4-flash"]', text)
        self.assertNotIn("DeepSeekWorker", text)
        self.assertIn('model_provider = "deepseek"', text)
        self.assertIn('model_reasoning_effort = "high"', text)
        self.assertIn("text-only", text)
        self.assertIn("Do not spawn additional subagents", text)
        self.assertIn("WORKER_REPORT", text)
        self.assertIn("preserve unrelated user changes", text)
        self.assertIn("distinguish verified results from assumptions", text)

    def test_pro_agent_is_standalone_and_uses_v4_pro(self) -> None:
        text = manager.expected_pro_agent_text()
        self.assertEqual(manager.PRO_ROLE, "DeepSeek-v4-pro")
        self.assertIn('name = "DeepSeek-v4-pro"', text)
        self.assertIn('nickname_candidates = ["DeepSeek-v4-pro"]', text)
        self.assertIn(f'model = "{manager.PRO_MODEL}"', text)
        self.assertIn('model_provider = "deepseek"', text)
        self.assertIn('model_reasoning_effort = "high"', text)
        self.assertIn("WORKER_REPORT", text)

    def test_legacy_agent_contract_remains_byte_compatible_for_migration(self) -> None:
        self.assertNotIn(
            "nickname_candidates",
            manager.expected_legacy_agent_text(),
        )

    def test_agent_contract_forbids_parent_fallback_after_missing_assignment(self) -> None:
        text = manager.expected_agent_text()
        self.assertIn("must not substitute its own output", text)
        self.assertIn("report the handoff failure", text)

    def test_disable_accepts_windows_line_endings_in_managed_agent(self) -> None:
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            manager,
            "credential_has_key",
            return_value=False,
        ):
            paths = manager.resolve_paths(directory)
            paths.agent.parent.mkdir(parents=True, exist_ok=True)
            paths.agent.write_bytes(
                manager.expected_agent_text().replace("\n", "\r\n").encode()
            )
            manager.write_manifest(
                paths,
                {
                    "managed_agent_file": True,
                    "agent_sha256": manager.sha256_bytes(
                        manager.expected_agent_text().encode()
                    ),
                },
            )
            result = manager.disable(paths)
            self.assertTrue(result["changed"])
            self.assertFalse(paths.agent.exists())

    def test_disable_removes_managed_legacy_agent_before_migration(self) -> None:
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            manager,
            "credential_has_key",
            return_value=False,
        ):
            paths = manager.resolve_paths(directory)
            legacy_text = manager.expected_legacy_agent_text()
            paths.legacy_agent.parent.mkdir(parents=True, exist_ok=True)
            paths.legacy_agent.write_text(legacy_text)
            manager.write_manifest(
                paths,
                {
                    "schema_version": 3,
                    "managed_agent_file": True,
                    "agent_sha256": manager.sha256_bytes(legacy_text.encode()),
                },
            )
            result = manager.disable(paths)
            self.assertTrue(result["changed"])
            self.assertFalse(paths.legacy_agent.exists())

    def test_provider_auth_validation_checks_every_field(self) -> None:
        provider = {
            "name": "DeepSeek",
            "base_url": "https://api.deepseek.com/",
            "wire_api": "responses",
            "auth": manager.expected_provider_auth(),
        }
        self.assertEqual(manager.provider_conflicts(provider), [])
        for field in ("name", "base_url", "wire_api"):
            invalid = copy.deepcopy(provider)
            invalid[field] = "wrong"
            self.assertIn(f"model_providers.deepseek.{field}", manager.provider_conflicts(invalid))
        for field in manager.expected_provider_auth():
            invalid = copy.deepcopy(provider)
            invalid["auth"][field] = "wrong"
            self.assertIn(f"model_providers.deepseek.auth.{field}", manager.provider_conflicts(invalid))
        invalid = copy.deepcopy(provider)
        invalid["auth"] = None
        self.assertIn("model_providers.deepseek.auth", manager.provider_conflicts(invalid))

    def test_windows_provider_auth_uses_credential_helper(self) -> None:
        with mock.patch.object(manager, "platform_name", return_value="windows"):
            auth = manager.expected_provider_auth()
            block = manager.managed_provider_block()
        self.assertEqual(auth["command"], sys.executable)
        self.assertEqual(auth["args"][-1], "_credential-get")
        self.assertNotIn("/usr/bin/security", block)
        parsed = manager.parse_toml_text(block)
        self.assertEqual(
            parsed["model_providers"][manager.PROVIDER]["auth"],
            auth,
        )

    def test_credential_helper_writes_only_the_secret(self) -> None:
        output = io.StringIO()
        with mock.patch.object(
            manager.sys,
            "argv",
            [str(SCRIPT), "_credential-get"],
        ), mock.patch.object(
            manager,
            "read_credential_key",
            return_value="sk-test-placeholder",
        ), redirect_stdout(output):
            exit_code = manager.main()
        self.assertEqual(exit_code, 0)
        self.assertEqual(output.getvalue(), "sk-test-placeholder")

    def test_windows_credential_backend_delegates_to_credential_manager(self) -> None:
        with mock.patch.object(
            manager,
            "platform_name",
            return_value="windows",
        ), mock.patch.object(
            manager,
            "_windows_credential_exists",
            return_value=True,
        ) as exists, mock.patch.object(
            manager,
            "_windows_store_credential",
        ) as store, mock.patch.object(
            manager,
            "_windows_remove_credential",
            return_value=True,
        ) as remove:
            self.assertEqual(manager.credential_backend(), "windows-credential-manager")
            self.assertTrue(manager.credential_has_key())
            manager.store_credential_key("sk-test")
            self.assertTrue(manager.remove_credential_key())
        exists.assert_called_once_with()
        store.assert_called_once_with("sk-test")
        remove.assert_called_once_with()

    def test_windows_desktop_codex_does_not_fall_back_to_path(self) -> None:
        with mock.patch.dict(manager.os.environ, {}, clear=True), mock.patch.object(
            manager,
            "platform_name",
            return_value="windows",
        ), mock.patch.object(
            manager.shutil,
            "which",
            return_value=r"C:\Tools\codex.exe",
        ) as which:
            with self.assertRaises(manager.ManagerError) as raised:
                manager.find_desktop_codex()
        self.assertEqual(raised.exception.code, "desktop_codex_missing")
        which.assert_not_called()

    def test_windows_desktop_codex_requires_explicit_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = root / "codex.exe"
            candidate.parent.mkdir(parents=True, exist_ok=True)
            candidate.write_bytes(b"placeholder")
            with mock.patch.object(
                manager,
                "platform_name",
                return_value="windows",
            ):
                with self.assertRaises(manager.ManagerError) as raised:
                    manager.find_desktop_codex()
                self.assertEqual(
                    manager.find_desktop_codex(str(candidate)),
                    str(candidate.resolve()),
                )
            self.assertEqual(raised.exception.code, "desktop_codex_missing")

    def test_desktop_codex_override_must_be_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
            manager.os.environ,
            {"CODEX_DESKTOP_BIN": sys.executable},
            clear=True,
        ), mock.patch.object(manager, "platform_name", return_value="unsupported"):
            with self.assertRaises(manager.ManagerError):
                manager.find_desktop_codex()
            self.assertEqual(
                manager.find_desktop_codex(str(Path(sys.executable))),
                str(Path(sys.executable).resolve()),
            )

    def test_macos_store_credential_keeps_secret_out_of_argv(self) -> None:
        secret = "sk-sentinel-never-in-argv"
        proc = SimpleNamespace(returncode=0, stderr="")
        with mock.patch.object(manager.subprocess, "run", return_value=proc) as run:
            manager._macos_store_credential(secret)
        argv = run.call_args.args[0]
        self.assertNotIn(secret, argv)
        self.assertEqual(argv[-1], "-w")
        self.assertEqual(run.call_args.kwargs["input"], secret + "\n")

    def test_macos_credential_presence_does_not_read_secret(self) -> None:
        proc = SimpleNamespace(returncode=0)
        with mock.patch.object(manager.subprocess, "run", return_value=proc) as run:
            self.assertTrue(manager._macos_credential_exists())
        argv = run.call_args.args[0]
        self.assertNotIn("-w", argv)

    def test_static_status_is_configured_with_complete_codex_home(self) -> None:
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            manager,
            "credential_has_key",
            return_value=True,
        ), mock.patch.object(manager, "codex_version_text", return_value="codex-cli test"):
            paths = manager.resolve_paths(directory)
            paths.config.parent.mkdir(parents=True, exist_ok=True)
            paths.config.write_text(
                'model = "gpt-5.6-sol"\n'
                f"model_catalog_json = {manager.toml_string(str(paths.catalog))}\n"
                "[features]\n"
                "multi_agent_v2 = false\n"
                + manager.managed_provider_block()
            )
            paths.catalog.write_text(
                json.dumps(
                    {
                        "models": [
                            {"slug": "gpt-5.6-sol", "multi_agent_version": manager.PARENT_MULTI_AGENT_VERSION},
                            {
                                "slug": manager.MODEL,
                                "multi_agent_version": manager.PARENT_MULTI_AGENT_VERSION,
                            },
                            {
                                "slug": manager.PRO_MODEL,
                                "multi_agent_version": manager.PARENT_MULTI_AGENT_VERSION,
                            },
                        ]
                    }
                )
            )
            paths.agent.parent.mkdir(parents=True, exist_ok=True)
            paths.agent.write_text(manager.expected_agent_text())
            paths.pro_agent.write_text(manager.expected_pro_agent_text())
            manager.write_manifest(paths, {"schema_version": 5})
            status = manager.static_status(paths, "desktop-codex")
            self.assertEqual(status["status"], "configured")
            self.assertTrue(status["checks"]["parent_uses_plaintext_v1"])
            self.assertTrue(status["checks"]["deepseek_uses_plaintext_v1"])
            self.assertTrue(status["checks"]["deepseek_pro_uses_plaintext_v1"])
            self.assertTrue(status["checks"]["desktop_multi_agent_v2_disabled"])
            self.assertTrue(status["checks"]["desktop_codex_detected"])
            self.assertTrue(status["checks"]["provider_valid"])

    def test_static_status_rejects_deepseek_child_v2_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            manager,
            "credential_has_key",
            return_value=True,
        ), mock.patch.object(manager, "codex_version_text", return_value="codex-cli test"):
            paths = manager.resolve_paths(directory)
            paths.config.parent.mkdir(parents=True, exist_ok=True)
            paths.config.write_text(
                'model = "gpt-5.6-sol"\n'
                f"model_catalog_json = {manager.toml_string(str(paths.catalog))}\n"
                "[features]\n"
                "multi_agent_v2 = false\n"
                + manager.managed_provider_block()
            )
            paths.catalog.write_text(
                json.dumps(
                    {
                        "models": [
                            {
                                "slug": "gpt-5.6-sol",
                                "multi_agent_version": manager.PARENT_MULTI_AGENT_VERSION,
                            },
                            {"slug": manager.MODEL, "multi_agent_version": "v2"},
                        ]
                    }
                )
            )
            paths.agent.parent.mkdir(parents=True, exist_ok=True)
            paths.agent.write_text(manager.expected_agent_text())
            manager.write_manifest(paths, {"schema_version": 4})
            status = manager.static_status(paths, "desktop-codex")
            self.assertEqual(status["status"], "partial")
            self.assertFalse(status["checks"]["deepseek_uses_plaintext_v1"])

    def test_status_reports_legacy_role_migration_required(self) -> None:
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            manager,
            "credential_has_key",
            return_value=True,
        ), mock.patch.object(manager, "codex_version_text", return_value="codex-cli test"):
            paths = manager.resolve_paths(directory)
            paths.config.parent.mkdir(parents=True, exist_ok=True)
            paths.config.write_text(
                'model = "gpt-5.6-sol"\n'
                f"model_catalog_json = {manager.toml_string(str(paths.catalog))}\n"
                "[features]\n"
                "multi_agent_v2 = false\n"
                + manager.managed_provider_block()
            )
            paths.catalog.write_text(
                json.dumps(
                    {
                        "models": [
                            {"slug": "gpt-5.6-sol", "multi_agent_version": manager.PARENT_MULTI_AGENT_VERSION},
                            {"slug": manager.MODEL},
                        ]
                    }
                )
            )
            paths.legacy_agent.parent.mkdir(parents=True, exist_ok=True)
            paths.legacy_agent.write_text(manager.expected_legacy_agent_text())
            manager.write_manifest(paths, {"schema_version": 3})
            status = manager.static_status(paths, "desktop-codex")
            self.assertEqual(status["status"], "partial")
            self.assertTrue(status["checks"]["legacy_agent_exists"])
            self.assertTrue(status["checks"]["role_migration_required"])

    def test_native_test_uses_fresh_session_without_catalog_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = manager.resolve_paths(directory)
            paths.config.parent.mkdir(parents=True, exist_ok=True)
            paths.config.write_text('model = "gpt-5.6-sol"\n')
            stdout = (
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "collab_tool_call",
                            "tool": "spawn_agent",
                            "receiver_thread_ids": ["child-123"],
                        }
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "collab_tool_call",
                            "tool": "wait",
                            "agents_states": {
                                "child-123": {
                                    "status": "completed",
                                    "message": "NATIVE_DEEPSEEK_WORKER_OK",
                                }
                            },
                        },
                    }
                )
                + "\n"
            )
            proc = SimpleNamespace(returncode=0, stdout=stdout, stderr="")
            expected = {
                "model_provider": manager.PROVIDER,
                "model": manager.MODEL,
                "reasoning_effort": manager.EFFORT,
                "agent_role": manager.ROLE,
                "agent_nickname": manager.ROLE,
            }
            with mock.patch.object(manager.subprocess, "run", return_value=proc) as run, mock.patch.object(
                manager, "wait_for_child_metadata", return_value=expected
            ):
                result = manager.native_test(paths, "codex")
            argv = run.call_args.args[0]
            self.assertNotIn("--disable", argv)
            self.assertNotIn("--enable", argv)
            self.assertFalse(any("model_catalog_json" in value for value in argv))
            self.assertTrue(result["desktop_fresh_session_native"])
            self.assertEqual(result["child_id"], "child-123")
            self.assertEqual({key: result[key] for key in expected}, expected)

    def test_native_test_routes_deepseek_pro_with_exact_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = manager.resolve_paths(directory)
            paths.config.parent.mkdir(parents=True, exist_ok=True)
            paths.config.write_text('model = "gpt-5.6-sol"\n')
            stdout = "\n".join(
                (
                    json.dumps(
                        {
                            "type": "item.completed",
                            "item": {
                                "type": "collab_tool_call",
                                "tool": "spawn_agent",
                                "receiver_thread_ids": ["child-pro-123"],
                            },
                        }
                    ),
                    json.dumps(
                        {
                            "type": "item.completed",
                            "item": {
                                "type": "collab_tool_call",
                                "tool": "wait",
                                "agents_states": {
                                    "child-pro-123": {
                                        "status": "completed",
                                        "message": "NATIVE_DEEPSEEK_PRO_WORKER_OK",
                                    }
                                },
                            },
                        }
                    ),
                )
            )
            proc = SimpleNamespace(returncode=0, stdout=stdout, stderr="")
            expected = {
                "model_provider": manager.PROVIDER,
                "model": manager.PRO_MODEL,
                "reasoning_effort": manager.EFFORT,
                "agent_role": manager.PRO_ROLE,
                "agent_nickname": manager.PRO_NICKNAME,
            }
            with mock.patch.object(manager.subprocess, "run", return_value=proc), mock.patch.object(
                manager, "wait_for_child_metadata", return_value=expected
            ):
                result = manager.native_test(
                    paths,
                    "codex",
                    manager.PRO_ROLE,
                    manager.PRO_MODEL,
                    manager.PRO_NICKNAME,
                )
            self.assertEqual(result["child_id"], "child-pro-123")
            self.assertEqual({key: result[key] for key in expected}, expected)

    def test_native_test_rejects_multiple_spawns(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = manager.resolve_paths(directory)
            paths.config.parent.mkdir(parents=True, exist_ok=True)
            paths.config.write_text('model = "gpt-5.6-sol"\n')
            events = [
                {
                    "type": "item.completed",
                    "item": {
                        "type": "collab_tool_call",
                        "tool": "spawn_agent",
                        "receiver_thread_ids": ["child-1"],
                    }
                },
                {
                    "type": "item.completed",
                    "item": {
                        "type": "collab_tool_call",
                        "tool": "spawn_agent",
                        "receiver_thread_ids": ["child-2"],
                    }
                },
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": "NATIVE_DEEPSEEK_WORKER_OK"},
                },
            ]
            proc = SimpleNamespace(
                returncode=0,
                stdout="\n".join(json.dumps(event) for event in events),
                stderr="",
            )
            with mock.patch.object(manager.subprocess, "run", return_value=proc):
                with self.assertRaises(manager.ManagerError) as raised:
                    manager.native_test(paths, "codex")
            self.assertEqual(raised.exception.code, "native_route_mismatch")

    def test_native_test_rejects_parent_forged_token_without_child_message(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = manager.resolve_paths(directory)
            paths.config.parent.mkdir(parents=True, exist_ok=True)
            paths.config.write_text('model = "gpt-5.6-sol"\n')
            events = [
                {
                    "type": "item.completed",
                    "item": {
                        "type": "collab_tool_call",
                        "tool": "spawn_agent",
                        "receiver_thread_ids": ["child-1"],
                    }
                },
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": "NATIVE_DEEPSEEK_WORKER_OK"},
                },
            ]
            proc = SimpleNamespace(
                returncode=0,
                stdout="\n".join(json.dumps(event) for event in events),
                stderr="",
            )
            expected = {
                "model_provider": manager.PROVIDER,
                "model": manager.MODEL,
                "reasoning_effort": manager.EFFORT,
                "agent_role": manager.ROLE,
                "agent_nickname": manager.ROLE,
            }
            with mock.patch.object(manager.subprocess, "run", return_value=proc), mock.patch.object(
                manager,
                "wait_for_child_metadata",
                return_value=expected,
            ):
                with self.assertRaises(manager.ManagerError) as raised:
                    manager.native_test(paths, "codex")
            self.assertEqual(raised.exception.code, "native_route_mismatch")

    def test_wait_for_child_metadata_retries_until_visible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = manager.resolve_paths(directory)
            expected = {"model": manager.MODEL}
            with mock.patch.object(
                manager,
                "query_child_metadata",
                side_effect=[None, None, expected],
            ), mock.patch.object(manager.time, "sleep"):
                actual = manager.wait_for_child_metadata(
                    paths,
                    "child-123",
                    timeout_seconds=1,
                    poll_interval=0,
                )
            self.assertEqual(actual, expected)

    def test_operation_lock_times_out_when_another_operation_holds_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = manager.resolve_paths(directory)
            with mock.patch.object(
                manager,
                "try_acquire_file_lock",
                return_value=False,
            ), mock.patch.object(manager.time, "sleep"):
                with self.assertRaises(manager.ManagerError) as raised:
                    with manager.operation_lock(paths, timeout_seconds=0.01):
                        self.fail("锁已被占用时不应进入操作区")
            self.assertEqual(raised.exception.code, "operation_in_progress")

    def test_windows_file_lock_adapter_acquires_and_releases_one_byte(self) -> None:
        fake_msvcrt = SimpleNamespace(
            LK_NBLCK=1,
            LK_UNLCK=2,
            calls=[],
        )

        def locking(fd, mode, size):
            fake_msvcrt.calls.append((fd, mode, size))

        fake_msvcrt.locking = locking
        with tempfile.TemporaryDirectory() as directory:
            lock_path = Path(directory) / "manager.lock"
            with lock_path.open("a+") as lock_file, mock.patch.object(
                manager,
                "fcntl",
                None,
            ), mock.patch.object(manager, "msvcrt", fake_msvcrt):
                self.assertTrue(manager.try_acquire_file_lock(lock_file))
                manager.release_file_lock(lock_file)
        self.assertEqual([call[1:] for call in fake_msvcrt.calls], [(1, 1), (2, 1)])

    def test_onboarding_requests_credential_before_writing_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            manager,
            "credential_available",
            return_value=True,
        ), mock.patch.object(manager, "credential_has_key", return_value=False):
            paths = manager.resolve_paths(directory)
            result = manager.setup(paths, "desktop-codex", False, False)
            self.assertEqual(result, {"status": "credential_missing", "credential": "deepseek_api_key"})
            self.assertFalse(paths.config.exists())
            self.assertFalse(paths.manifest.exists())

    def test_skip_live_test_does_not_probe_diagnostic_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            manager,
            "credential_available",
            return_value=True,
        ), mock.patch.object(manager, "credential_has_key", return_value=True), mock.patch.object(
            manager,
            "install",
            return_value={"backup": "/tmp/backup", "adopted_existing": False},
        ), mock.patch.object(manager, "codex_version_text") as version:
            result = manager.setup(manager.resolve_paths(directory), "desktop-codex", False, True)
            self.assertEqual(result["status"], "configured")
            version.assert_not_called()

    def test_repeated_setup_preserves_ownership_and_previous_catalog_selection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = manager.resolve_paths(directory)
            external_catalog = "/tmp/catalog-before-deepseek.json"
            paths.config.parent.mkdir(parents=True, exist_ok=True)
            paths.config.write_text(
                f'model = "gpt-5.6-sol"\n'
                f'model_catalog_json = "{external_catalog}"\n'
                "[features]\n"
                "multi_agent_v2 = true\n"
            )
            paths.catalog.write_text(json.dumps({"models": [{"slug": "original"}]}))
            paths.agent.parent.mkdir(parents=True, exist_ok=True)
            paths.agent.write_text(manager.expected_agent_text())
            base = {"models": [{"slug": "gpt-5.6-sol"}, {"slug": "gpt-other"}]}
            patches = [
                mock.patch.object(manager, "fetch_official_deepseek_model", return_value={"slug": manager.MODEL}),
                mock.patch.object(manager, "load_base_catalog", return_value=base),
                mock.patch.object(manager, "codex_version_text", return_value="codex-cli test"),
                mock.patch.object(manager, "credential_available", return_value=True),
                mock.patch.object(manager, "credential_has_key", return_value=True),
            ]
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                first = manager.setup(paths, "codex", False, True)
                first_manifest = manager.read_manifest(paths)
                second = manager.setup(paths, "codex", False, True)
            self.assertEqual(first["status"], "configured")
            self.assertEqual(second["status"], "configured")
            self.assertEqual(first_manifest["previous_model_catalog_json"], external_catalog)
            manifest = manager.read_manifest(paths)
            self.assertEqual(manifest["previous_model_catalog_json"], external_catalog)
            self.assertTrue(manifest["managed_catalog_selection"])
            self.assertFalse(manifest["managed_agent_file"])
            self.assertTrue(manifest["catalog_preexisted"])
            self.assertTrue(manifest["adopted_existing"])
            self.assertTrue(manifest["managed_multi_agent_v2"])
            self.assertTrue(manifest["previous_multi_agent_v2"])
            self.assertFalse(
                manager.parse_toml_text(paths.config.read_text())["features"]["multi_agent_v2"]
            )

    def test_uninstall_restores_preexisting_catalog_and_selection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = manager.resolve_paths(directory)
            external_catalog = "/tmp/catalog-before-uninstall.json"
            original_catalog = {"models": [{"slug": "original", "custom": True}]}
            paths.config.parent.mkdir(parents=True, exist_ok=True)
            paths.config.write_text(
                f'model = "gpt-5.6-sol"\n'
                f'model_catalog_json = "{external_catalog}"\n'
                "[features]\n"
                "multi_agent_v2 = true\n"
            )
            paths.catalog.write_text(json.dumps(original_catalog) + "\n")
            paths.agent.parent.mkdir(parents=True, exist_ok=True)
            paths.agent.write_text(manager.expected_agent_text())
            patches = [
                mock.patch.object(manager, "fetch_official_deepseek_model", return_value={"slug": manager.MODEL}),
                mock.patch.object(
                    manager,
                    "load_base_catalog",
                    return_value={"models": [{"slug": "gpt-5.6-sol"}]},
                ),
                mock.patch.object(manager, "credential_has_key", return_value=False),
            ]
            with patches[0], patches[1], patches[2]:
                manager.install(paths, "codex")
                result = manager.uninstall(paths, remove_credential=False)
            self.assertTrue(result["catalog_restored"])
            self.assertFalse(result["catalog_removed"])
            self.assertEqual(json.loads(paths.catalog.read_text()), original_catalog)
            parsed = manager.parse_toml_text(paths.config.read_text())
            self.assertEqual(parsed["model_catalog_json"], external_catalog)
            self.assertTrue(parsed["features"]["multi_agent_v2"])
            self.assertNotIn(manager.PROVIDER_BEGIN, paths.config.read_text())
            self.assertTrue(paths.agent.is_file())

    def test_schema_v1_repair_then_uninstall_removes_managed_catalog_selection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = manager.resolve_paths(directory)
            paths.config.parent.mkdir(parents=True, exist_ok=True)
            paths.config.write_text(
                'model = "gpt-5.6-sol"\n'
                f"model_catalog_json = {manager.toml_string(str(paths.catalog))}\n"
                + manager.managed_provider_block()
            )
            paths.catalog.write_text(
                json.dumps(
                    {
                        "models": [
                            {"slug": "gpt-5.6-sol"},
                            {"slug": manager.MODEL},
                        ]
                    }
                )
                + "\n"
            )
            paths.agent.parent.mkdir(parents=True, exist_ok=True)
            paths.agent.write_text(manager.expected_agent_text())
            manager.write_manifest(
                paths,
                {
                    "schema_version": 1,
                    "previous_model_catalog_json": None,
                    "managed_provider_block": True,
                    "managed_agent_file": True,
                },
            )
            patches = [
                mock.patch.object(
                    manager,
                    "fetch_official_deepseek_model",
                    return_value={"slug": manager.MODEL},
                ),
                mock.patch.object(
                    manager,
                    "load_base_catalog",
                    return_value={"models": [{"slug": "gpt-5.6-sol"}]},
                ),
                mock.patch.object(manager, "credential_has_key", return_value=False),
            ]
            with patches[0], patches[1], patches[2]:
                manager.install(paths, "codex")
                manifest = manager.read_manifest(paths)
                self.assertTrue(manifest["managed_catalog_selection"])
                self.assertFalse(manifest["catalog_preexisted"])
                manager.uninstall(paths, remove_credential=False)
            parsed = manager.parse_toml_text(paths.config.read_text())
            self.assertNotIn("model_catalog_json", parsed)
            self.assertFalse(paths.catalog.exists())

    def test_uninstall_rolls_back_all_files_after_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = manager.resolve_paths(directory)
            paths.config.parent.mkdir(parents=True, exist_ok=True)
            paths.config.write_text(
                'model = "gpt-5.6-sol"\n'
                f"model_catalog_json = {manager.toml_string(str(paths.catalog))}\n"
                + manager.managed_provider_block()
            )
            paths.catalog.write_text(json.dumps({"models": [{"slug": manager.MODEL}]}) + "\n")
            paths.agent.parent.mkdir(parents=True, exist_ok=True)
            paths.agent.write_text(manager.expected_agent_text())
            manager.write_manifest(
                paths,
                {
                    "schema_version": 2,
                    "managed_provider_block": True,
                    "managed_catalog_selection": True,
                    "managed_agent_file": True,
                    "catalog_preexisted": False,
                    "catalog_sha256": manager.sha256_bytes(paths.catalog.read_bytes()),
                    "agent_sha256": manager.sha256_bytes(
                        manager.expected_agent_text().encode()
                    ),
                },
            )
            before = {
                path: path.read_bytes()
                for path in (paths.config, paths.catalog, paths.agent, paths.manifest)
            }
            real_atomic_write = manager.atomic_write
            failed = False

            def fail_config_write(path, data, mode=0o600):
                nonlocal failed
                if path == paths.config and not paths.agent.exists() and not failed:
                    failed = True
                    raise OSError("injected failure")
                return real_atomic_write(path, data, mode)

            with mock.patch.object(manager, "atomic_write", side_effect=fail_config_write):
                with self.assertRaises(OSError):
                    manager.uninstall(paths, remove_credential=False)
            for path, content in before.items():
                self.assertEqual(path.read_bytes(), content)

    def test_repair_switching_parent_restores_old_version_and_records_new_original(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = manager.resolve_paths(directory)
            paths.config.parent.mkdir(parents=True, exist_ok=True)
            paths.config.write_text('model = "gpt-5.6-sol"\n')
            base = {
                "models": [
                    {"slug": "gpt-5.6-sol", "multi_agent_version": "original-sol"},
                    {"slug": "gpt-5.6-terra", "multi_agent_version": "original-terra"},
                ]
            }
            patches = [
                mock.patch.object(manager, "fetch_official_deepseek_model", return_value={"slug": manager.MODEL}),
                mock.patch.object(manager, "load_base_catalog", side_effect=lambda *_: copy.deepcopy(base)),
                mock.patch.object(manager, "codex_version_text", return_value="codex-cli test"),
                mock.patch.object(manager, "credential_available", return_value=True),
                mock.patch.object(manager, "credential_has_key", return_value=True),
            ]
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                manager.setup(paths, "codex", False, True)
                paths.config.write_text(
                    manager.set_top_level_key(paths.config.read_text(), "model", "gpt-5.6-terra")
                )
                manager.setup(paths, "codex", False, True)
            catalog = json.loads(paths.catalog.read_text())
            by_slug = {item["slug"]: item for item in catalog["models"]}
            self.assertEqual(by_slug["gpt-5.6-sol"]["multi_agent_version"], "original-sol")
            self.assertEqual(by_slug["gpt-5.6-terra"]["multi_agent_version"], manager.PARENT_MULTI_AGENT_VERSION)
            manifest = manager.read_manifest(paths)
            self.assertEqual(manifest["parent_model"], "gpt-5.6-terra")
            self.assertEqual(manifest["parent_multi_agent_version"], manager.PARENT_MULTI_AGENT_VERSION)
            self.assertEqual(manifest["parent_original_multi_agent_version"], "original-terra")

    def test_repair_migrates_managed_deepseek_worker_to_deepseek(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = manager.resolve_paths(directory)
            legacy_agent = paths.home / "agents" / "DeepSeekWorker.toml"
            legacy_text = (
                manager.expected_agent_text()
                .replace('name = "DeepSeek"', 'name = "DeepSeekWorker"', 1)
                .replace("Text-only DeepSeek subagent", "Text-only DeepSeek worker", 1)
                .replace(
                    "You are DeepSeek, a focused text-only coding subagent",
                    "You are DeepSeek Worker, a focused text-only coding worker",
                    1,
                )
            )
            paths.config.parent.mkdir(parents=True, exist_ok=True)
            paths.config.write_text('model = "gpt-5.6-sol"\n')
            legacy_agent.parent.mkdir(parents=True, exist_ok=True)
            legacy_agent.write_text(legacy_text)
            manager.write_manifest(
                paths,
                {
                    "schema_version": 3,
                    "managed_agent_file": True,
                    "agent_preexisted": False,
                    "agent_sha256": manager.sha256_bytes(legacy_text.encode()),
                },
            )
            with mock.patch.object(
                manager,
                "fetch_official_deepseek_model",
                return_value={"slug": manager.MODEL},
            ), mock.patch.object(
                manager,
                "load_base_catalog",
                return_value={"models": [{"slug": "gpt-5.6-sol"}]},
            ):
                result = manager.install(paths, "codex")
            self.assertTrue(result["migrated_role"])
            self.assertTrue(paths.agent.is_file())
            self.assertEqual(paths.agent.read_text(), manager.expected_agent_text())
            self.assertFalse(legacy_agent.exists())
            manifest = manager.read_manifest(paths)
            self.assertEqual(manifest["schema_version"], 6)
            self.assertEqual(manifest["role"], "DeepSeek-v4-flash")
            self.assertTrue(manifest["legacy_agent_migrated"])
            self.assertTrue((Path(result["backup"]) / "DeepSeekWorker.toml").is_file())

    def test_repair_migrates_deepseek_role_to_explicit_flash_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = manager.resolve_paths(directory)
            old_text = manager.expected_old_agent_text()
            paths.config.parent.mkdir(parents=True, exist_ok=True)
            paths.config.write_text('model = "gpt-5.6-sol"\n')
            paths.old_agent.parent.mkdir(parents=True, exist_ok=True)
            paths.old_agent.write_text(old_text)
            manager.write_manifest(
                paths,
                {
                    "schema_version": 4,
                    "managed_agent_file": True,
                    "agent_preexisted": False,
                    "agent_sha256": manager.sha256_bytes(old_text.encode()),
                },
            )
            with mock.patch.object(
                manager,
                "fetch_official_deepseek_model",
                return_value={"slug": manager.MODEL},
            ), mock.patch.object(
                manager,
                "load_base_catalog",
                return_value={"models": [{"slug": "gpt-5.6-sol"}]},
            ):
                result = manager.install(paths, "codex")
            self.assertTrue(result["migrated_role"])
            self.assertFalse(paths.old_agent.exists())
            self.assertEqual(paths.agent.read_text(), manager.expected_agent_text())
            self.assertEqual(paths.pro_agent.read_text(), manager.expected_pro_agent_text())
            self.assertTrue(manager.read_manifest(paths)["old_role_migrated"])
            self.assertTrue((Path(result["backup"]) / "DeepSeek.toml").is_file())

    def test_role_migration_preserves_preexisting_flash_agent_on_disable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = manager.resolve_paths(directory)
            old_text = manager.expected_old_agent_text()
            flash_text = manager.expected_agent_text()
            paths.config.parent.mkdir(parents=True, exist_ok=True)
            paths.config.write_text('model = "gpt-5.6-sol"\n')
            paths.old_agent.parent.mkdir(parents=True, exist_ok=True)
            paths.old_agent.write_text(old_text)
            paths.agent.write_text(flash_text)
            manager.write_manifest(
                paths,
                {
                    "schema_version": 4,
                    "managed_agent_file": True,
                    "agent_preexisted": False,
                    "agent_sha256": manager.sha256_bytes(old_text.encode()),
                },
            )
            with mock.patch.object(
                manager,
                "fetch_official_deepseek_model",
                return_value={"slug": manager.MODEL},
            ), mock.patch.object(
                manager,
                "load_base_catalog",
                return_value={"models": [{"slug": "gpt-5.6-sol"}]},
            ), mock.patch.object(manager, "credential_has_key", return_value=True):
                manager.install(paths, "codex")
                manifest = manager.read_manifest(paths)
                disabled = manager.disable(paths)

            self.assertFalse(manifest["managed_agent_file"])
            self.assertTrue(manifest["agent_preexisted"])
            self.assertTrue(manifest["adopted_existing"])
            self.assertTrue(disabled["agent_preserved"])
            self.assertTrue(paths.agent.is_file())
            self.assertEqual(paths.agent.read_text(), flash_text)

    def test_repair_upgrades_manager_owned_deepseek_agent_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = manager.resolve_paths(directory)
            old_text = manager.expected_agent_text().replace(
                'nickname_candidates = ["DeepSeek-v4-flash"]\n',
                "",
            )
            paths.config.parent.mkdir(parents=True, exist_ok=True)
            paths.config.write_text('model = "gpt-5.6-sol"\n')
            paths.agent.parent.mkdir(parents=True, exist_ok=True)
            paths.agent.write_text(old_text)
            manager.write_manifest(
                paths,
                {
                    "schema_version": 4,
                    "managed_agent_file": True,
                    "agent_preexisted": False,
                    "agent_sha256": manager.sha256_bytes(old_text.encode()),
                },
            )
            with mock.patch.object(
                manager,
                "fetch_official_deepseek_model",
                return_value={"slug": manager.MODEL, "multi_agent_version": "v2"},
            ), mock.patch.object(
                manager,
                "load_base_catalog",
                return_value={"models": [{"slug": "gpt-5.6-sol"}]},
            ):
                result = manager.install(paths, "codex")
            self.assertTrue(result["upgraded_agent_contract"])
            self.assertEqual(paths.agent.read_text(), manager.expected_agent_text())
            self.assertEqual(
                manager.read_manifest(paths)["deepseek_multi_agent_version"],
                manager.PARENT_MULTI_AGENT_VERSION,
            )

    def test_failed_role_migration_restores_legacy_agent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = manager.resolve_paths(directory)
            legacy_text = manager.expected_legacy_agent_text()
            paths.config.parent.mkdir(parents=True, exist_ok=True)
            paths.config.write_text('model = "gpt-5.6-sol"\n')
            paths.legacy_agent.parent.mkdir(parents=True, exist_ok=True)
            paths.legacy_agent.write_text(legacy_text)
            manager.write_manifest(
                paths,
                {
                    "schema_version": 3,
                    "managed_agent_file": True,
                    "agent_preexisted": False,
                    "agent_sha256": manager.sha256_bytes(legacy_text.encode()),
                },
            )
            with mock.patch.object(
                manager,
                "fetch_official_deepseek_model",
                return_value={"slug": manager.MODEL},
            ), mock.patch.object(
                manager,
                "load_base_catalog",
                return_value={"models": [{"slug": "gpt-5.6-sol"}]},
            ), mock.patch.object(
                manager,
                "write_manifest",
                side_effect=OSError("injected manifest failure"),
            ):
                with self.assertRaises(OSError):
                    manager.install(paths, "codex")
            self.assertEqual(paths.legacy_agent.read_text(), legacy_text)
            self.assertFalse(paths.agent.exists())

    def test_install_removes_legacy_role_marker_and_uses_standalone_agent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = manager.resolve_paths(directory)
            paths.config.parent.mkdir(parents=True, exist_ok=True)
            legacy_role = (
                f"{manager.ROLE_BEGIN}\n"
                "[agents.DeepSeekWorker]\n"
                'description = "legacy role registration"\n'
                f"config_file = {manager.toml_string(str(paths.agent))}\n"
                f"{manager.ROLE_END}\n"
            )
            paths.config.write_text('model = "gpt-5.6-sol"\n' + legacy_role)
            patches = [
                mock.patch.object(manager, "fetch_official_deepseek_model", return_value={"slug": manager.MODEL}),
                mock.patch.object(
                    manager,
                    "load_base_catalog",
                    return_value={"models": [{"slug": "gpt-5.6-sol"}]},
                ),
            ]
            with patches[0], patches[1]:
                manager.install(paths, "codex")
            config_text = paths.config.read_text()
            self.assertNotIn(manager.ROLE_BEGIN, config_text)
            self.assertNotIn(manager.ROLE_END, config_text)
            self.assertNotIn("[agents.DeepSeekWorker]", config_text)
            self.assertEqual(paths.agent.read_text(), manager.expected_agent_text())
            self.assertTrue(manager.read_manifest(paths)["legacy_role_block_removed"])

    def test_install_removes_compatible_unmarked_legacy_role(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = manager.resolve_paths(directory)
            paths.config.parent.mkdir(parents=True, exist_ok=True)
            paths.config.write_text(
                'model = "gpt-5.6-sol"\n'
                "[agents.DeepSeekWorker]\n"
                'description = "legacy role registration"\n'
                f"config_file = {manager.toml_string(str(paths.agent))}\n"
            )
            patches = [
                mock.patch.object(
                    manager,
                    "fetch_official_deepseek_model",
                    return_value={"slug": manager.MODEL},
                ),
                mock.patch.object(
                    manager,
                    "load_base_catalog",
                    return_value={"models": [{"slug": "gpt-5.6-sol"}]},
                ),
            ]
            with patches[0], patches[1]:
                manager.install(paths, "codex")
            config_text = paths.config.read_text()
            self.assertNotIn("[agents.DeepSeekWorker]", config_text)
            self.assertTrue(manager.read_manifest(paths)["legacy_role_block_removed"])

    def test_install_removes_quoted_legacy_role_and_status_requires_absence(self) -> None:
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            manager,
            "credential_has_key",
            return_value=True,
        ), mock.patch.object(manager, "codex_version_text", return_value="codex-cli test"):
            paths = manager.resolve_paths(directory)
            paths.config.parent.mkdir(parents=True, exist_ok=True)
            paths.config.write_text(
                'model = "gpt-5.6-sol"\n'
                f"model_catalog_json = {manager.toml_string(str(paths.catalog))}\n"
                "[features]\n"
                "multi_agent_v2 = false\n"
                + manager.managed_provider_block()
                + '\n[agents."DeepSeekWorker"]\n'
                'description = "legacy role registration"\n'
                f"config_file = {manager.toml_string(str(paths.agent))}\n"
            )
            paths.catalog.write_text(
                json.dumps(
                    {
                        "models": [
                            {
                                "slug": "gpt-5.6-sol",
                                "multi_agent_version": manager.PARENT_MULTI_AGENT_VERSION,
                            },
                            {"slug": manager.MODEL},
                        ]
                    }
                )
            )
            paths.agent.parent.mkdir(parents=True, exist_ok=True)
            paths.agent.write_text(manager.expected_agent_text())
            manager.write_manifest(paths, {"schema_version": 2})
            self.assertEqual(manager.static_status(paths, "desktop-codex")["status"], "partial")
            patches = [
                mock.patch.object(
                    manager,
                    "fetch_official_deepseek_model",
                    return_value={"slug": manager.MODEL},
                ),
                mock.patch.object(
                    manager,
                    "load_base_catalog",
                    return_value={"models": [{"slug": "gpt-5.6-sol"}]},
                ),
            ]
            with patches[0], patches[1]:
                manager.install(paths, "codex")
            self.assertNotIn('[agents."DeepSeekWorker"]', paths.config.read_text())
            self.assertEqual(manager.static_status(paths, "desktop-codex")["status"], "configured")

    def test_status_reports_partial_for_empty_home(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            status = manager.static_status(manager.resolve_paths(directory))
            self.assertEqual(status["status"], "partial")
            self.assertFalse(status["checks"]["provider_registered"])


if __name__ == "__main__":
    unittest.main()
