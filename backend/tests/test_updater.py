"""Usługa aktualizacji: sprawdzanie wersji, serwer i zadanie – na prawdziwym repozytorium git
i atrapie Dockera (bez demona Dockera)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "updater"))

from netpulse_updater import git_ops, state  # noqa: E402
from netpulse_updater.config import Settings  # noqa: E402
from netpulse_updater.envfile import topup_env  # noqa: E402
from netpulse_updater.job import Job  # noqa: E402
from netpulse_updater.server import UpdaterApp, make_handler  # noqa: E402

pytestmark = pytest.mark.skipif(
    subprocess.run(["git", "--version"], capture_output=True).returncode != 0, reason="brak gita"
)

GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
}
ENV_EXAMPLE_V1 = "POSTGRES_PASSWORD=zmien-mnie\nNETPULSE_PORT=8000\n"
ENV_EXAMPLE_V2 = ENV_EXAMPLE_V1 + "NETPULSE_DIR=/opt/uplinkview\nNETPULSE_NOWA_FUNKCJA=on\n#KOMENTARZ=x\n"


def git(cwd: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, env=GIT_ENV, capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


class Repo:
    """Zdalne repozytorium (bare), katalog autora i katalog instalacji (klon)."""

    def __init__(self, tmp: Path):
        self.remote = tmp / "remote.git"
        self.author = tmp / "author"
        self.install = tmp / "install"
        git(tmp, "init", "-q", "--bare", "-b", "main", str(self.remote))
        git(tmp, "clone", "-q", str(self.remote), str(self.author))
        (self.author / "deploy").mkdir()
        (self.author / "deploy" / "docker-compose.yml").write_text("services: {}\n")  # znacznik instalacji UplinkView
        self.commit("0.1.0", "Pierwsza wersja", ENV_EXAMPLE_V1)
        git(tmp, "clone", "-q", str(self.remote), str(self.install))
        # .env instalacji (nieśledzony) powstaje przy instalacji
        (self.install / "deploy" / ".env").write_text("POSTGRES_PASSWORD=sekret\nNETPULSE_PORT=8000\n")

    def commit(self, version: str, subject: str, env_example: str | None = None) -> str:
        pkg = self.author / "backend" / "netpulse"
        pkg.mkdir(parents=True, exist_ok=True)
        (pkg / "__init__.py").write_text(f'"""x"""\n\n__version__ = "{version}"\n')
        if env_example is not None:
            (self.author / "deploy").mkdir(exist_ok=True)
            (self.author / "deploy" / ".env.example").write_text(env_example)
        git(self.author, "add", "-A")
        git(self.author, "commit", "-q", "-m", subject)
        git(self.author, "push", "-q", "origin", "HEAD:main")
        return git(self.author, "rev-parse", "--short", "HEAD")

    def head(self) -> str:
        return git(self.install, "rev-parse", "--short", "HEAD")


@pytest.fixture
def repo(tmp_path):
    return Repo(tmp_path)


def settings(repo: Repo, **kw) -> Settings:
    return Settings(install_dir=repo.install, token="tajny-token", health_timeout_s=0, **kw)


# --- sprawdzanie wersji ------------------------------------------------------------


def test_parse_version():
    assert git_ops.parse_version('"""x"""\n__version__ = "1.2.3"\n') == "1.2.3"
    assert git_ops.parse_version("brak") is None


def test_current_reads_version_and_commit(repo):
    cur = git_ops.current(settings(repo))
    assert cur["version"] == "0.1.0" and cur["commit"] == repo.head() and cur["branch"] == "main"


def test_check_up_to_date(repo):
    info = git_ops.check(settings(repo))
    assert info["update_available"] is False and info["behind"] == 0 and info["changes"] == []
    assert info["latest"]["version"] == "0.1.0"


def test_check_lists_new_changes_and_version(repo):
    repo.commit("0.2.0", "Etap A: pierwsza zmiana")
    newest = repo.commit("0.3.0", "Etap B: druga zmiana")
    info = git_ops.check(settings(repo))
    assert info["update_available"] is True and info["behind"] == 2
    assert [c["subject"] for c in info["changes"]] == ["Etap B: druga zmiana", "Etap A: pierwsza zmiana"]
    assert info["latest"] == {"version": "0.3.0", "commit": newest}
    assert info["current"]["version"] == "0.1.0"  # sprawdzanie niczego nie instaluje
    assert repo.head() != newest


def test_check_reports_diverged_local_changes(repo):
    (repo.install / "lokalny.txt").write_text("x")
    git(repo.install, "add", "-A")
    git(repo.install, "commit", "-q", "-m", "lokalna zmiana")
    repo.commit("0.2.0", "zmiana ze źródła")
    info = git_ops.check(settings(repo))
    assert info["diverged"] is True and info["update_available"] is False


def break_source(repo: Repo) -> None:
    """Źródło aktualizacji przestaje być dostępne (zły adres origin)."""
    git(repo.install, "remote", "set-url", "origin", str(repo.remote.parent / "nie-ma.git"))


def test_check_fails_clearly_when_source_unreachable(repo):
    break_source(repo)
    with pytest.raises(git_ops.UpdateError, match="Nie udało się połączyć ze źródłem"):
        git_ops.check(settings(repo))


@pytest.mark.parametrize(
    "old",
    [
        "https://github.com/arkadiuszbaglaj/NetPulse.git",
        "https://github.com/arkadiuszbaglaj/NetPulse",
        "git@github.com:arkadiuszbaglaj/NetPulse.git",
    ],
)
def test_old_repository_address_moves_to_uplinkview(repo, old):
    """Zmiana nazwy (0.78.0): `origin` ze starym adresem GitHuba dostaje nowy, bez NETPULSE_UPDATE_REPO."""
    git(repo.install, "remote", "set-url", "origin", old)
    git_ops.set_origin(settings(repo))
    assert git(repo.install, "remote", "get-url", "origin") == git_ops.NEW_REPO == "https://github.com/uplinkview/uplinkview.git"


def test_other_origin_is_left_alone(repo):
    before = git(repo.install, "remote", "get-url", "origin")
    git_ops.set_origin(settings(repo))
    assert git(repo.install, "remote", "get-url", "origin") == before


def test_check_can_use_another_source(repo, tmp_path):
    (tmp_path / "inne").mkdir()
    other = Repo(tmp_path / "inne")
    other.commit("9.0.0", "z innego źródła")
    info = git_ops.check(settings(repo, repo_url=str(other.remote)))
    assert info["latest"]["version"] == "9.0.0"
    assert git(repo.install, "remote", "get-url", "origin") == str(other.remote)


# --- uzupełnianie .env -------------------------------------------------------------


def test_topup_env_adds_missing_keys_only(repo):
    repo.commit("0.2.0", "nowe zmienne", ENV_EXAMPLE_V2)
    git(repo.install, "pull", "-q", "--ff-only")
    before = (repo.install / "deploy" / ".env").read_text()
    added = topup_env(repo.install)
    assert added == ["NETPULSE_DIR", "NETPULSE_NOWA_FUNKCJA"]
    env = dict(line.split("=", 1) for line in (repo.install / "deploy" / ".env").read_text().splitlines())
    assert env["POSTGRES_PASSWORD"] == "sekret"  # istniejące wartości zostają
    assert env["NETPULSE_DIR"] == str(repo.install)
    assert env["NETPULSE_NOWA_FUNKCJA"] == "on"
    assert "KOMENTARZ" not in env  # zakomentowane zmienne nie są dopisywane
    assert (repo.install / "deploy" / ".env").read_text().startswith(before)
    assert topup_env(repo.install) == []  # drugi raz nic do dopisania


def test_topup_env_replaces_old_default_only(repo):
    env_file = repo.install / "deploy" / ".env"
    env_file.write_text(env_file.read_text() + "NETPULSE_WAN_SAMPLE_INTERVAL=0.5\n")
    topup_env(repo.install)
    assert "NETPULSE_WAN_SAMPLE_INTERVAL=0.25\n" in env_file.read_text()
    env_file.write_text(env_file.read_text().replace("=0.25", "=1"))
    topup_env(repo.install)
    assert "NETPULSE_WAN_SAMPLE_INTERVAL=1\n" in env_file.read_text()  # wartość ustawiona ręcznie zostaje


# --- serwer ------------------------------------------------------------------------


class Launcher:
    def __init__(self):
        self.calls = 0
        self.fail = False

    def __call__(self, s):
        self.calls += 1
        if self.fail:
            raise RuntimeError("docker run nie działa")


def make_app(repo, running=False, **kw):
    launcher = Launcher()
    flags = {"running": running}
    app = UpdaterApp(settings(repo, **kw), launcher=launcher, is_running=lambda s: flags["running"])
    return app, launcher, flags


def test_auth_required_for_everything_but_health(repo):
    app, _, _ = make_app(repo)
    assert app.handle("GET", "/health", None) == (200, {"status": "ok"})
    for method, path in (("GET", "/status"), ("POST", "/check"), ("POST", "/update")):
        assert app.handle(method, path, None)[0] == 401
        assert app.handle(method, path, "Bearer zly-token")[0] == 401
        assert app.handle(method, path, "tajny-token")[0] == 401  # bez słowa Bearer


def test_disabled_without_token(repo):
    app = UpdaterApp(replace(settings(repo), token=""), launcher=Launcher(), is_running=lambda s: False)
    code, body = app.handle("GET", "/status", "Bearer ")
    assert code == 503 and "wyłączone" in body["error"]
    assert app.handle("GET", "/health", None)[0] == 200


def test_unknown_routes_and_methods(repo):
    app, _, _ = make_app(repo)
    auth = "Bearer tajny-token"
    assert app.handle("GET", "/nie-ma", auth)[0] == 404
    assert app.handle("GET", "/update", auth)[0] == 404  # aktualizacja tylko przez POST
    assert app.handle("DELETE", "/status", auth)[0] == 404


def test_status_check_and_status_again(repo):
    app, _, _ = make_app(repo)
    auth = "Bearer tajny-token"
    code, body = app.handle("GET", "/status", auth)
    assert code == 200 and body["current"]["version"] == "0.1.0"
    assert body["info"] is None and body["job"]["state"] == "idle" and body["job"]["log"] == []

    repo.commit("0.2.0", "nowa funkcja")
    code, body = app.handle("POST", "/check", auth)
    assert code == 200 and body["info"]["update_available"] is True and body["info"]["behind"] == 1
    # wynik sprawdzenia jest zapamiętany
    assert app.handle("GET", "/status", auth)[1]["info"]["latest"]["version"] == "0.2.0"


def test_status_after_install_drops_stale_update_available(repo):
    """Po instalacji (z panelu albo `uplinkview update`) zapamiętane „jest nowa wersja” znika od razu."""
    app, _, _ = make_app(repo)
    auth = "Bearer tajny-token"
    repo.commit("0.2.0", "nowa funkcja")
    checked_at = app.handle("POST", "/check", auth)[1]["info"]["checked_at"]
    git(repo.install, "merge", "--ff-only", "-q", "origin/main")

    info = app.handle("GET", "/status", auth)[1]["info"]
    assert info["update_available"] is False and info["behind"] == 0 and info["changes"] == []
    assert info["current"]["version"] == "0.2.0"
    assert info["checked_at"] == checked_at  # rytm automatycznego sprawdzania się nie zmienia
    assert state.read_check(settings(repo))["update_available"] is False


def test_check_error_is_502(repo):
    app = UpdaterApp(settings(repo), launcher=Launcher(), is_running=lambda s: False, checker=_raise_update_error)
    code, body = app.handle("POST", "/check", "Bearer tajny-token")
    assert code == 502 and "źródłem" in body["error"]


def _raise_update_error(s):
    raise git_ops.UpdateError("Nie udało się połączyć ze źródłem aktualizacji: x")


def test_update_starts_job_once(repo):
    app, launcher, flags = make_app(repo)
    code, body = app.handle("POST", "/update", "Bearer tajny-token")
    assert code == 202 and launcher.calls == 1
    assert body["job"]["state"] == "running" and [p["id"] for p in body["job"]["phases"]][0] == "prepare"
    flags["running"] = True
    assert app.handle("POST", "/update", "Bearer tajny-token")[0] == 409
    assert launcher.calls == 1


def test_update_launch_failure_is_reported(repo):
    app, launcher, _ = make_app(repo)
    launcher.fail = True
    code, body = app.handle("POST", "/update", "Bearer tajny-token")
    assert code == 500 and "docker run nie działa" in body["error"]
    assert app.handle("GET", "/status", "Bearer tajny-token")[1]["job"]["state"] == "failed"


def test_dead_job_is_marked_failed_after_grace_period(repo):
    app, _, _ = make_app(repo)
    s = settings(repo)
    old = (datetime.now(UTC) - timedelta(minutes=5)).isoformat(timespec="seconds")
    status = state.new_status("0.1.0", "abc")
    status["started_at"] = old
    state.write_status(s, status)
    job = app.job_view()
    assert job["state"] == "failed" and "przerwana" in job["error"]

    # świeże zadanie, którego kontener jeszcze nie wystartował, nie jest uznane za martwe
    fresh = state.new_status("0.1.0", "abc")
    state.write_status(s, fresh)
    assert app.job_view()["state"] == "running"


def test_http_smoke(repo):
    app, _, _ = make_app(repo)
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        assert json.load(urllib.request.urlopen(f"{base}/health")) == {"status": "ok"}
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(f"{base}/status")
        assert exc.value.code == 401
        req = urllib.request.Request(f"{base}/status", headers={"Authorization": "Bearer tajny-token"})
        assert json.load(urllib.request.urlopen(req))["current"]["version"] == "0.1.0"
        req = urllib.request.Request(f"{base}/check", method="POST", data=b"{}", headers={"Authorization": "Bearer tajny-token"})
        assert json.load(urllib.request.urlopen(req))["info"]["behind"] == 0
    finally:
        server.shutdown()


# --- token API ↔ updater -------------------------------------------------------------


def test_token_is_generated_once_and_reused(tmp_path):
    from netpulse_updater.apitoken import ensure_token

    f = tmp_path / "run" / "updater-token"
    s = Settings(install_dir=tmp_path, token_file=str(f))
    first = ensure_token(s)
    assert len(first.token) >= 40 and f.read_text() == first.token
    assert ensure_token(s).token == first.token  # restart usługi nie zmienia tokenu
    assert not list(f.parent.glob("*.tmp"))


def test_token_regenerated_when_file_is_junk(tmp_path):
    from netpulse_updater.apitoken import ensure_token

    f = tmp_path / "updater-token"
    f.write_text("krotki")
    token = ensure_token(Settings(install_dir=tmp_path, token_file=str(f))).token
    assert token != "krotki" and len(token) >= 40


def test_token_is_unique_per_installation(tmp_path):
    from netpulse_updater.apitoken import ensure_token

    a = ensure_token(Settings(install_dir=tmp_path, token_file=str(tmp_path / "a"))).token
    b = ensure_token(Settings(install_dir=tmp_path, token_file=str(tmp_path / "b"))).token
    assert a != b


def test_disabled_updater_has_no_token_and_refuses_everything(tmp_path, repo):
    from netpulse_updater.apitoken import ensure_token

    f = tmp_path / "updater-token"
    s = ensure_token(replace(settings(repo), token="", token_file=str(f), enabled=False))
    assert s.token == "" and not f.exists()
    app = UpdaterApp(s, launcher=Launcher(), is_running=lambda _: False)
    assert app.handle("GET", "/status", "Bearer ")[0] == 503


def test_explicit_token_wins_over_file(tmp_path):
    from netpulse_updater.apitoken import ensure_token

    s = ensure_token(Settings(install_dir=tmp_path, token="jawny-token", token_file=str(tmp_path / "x")))
    assert s.token == "jawny-token" and not (tmp_path / "x").exists()


# --- walidacja katalogu instalacji ---------------------------------------------------


def test_wrong_install_dir_is_reported_and_blocks_update(tmp_path):
    empty = tmp_path / "pusty"
    empty.mkdir()
    launcher = Launcher()
    app = UpdaterApp(Settings(install_dir=empty, token="t"), launcher=launcher, is_running=lambda _: False)
    code, body = app.handle("POST", "/update", "Bearer t")
    assert code == 409 and "nie zawiera UplinkView" in body["error"] and "NETPULSE_DIR" in body["error"]
    assert launcher.calls == 0


def test_status_reports_no_problem_for_valid_install(repo):
    app, _, _ = make_app(repo)
    assert app.handle("GET", "/status", "Bearer tajny-token")[1]["problem"] is None


# --- zadanie aktualizacji ----------------------------------------------------------


class FakeDocker:
    """Atrapa runnera: `git` wykonuje naprawdę, `docker` tylko zapisuje wywołania."""

    def __init__(self, fail: tuple[str, ...] = (), health: list[int] | None = None):
        self.calls: list[str] = []
        self.fail = fail
        self.health = list(health or [])

    def __call__(self, cmd, cwd, log, gzip_to=None) -> int:
        line = " ".join(str(c) for c in cmd)
        self.calls.append(line)
        if cmd[0] == "git":
            r = subprocess.run(cmd, cwd=cwd, env=GIT_ENV, capture_output=True, text=True, encoding="utf-8")
            for out in (r.stdout, r.stderr):
                for ln in out.splitlines():
                    log(ln)
            return r.returncode
        if any(key in line for key in self.fail):
            return 1
        if gzip_to is not None:
            gzip_to.write_bytes(b"-- dump --" * 20)
        if "exec -T api" in line:
            return self.health.pop(0) if self.health else 0
        return 0

    def has(self, text: str) -> bool:
        return any(text in c for c in self.calls)


def run_job(repo, docker=None, free_mb=50_000, **kw):
    docker = docker or FakeDocker()
    s = settings(repo, **kw)
    job = Job(s, runner=docker, sleep=lambda _: None, disk_free_mb=lambda: free_mb)
    return job.run(), docker, s


def phases(s: Settings) -> dict[str, str]:
    return {p["id"]: p["status"] for p in state.read_status(s)["phases"]}


def test_job_success(repo):
    repo.commit("0.2.0", "Etap A")
    new = repo.commit("0.3.0", "Etap B", ENV_EXAMPLE_V2)
    result, docker, s = run_job(repo)
    assert result == "ok" and repo.head() == new
    st = state.read_status(s)
    assert st["state"] == "ok" and st["from_version"] == "0.1.0" and st["to_version"] == "0.3.0"
    assert st["finished_at"] and st["error"] is None
    assert set(phases(s).values()) == {"done"}
    # kolejność: kopia bazy przed pobraniem kodu, budowanie przed uruchomieniem, test zdrowia na końcu
    order = [
        next(i for i, c in enumerate(docker.calls) if key in c)
        for key in ("pg_dump", "git fetch", "git merge", " build", " up -d", "exec -T api")
    ]
    assert order == sorted(order)
    assert docker.has("builder prune -f --filter until=72h")  # sprzątanie po aktualizacji
    assert docker.has("builder prune -f --max-used-space 2gb") and not docker.has("--keep-storage")  # limit cache
    assert len(list((repo.install / "backups").glob("netpulse-*.sql.gz"))) == 1
    assert "NETPULSE_NOWA_FUNKCJA=on" in (repo.install / "deploy" / ".env").read_text()  # nowe zmienne w .env
    assert any("Kopia bazy" in line for line in state.log_tail(s))


def test_job_nothing_to_install(repo):
    result, docker, s = run_job(repo)
    assert result == "ok"
    st = state.read_status(s)
    assert st["note"] == "Masz już najnowszą wersję." and not docker.has(" build")
    assert phases(s)["build"] == "skipped"


def test_job_stops_when_disk_is_too_small(repo):
    repo.commit("0.2.0", "Etap A")
    before = repo.head()
    result, docker, s = run_job(repo, free_mb=100)
    assert result == "failed" and repo.head() == before
    st = state.read_status(s)
    assert "Za mało miejsca na dysku: wolne 100 MB" in st["error"] and "Nic nie zostało zmienione" in st["error"]
    assert docker.has("builder prune -af") and not docker.has("pg_dump") and not docker.has("git merge")
    assert phases(s)["prepare"] == "failed"


def test_job_stops_when_backup_fails(repo):
    repo.commit("0.2.0", "Etap A")
    before = repo.head()
    result, docker, s = run_job(repo, FakeDocker(fail=("pg_dump",)))
    assert result == "failed" and repo.head() == before
    assert "kopii bazy" in state.read_status(s)["error"]
    assert not docker.has("git merge") and not docker.has(" build")
    assert not list((repo.install / "backups").glob("*.sql.gz"))  # pusta kopia jest usuwana


def test_job_keeps_only_recent_backups(repo):
    repo.commit("0.2.0", "Etap A")
    d = repo.install / "backups"
    d.mkdir()
    for n in range(5):
        (d / f"netpulse-2020010{n}-000000.sql.gz").write_bytes(b"x" * 50)
    run_job(repo)
    names = sorted(p.name for p in d.glob("netpulse-*.sql.gz"))
    assert len(names) == 3
    assert "netpulse-20200100-000000.sql.gz" not in names and "netpulse-20200101-000000.sql.gz" not in names


def test_job_build_failure_restores_code_and_leaves_services_alone(repo):
    repo.commit("0.2.0", "Etap A")
    before = repo.head()
    result, docker, s = run_job(repo, FakeDocker(fail=(" build",)))
    assert result == "failed" and repo.head() == before  # kod wrócił do poprzedniej wersji
    st = state.read_status(s)
    assert "Budowanie" in st["error"] and "Usługi działają dalej na poprzedniej wersji" in st["note"]
    assert not docker.has(" up -d") and phases(s)["build"] == "failed"


def test_job_unhealthy_new_version_rolls_back(repo):
    repo.commit("0.2.0", "Etap A")
    before = repo.head()
    docker = FakeDocker(health=[1, 0])  # nowa wersja nie odpowiada, po powrocie działa
    result, docker, s = run_job(repo, docker)
    assert result == "rolled_back" and repo.head() == before
    st = state.read_status(s)
    assert st["state"] == "rolled_back" and "Przywrócono poprzednią wersję" in st["note"]
    assert "nie odpowiada" in st["error"]
    assert phases(s)["verify"] == "failed" and phases(s)["rollback"] == "done"
    assert sum(" up -d" in c for c in docker.calls) == 2  # uruchomienie nowej + powrót do starej
    assert docker.has("up -d --build")


def test_job_reports_failed_rollback_honestly(repo):
    repo.commit("0.2.0", "Etap A")
    result, _, s = run_job(repo, FakeDocker(health=[1, 1]))
    assert result == "failed"
    st = state.read_status(s)
    assert "Nie udało się przywrócić" in st["note"] and "backups" in st["note"]
    assert phases(s)["rollback"] == "failed"


def test_job_refuses_when_local_changes_block_fast_forward(repo):
    (repo.install / "lokalny.txt").write_text("x")
    git(repo.install, "add", "-A")
    git(repo.install, "commit", "-q", "-m", "lokalna zmiana")
    local = repo.head()
    repo.commit("0.2.0", "zmiana ze źródła")
    result, docker, s = run_job(repo)
    assert result == "failed" and repo.head() == local
    assert "lokalne zmiany" in state.read_status(s)["error"] and not docker.has(" build")


def test_job_fetch_failure(repo):
    break_source(repo)
    result, _, s = run_job(repo)
    assert result == "failed" and "pobrać aktualizacji" in state.read_status(s)["error"]


def test_job_unexpected_exception_never_leaves_running_state(repo):
    class Boom(FakeDocker):
        def __call__(self, cmd, cwd, log, gzip_to=None):
            raise OSError("brak miejsca na urządzeniu")

    s = settings(repo)
    result = Job(s, runner=Boom(), sleep=lambda _: None, disk_free_mb=lambda: 50_000).run()
    assert result == "failed"
    st = state.read_status(s)
    assert st["state"] == "failed" and st["finished_at"] and "Nieoczekiwany błąd" in st["error"]


def test_log_is_bounded_and_resettable(repo):
    s = settings(repo)
    state.reset_log(s)
    state.append_log(s, "x" * 5000)
    state.append_log(s, "\n")
    for n in range(300):
        state.append_log(s, f"linia {n}")
    tail = state.log_tail(s)
    assert len(tail) == state.LOG_TAIL and tail[-1] == "linia 299"
    assert all(len(line) <= state.MAX_LOG_LINE for line in tail)
    state.reset_log(s)
    assert state.log_tail(s) == []


def test_status_file_is_written_atomically(repo):
    s = settings(repo)
    for n in range(30):
        st = state.new_status(f"0.{n}.0", "abc")
        state.write_status(s, st)
        assert state.read_status(s)["from_version"] == f"0.{n}.0"
    assert not list(s.state_dir.glob("*.tmp"))
    time.sleep(0)  # (brak resztek plików tymczasowych)


def test_cache_cap_falls_back_to_keep_storage_on_older_docker(repo):
    """Docker 27 (obraz updatera) nie zna --max-used-space – wtedy ten sam limit przez --keep-storage."""
    repo.commit("0.2.0", "Etap A")
    result, docker, _ = run_job(repo, docker=FakeDocker(fail=("--max-used-space",)), build_cache_max="3gb")
    assert result == "ok"
    assert docker.has("builder prune -f --max-used-space 3gb") and docker.has("builder prune -f --keep-storage 3gb")


# --- podpis aktualizacji (od 0.69.0) -------------------------------------------------

import shutil  # noqa: E402

needs_ssh_keygen = pytest.mark.skipif(shutil.which("ssh-keygen") is None, reason="brak ssh-keygen")


def new_key(tmp: Path, name: str) -> Path:
    """Tymczasowy klucz podpisujący (bez hasła); zwraca ścieżkę klucza prywatnego."""
    key = tmp / name
    r = subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", name, "-f", str(key)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return key


def signers_line(key: Path) -> str:
    kind, blob = key.with_suffix(".pub").read_text().split()[:2]
    return f'netpulse-release namespaces="git" {kind} {blob}\n'


def sign_with(repo: Repo, key: Path | None) -> None:
    """Autor podpisuje kolejne commity kluczem `key` (None = bez podpisu)."""
    git(repo.author, "config", "gpg.format", "ssh")
    git(repo.author, "config", "commit.gpgsign", "true" if key else "false")
    if key:
        git(repo.author, "config", "user.signingkey", str(key.with_suffix(".pub")))


def trust(repo: Repo, *keys: Path) -> None:
    (repo.author / "deploy" / "update-signers").write_text("".join(signers_line(k) for k in keys))


@pytest.fixture
def signed(repo, tmp_path):
    """Instalacja w wersji, która ma już listę zaufanych kluczy (jak każda od 0.69.0)."""
    key = new_key(tmp_path, "klucz-wydan")
    sign_with(repo, key)
    trust(repo, key)
    repo.commit("0.2.0", "Lista zaufanych kluczy")
    git(repo.install, "pull", "-q", "--ff-only")
    repo.key = key
    return repo


@needs_ssh_keygen
def test_signed_update_is_offered_and_installed(signed):
    new = signed.commit("0.3.0", "Podpisana wersja")
    s = settings(signed)
    assert git_ops.signature_required(s)
    assert git_ops.check(s)["update_available"] is True
    result, docker, s = run_job(signed)
    assert result == "ok" and signed.head() == new
    assert any("Podpis aktualizacji prawidłowy" in line for line in state.log_tail(s))


@needs_ssh_keygen
def test_unsigned_update_is_refused(signed):
    old = signed.head()
    sign_with(signed, None)
    signed.commit("0.3.0", "Bez podpisu – np. zmiana z przejętego konta")
    with pytest.raises(git_ops.UpdateError, match="nie ma prawidłowego podpisu"):
        git_ops.check(settings(signed))
    result, docker, s = run_job(signed)
    assert result == "failed" and signed.head() == old
    st = state.read_status(s)
    assert "nie ma prawidłowego podpisu" in st["error"] and "Nic nie zostało zmienione" in st["error"]
    assert not docker.has("git merge") and not docker.has(" build") and not docker.has(" up -d")


@needs_ssh_keygen
def test_update_signed_with_unknown_key_is_refused(signed, tmp_path):
    old = signed.head()
    sign_with(signed, new_key(tmp_path, "obcy-klucz"))
    signed.commit("0.3.0", "Podpis obcym kluczem")
    with pytest.raises(git_ops.UpdateError, match="nie ma prawidłowego podpisu"):
        git_ops.check(settings(signed))
    result, _, _ = run_job(signed)
    assert result == "failed" and signed.head() == old


@needs_ssh_keygen
def test_attacker_cannot_swap_trusted_keys_in_the_same_update(signed, tmp_path):
    """Zaufana jest lista z zainstalowanej wersji: commit, który sam dopisuje swój klucz, nie przechodzi."""
    old = signed.head()
    evil = new_key(tmp_path, "klucz-napastnika")
    sign_with(signed, evil)
    trust(signed, evil)
    signed.commit("0.3.0", "Podmiana listy kluczy")
    result, _, _ = run_job(signed)
    assert result == "failed" and signed.head() == old


@needs_ssh_keygen
def test_key_rotation_through_signed_update(signed, tmp_path):
    """Nowy klucz wprowadza aktualizacja podpisana starym; potem działa nowy, a stary już nie."""
    fresh = new_key(tmp_path, "nowy-klucz")
    trust(signed, fresh)
    signed.commit("0.3.0", "Wymiana klucza (podpis starym)")
    assert run_job(signed)[0] == "ok"
    sign_with(signed, fresh)
    new = signed.commit("0.4.0", "Podpis nowym kluczem")
    assert run_job(signed)[0] == "ok" and signed.head() == new
    sign_with(signed, signed.key)
    signed.commit("0.5.0", "Podpis wycofanym kluczem")
    assert run_job(signed)[0] == "failed" and signed.head() == new


@needs_ssh_keygen
def test_verification_can_be_switched_off_for_own_source(signed):
    sign_with(signed, None)
    new = signed.commit("0.3.0", "Własny fork bez podpisów")
    s = settings(signed, verify_signatures=False)
    assert not git_ops.signature_required(s)
    assert git_ops.check(s)["update_available"] is True
    assert run_job(signed, verify_signatures=False)[0] == "ok" and signed.head() == new


def test_install_without_signers_file_updates_as_before(repo):
    """Wersje sprzed 0.69.0 nie mają listy kluczy – pierwsza aktualizacja do wersji z podpisami przechodzi bez sprawdzania."""
    assert not git_ops.signature_required(settings(repo))
    new = repo.commit("0.2.0", "Zwykła wersja")
    assert run_job(repo)[0] == "ok" and repo.head() == new
