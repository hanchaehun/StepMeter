"""결함판 빌드·실행 도구(benchmark/serve_variants.py)의 네트워크 없는 검사.

기대값 출처:
  - page_id 6개: human-study/pages.md "페이지와 과업"
  - 시작 주소: human-study/session-procedure.md "페이지별 주소"
  - shadcn-admin 기준선 8772: benchmark/selection.md "shadcn-admin 클리닝"
  - sha256("abc"): FIPS 180-2 부록 B.1 예제
  - sb-admin-2/small: R01 결함판 (#41에서 링크 간격 조정, PM 결정). verify_sb_admin_2로 발현을 잰다
"""
from __future__ import annotations

import argparse
import copy
import json
import socket
import tempfile
import unittest
from pathlib import Path

from benchmark import serve_variants as sv

PAGES_MD = {
    "sb-admin-2/register/baseline",
    "material-kit-react/products/baseline",
    "material-kit-react/sign-in/baseline",
    "sb-admin-2/login/small",
    "shadcn-admin/tasks/contrast",
    "shadcn-admin/users/below-fold",
}
SESSION_PROCEDURE_URLS = {
    "sb-admin-2/register/baseline": "http://127.0.0.1:8766/register.html",
    "material-kit-react/products/baseline": "http://127.0.0.1:8767/products",
    "material-kit-react/sign-in/baseline": "http://127.0.0.1:8767/sign-in",
    "sb-admin-2/login/small": "http://127.0.0.1:8791/login.html",
    "shadcn-admin/tasks/contrast": "http://127.0.0.1:8782/tasks",
    "shadcn-admin/users/below-fold": "http://127.0.0.1:8785/users",
}
SHA256_ABC = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def raw_config() -> dict:
    return json.loads(sv.CONFIG.read_text(encoding="utf-8"))


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.raw = raw_config()
        self.apps = sv.load_apps()

    def errors(self, raw: dict) -> list[str]:
        return sv.validate(raw, self.apps)

    def test_repository_config_is_valid(self):
        self.assertEqual(self.errors(self.raw), [])
        sv.load_config()

    def test_pages_are_the_six_from_pages_md(self):
        self.assertEqual({p["page_id"] for p in self.raw["pages"]}, PAGES_MD)

    def test_urls_match_session_procedure(self):
        table = {row["page_id"]: row["url"] for row in sv.page_table(sv.load_config())}
        self.assertEqual(table, SESSION_PROCEDURE_URLS)

    def test_required_builds_and_check_baseline(self):
        ids = {f"{b['app']}/{b['variant']}" for b in self.raw["builds"]}
        self.assertLessEqual({"sb-admin-2/baseline", "sb-admin-2/small", "material-kit-react/baseline",
                              "shadcn-admin/contrast", "shadcn-admin/below-fold"}, ids)
        # verify_shadcn_admin은 기준선 빌드와 비교하므로 check용 기준선이 있어야 한다
        self.assertIn("shadcn-admin/baseline", ids)
        config = sv.load_config()
        self.assertEqual(config.build("shadcn-admin/baseline").port, 8772)
        self.assertNotIn("shadcn-admin/baseline", {b.id for b in config.page_builds()})

    def test_ports_match_verify_script_defaults(self):
        # 수동 verify 실행(python -m benchmark.verify_*)이 serve 포트를 그대로 쓰도록 맞춘다
        from benchmark import verify_sb_admin_2, verify_shadcn_admin
        defaults = {"sb-admin-2": verify_sb_admin_2.DEFAULT_PORTS, "shadcn-admin": verify_shadcn_admin.DEFAULT_PORTS}
        for b in sv.load_config().builds:
            if b.app in defaults and b.variant != sv.BASELINE:
                self.assertEqual(b.port, defaults[b.app][b.variant], b.id)

    def test_every_defect_build_is_measured_by_its_verify_script(self):
        # check는 결함판마다 verify 스크립트의 같은 이름 측정(CASES)으로 발현을 본다. sb-admin-2/small도 R01 결함판이다
        import importlib
        for b in sv.load_config().builds:
            if b.variant == sv.BASELINE or b.app not in sv.VERIFY_MODULES:
                continue
            cases = importlib.import_module(sv.VERIFY_MODULES[b.app]).CASES
            self.assertIn(b.variant, cases, b.id)
        from benchmark import verify_sb_admin_2
        self.assertEqual(verify_sb_admin_2.CASES["small"][0], "R01")

    def test_duplicate_port_rejected(self):
        raw = copy.deepcopy(self.raw)
        raw["builds"][1]["port"] = raw["builds"][0]["port"]
        errors = self.errors(raw)
        self.assertTrue(any("겹친다" in e for e in errors), errors)

    def test_port_out_of_range_or_not_int_rejected(self):
        for port in (80, 70000, "8766", True):
            raw = copy.deepcopy(self.raw)
            raw["builds"][0]["port"] = port
            self.assertTrue(any("port" in e for e in self.errors(raw)), port)

    def test_duplicate_build_rejected(self):
        raw = copy.deepcopy(self.raw)
        raw["builds"].append({**raw["builds"][0], "port": 8999})
        self.assertTrue(any("두 번" in e for e in self.errors(raw)))

    def test_missing_mutation_patch_rejected(self):
        raw = copy.deepcopy(self.raw)
        raw["builds"].append({"app": "sb-admin-2", "variant": "no-such-variant", "port": 8999})
        self.assertTrue(any("no-such-variant.patch" in e for e in self.errors(raw)))

    def test_only_development_apps_are_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "apps.json"
            path.write_text(json.dumps({"apps": [{"id": "dev-app", "split": "development"},
                                                 {"id": "private-app", "split": "holdout"}]}), encoding="utf-8")
            self.assertEqual(set(sv.load_apps(path)), {"dev-app"})

    def test_recipe_for_app_outside_apps_json_rejected(self):
        raw = copy.deepcopy(self.raw)
        raw["recipes"]["private-app"] = {"install": None, "build": None, "serve_root": ".", "spa": False}
        self.assertTrue(any("recipes.private-app: benchmark/apps.json" in e for e in self.errors(raw)))

    def test_build_for_unknown_recipe_rejected(self):
        raw = copy.deepcopy(self.raw)
        raw["builds"].append({"app": "react-shopping-cart", "variant": "baseline", "port": 8999})
        self.assertTrue(any("recipes에 없는 앱" in e for e in self.errors(raw)))

    def test_page_without_build_rejected(self):
        raw = copy.deepcopy(self.raw)
        raw["pages"].append({"page_id": "shadcn-admin/users/small", "path": "/users"})
        self.assertTrue(any("shadcn-admin/small" in e for e in self.errors(raw)))

    def test_bad_page_id_and_path_rejected(self):
        for page in ({"page_id": "sb-admin-2/login", "path": "/login.html"},
                     {"page_id": "sb-admin-2/Login/small", "path": "/login.html"},
                     {"page_id": "sb-admin-2/login2/small", "path": "login.html"},
                     {"page_id": "sb-admin-2/login3/small", "path": "/../secret"}):
            raw = copy.deepcopy(self.raw)
            raw["pages"].append(page)
            self.assertTrue(self.errors(raw), page)

    def test_duplicate_page_rejected(self):
        raw = copy.deepcopy(self.raw)
        raw["pages"].append(dict(raw["pages"][0]))
        self.assertTrue(any("두 번" in e for e in self.errors(raw)))

    def test_bad_recipe_rejected(self):
        for field, value in (("install", "npm ci"), ("build", []), ("serve_root", "../dist"), ("spa", "yes")):
            raw = copy.deepcopy(self.raw)
            raw["recipes"]["material-kit-react"][field] = value
            self.assertTrue(any(field in e for e in self.errors(raw)), field)

    def test_select_builds(self):
        config = sv.load_config()
        self.assertEqual([b.id for b in sv.select_builds(config, ["shadcn-admin/contrast"], [])],
                         ["shadcn-admin/contrast"])
        self.assertEqual(sv.select_builds(config, [], config.page_builds()), config.page_builds())
        with self.assertRaises(sv.ConfigError):
            sv.select_builds(config, ["shadcn-admin/nope"], [])

    def test_url_for_page_id(self):
        config = sv.load_config()
        self.assertEqual(config.url_for("sb-admin-2/login/small"), "http://127.0.0.1:8791/login.html")
        with self.assertRaises(sv.ConfigError):
            config.url_for("sb-admin-2/login/baseline")


class HostTests(unittest.TestCase):
    def test_parse_host_accepts_ipv4_only(self):
        self.assertEqual(sv.parse_host("127.0.0.1"), "127.0.0.1")
        self.assertEqual(sv.parse_host("0.0.0.0"), "0.0.0.0")
        for bad in ("localhost", "::1", "127.0.0.256", ""):
            with self.assertRaises(argparse.ArgumentTypeError, msg=bad):
                sv.parse_host(bad)

    def test_url_host_for_wildcard_bind(self):
        self.assertEqual(sv.url_host("0.0.0.0"), "127.0.0.1")
        self.assertEqual(sv.url_host("192.168.0.5"), "192.168.0.5")

    def test_page_table_host_override_keeps_port_and_path(self):
        config = sv.load_config()
        table = {r["page_id"]: r["url"] for r in sv.page_table(config, "192.168.0.5")}
        self.assertEqual(table["shadcn-admin/users/below-fold"], "http://192.168.0.5:8785/users")
        self.assertEqual(config.url_for("sb-admin-2/login/small"), "http://127.0.0.1:8791/login.html")


class HashAndRebuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.bench = Path(self.tmp.name)
        (self.bench / "baselines").mkdir()
        (self.bench / "mutations" / "demo").mkdir(parents=True)
        (self.bench / "baselines" / "demo.patch").write_bytes(b"baseline\n")
        (self.bench / "mutations" / "demo" / "small.patch").write_bytes(b"small\n")
        self.app = {"id": "demo", "repository": "https://example.invalid/demo", "revision": "a" * 40}
        self.recipe = sv.Recipe(install=("npm", "ci"), build=("npm", "run", "build"), serve_root="dist", spa=True)
        self.build = sv.Build("demo", "small", 9001)

    def tearDown(self):
        self.tmp.cleanup()

    def key(self) -> dict:
        return sv.source_key(self.app, self.recipe, self.build, self.bench)

    def test_sha256_known_vector(self):
        path = self.bench / "abc.txt"
        path.write_bytes(b"abc")
        self.assertEqual(sv.sha256_file(path), SHA256_ABC)

    def test_patch_order_baseline_then_mutation(self):
        kinds = [(kind, rel) for kind, rel, _ in sv.patch_files(self.build, self.bench)]
        self.assertEqual(kinds, [("baseline", "benchmark/baselines/demo.patch"),
                                 ("mutation", "benchmark/mutations/demo/small.patch")])
        baseline = sv.Build("demo", "baseline", 9000)
        self.assertEqual([k for k, _, _ in sv.patch_files(baseline, self.bench)], ["baseline"])

    def test_same_hash_skips_rebuild(self):
        key = self.key()
        manifest = {**key, "output": {"sha256": "out"}}
        self.assertIsNone(sv.rebuild_reason(manifest, key, "out"))

    def test_rebuild_reasons(self):
        key = self.key()
        manifest = {**key, "output": {"sha256": "out"}}
        self.assertEqual(sv.rebuild_reason(None, key, None), "manifest 없음")
        self.assertEqual(sv.rebuild_reason(manifest, key, "out", force=True), "--force")
        self.assertEqual(sv.rebuild_reason(manifest, key, None), "빌드 결과 없음")
        self.assertIn("빌드 뒤", sv.rebuild_reason(manifest, key, "other"))
        self.assertIn("커밋", sv.rebuild_reason({**manifest, "revision": "b" * 40}, key, "out"))
        recipe = {**key["recipe"], "build": ["npm", "run", "other"]}
        self.assertIn("설치·빌드", sv.rebuild_reason({**manifest, "recipe": recipe}, key, "out"))

    def test_changed_patch_triggers_rebuild_and_names_it(self):
        manifest = {**self.key(), "output": {"sha256": "out"}}
        (self.bench / "mutations" / "demo" / "small.patch").write_bytes(b"small changed\n")
        reason = sv.rebuild_reason(manifest, self.key(), "out")
        self.assertIn("benchmark/mutations/demo/small.patch", reason)
        self.assertNotIn("baselines", reason)

    def test_tree_digest_ignores_hidden_and_tracks_content(self):
        root = self.bench / "out"
        (root / "sub").mkdir(parents=True)
        (root / ".git").mkdir()
        (root / "index.html").write_bytes(b"<p>a</p>")
        (root / "sub" / "app.js").write_bytes(b"1")
        (root / ".git" / "HEAD").write_bytes(b"x")
        first = sv.tree_digest(root)
        self.assertEqual(first["files"], 2)
        (root / ".git" / "HEAD").write_bytes(b"y")
        self.assertEqual(sv.tree_digest(root), first)
        (root / "sub" / "app.js").write_bytes(b"2")
        self.assertNotEqual(sv.tree_digest(root)["sha256"], first["sha256"])

    def test_tree_digest_depends_on_path(self):
        a, b = self.bench / "a", self.bench / "b"
        a.mkdir()
        b.mkdir()
        (a / "x.js").write_bytes(b"same")
        (b / "y.js").write_bytes(b"same")
        self.assertNotEqual(sv.tree_digest(a)["sha256"], sv.tree_digest(b)["sha256"])


class StaticServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.root = base / "dist"
        (self.root / "assets").mkdir(parents=True)
        (self.root / "sub").mkdir()
        (self.root / ".git").mkdir()
        for rel in ("index.html", "register.html", "assets/app.js", "sub/index.html", ".git/config"):
            (self.root / rel).write_text(rel, encoding="utf-8")
        (base / "secret.txt").write_text("secret", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def resolved(self, url: str, spa: bool) -> str | None:
        found = sv.resolve_path(self.root, url, spa)
        return None if found is None else found.relative_to(self.root.resolve()).as_posix()

    def test_spa_routes_fall_back_to_index(self):
        self.assertEqual(self.resolved("/", True), "index.html")
        self.assertEqual(self.resolved("/products", True), "index.html")
        self.assertEqual(self.resolved("/users?tab=1", True), "index.html")
        self.assertEqual(self.resolved("/assets/app.js", True), "assets/app.js")
        self.assertIsNone(self.resolved("/assets/missing.js", True))

    def test_static_site_has_no_fallback(self):
        self.assertEqual(self.resolved("/register.html?email=x", False), "register.html")
        self.assertEqual(self.resolved("/sub/", False), "sub/index.html")
        self.assertIsNone(self.resolved("/products", False))

    def test_hidden_and_parent_paths_blocked(self):
        # SPA여도 index.html로 돌리지 않고 거절한다
        for url in ("/.git/config", "/../secret.txt", "/%2e%2e/secret.txt", "/assets/..%2f..%2fsecret.txt",
                    "/C:/Windows/win.ini", "/assets\\..\\..\\secret.txt"):
            for spa in (False, True):
                self.assertIsNone(self.resolved(url, spa), (url, spa))

    def test_javascript_content_type(self):
        # Windows 레지스트리와 관계없이 모듈 스크립트가 막히지 않는 형식
        self.assertTrue(sv.content_type(Path("a.js")).startswith("text/javascript"))
        self.assertTrue(sv.content_type(Path("a.CSS")).startswith("text/css"))


class CommandAndPortTests(unittest.TestCase):
    def test_windows_node_shims_use_cmd(self):
        seen = []

        def which(name):
            seen.append(name)
            return f"C:/tools/{name}"

        self.assertEqual(sv.resolve_command(["npm", "ci"], os_name="nt", which=which), ["C:/tools/npm.cmd", "ci"])
        self.assertEqual(sv.resolve_command(["npx", "--yes", "pnpm@9.15.9"], os_name="nt", which=which)[0],
                         "C:/tools/npx.cmd")
        self.assertEqual(sv.resolve_command(["git", "init"], os_name="nt", which=which), ["C:/tools/git", "init"])
        self.assertEqual(sv.resolve_command(["npm", "ci"], os_name="posix", which=which)[0], "C:/tools/npm")
        self.assertEqual(seen, ["npm.cmd", "npx.cmd", "git", "npm"])

    def test_missing_command_raises(self):
        with self.assertRaises(sv.BuildError):
            sv.resolve_command(["npm", "ci"], os_name="nt", which=lambda _name: None)

    def test_port_in_use_detects_listener(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            s.listen()
            self.assertTrue(sv.port_in_use("127.0.0.1", s.getsockname()[1]))


if __name__ == "__main__":
    unittest.main()
