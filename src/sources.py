"""Поиск/проверка свежести/загрузка подписок.

Свежесть определяется содержимым: sha1 тела подписки.
Источник считается живым, если содержимое менялось
недавно; умершие источники (нет обновлений > stale_days) отбрасываются.
"""
import hashlib
import json
import os
import subprocess
import time
import urllib.parse

import log

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

RAW = "https://raw.githubusercontent.com/{repo}/{branch}/{file}"


def _curl(args: list, proxy: str = None, timeout: int = 40) -> str:
    cmd = ["curl", "-sL", "--max-time", str(timeout), "-A", UA]
    if proxy:
        cmd += ["-x", proxy]
    cmd += args
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout + 15,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if r.returncode != 0:
            return ""
        return r.stdout.decode("utf-8", "replace")
    except Exception:
        return ""


def fetch_urls(urls: list, proxies: list, workers: int = 8) -> dict:
    """Параллельная загрузка подписок. Возвращает {url: тело}."""
    import concurrent.futures as cf
    out = {}
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(fetch_url, u, proxies): u for u in urls}
        for f in cf.as_completed(futs):
            u = futs[f]
            try:
                body = f.result()
            except Exception:
                body = ""
            if body:
                out[u] = body
    return out


def fetch_url(url: str, proxies: list) -> str:
    """Пытается chain прокси -> direct."""
    for px in proxies:
        if px == "direct":
            body = _curl([url])
            if body:
                return body
        else:
            body = _curl([url], proxy=px)
            if not body:
                body = _curl([url], proxy=px)
            if body:
                return body
        time.sleep(0.3)
    return ""


def _sha(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()


class SourceManager:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.log = log.get_logger()
        self.path = os.path.join(cfg["paths"]["state_dir"], "sources.json")
        self.data = self._load()

    def _load(self) -> dict:
        if os.path.isfile(self.path):
            try:
                with open(self.path, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"discovered_at": 0, "sources": []}

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    # ---------------- discovery ----------------
    def discover_if_due(self, proxies: list, force: bool = False):
        hours = float(self.cfg["sources"].get("rediscover_hours", 12))
        due = force or (time.time() - self.data.get("discovered_at", 0)) > hours * 3600
        if not due:
            return
        self.log.info("Поиск новых источников (GitHub search)...")
        repos = []
        for q in self.cfg["sources"].get("search_queries", []):
            repos += self._search(q, proxies)
        seen = {}
        for r in repos:
            if r["full_name"] in seen:
                continue
            seen[r["full_name"]] = r
        stale_days = float(self.cfg["sources"].get("stale_days", 30))
        fresh = [r for r in seen.values()
                 if r.get("pushed_ts", 0) > (time.time() - stale_days * 86400)
                 and not r.get("archived", False)]
        self.log.info(f"Найдено репозиториев: {len(repos)}, свежих: {len(fresh)}")
        known = {s["repo"] for s in self.data["sources"]}
        added = 0
        for r in fresh[:10]:
            if r["full_name"] in known:
                continue
            branch = r.get("default_branch") or "main"
            url = self._sniff_repo(r["full_name"], branch, proxies)
            if url:
                self.data["sources"].append({
                    "repo": r["full_name"], "file": url.rsplit("/", 1)[-1],
                    "url": url, "first_seen": time.time(),
                    "last_sha": "", "last_ok": 0, "fails": 0, "last_count": 0,
                })
                added += 1
                self.log.info(f"  + источник {r['full_name']} -> {url}")
        self.data["discovered_at"] = time.time()
        self.save()
        if added == 0 and not self.data["sources"]:
            self._seed(proxies)

    def _seed(self, proxies):
        self.log.warn("Пусто после поиска; пробуем seed-репозитории")
        for repo in self.cfg["sources"].get("seed_repos", []):
            branch = "main"
            url = self._sniff_repo(repo, branch, proxies) or self._sniff_repo(repo, "master", proxies)
            if url:
                self.data["sources"].append({
                    "repo": repo, "file": url.rsplit("/", 1)[-1], "url": url,
                    "first_seen": time.time(), "last_sha": "", "last_ok": 0,
                    "fails": 0, "last_count": 0,
                })
        self.save()

    def _search(self, query: str, proxies: list) -> list:
        q = urllib.parse.quote(query)
        url = ("https://api.github.com/search/repositories?q=" + q +
               "&sort=updated&order=desc&per_page=12")
        body = fetch_url(url, proxies)
        try:
            d = json.loads(body)
        except Exception:
            return []
        out = []
        for it in d.get("items", []):
            import datetime
            pushed = it.get("pushed_at", "")
            pushed_ts = 0
            try:
                pushed_ts = datetime.datetime.strptime(
                    pushed, "%Y-%m-%dT%H:%M:%SZ").timestamp()
            except Exception:
                pass
            out.append({
                "full_name": it.get("full_name", ""),
                "default_branch": it.get("default_branch", "main"),
                "pushed_ts": pushed_ts,
                "archived": it.get("archived", False),
                "stars": it.get("stargazers_count", 0),
            })
        return out

    def _sniff_repo(self, repo: str, branch: str, proxies: list):
        for f in self.cfg["sources"].get("known_files", []):
            url = RAW.format(repo=repo, branch=branch, file=f)
            body = fetch_url(url, proxies)
            if body and not body.lstrip().startswith("404:"):
                return url
        return None

    # ---------------- тело источника на диск (кэш) ----------------
    def _bodies_dir(self) -> str:
        d = os.path.join(self.cfg["paths"]["state_dir"], "bodies")
        os.makedirs(d, exist_ok=True)
        return d

    def _store_body(self, name: str, body: str):
        """Сохраняет тело источника на диск — чтобы можно было перепарсить
        серверы без сети, даже если источник 'без изменений'."""
        if not body:
            return
        safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in name)[:80]
        try:
            with open(os.path.join(self._bodies_dir(), safe + ".txt"), "w",
                      encoding="utf-8", errors="replace") as f:
                f.write(body)
        except Exception as e:
            self.log.warn(f"  body cache fail {name}: {e}")

    def load_bodies(self) -> list:
        """Возвращает [(name, body)] всех сохранённых тел источников."""
        out = []
        d = self._bodies_dir()
        try:
            for fn in os.listdir(d):
                if not fn.endswith(".txt"):
                    continue
                try:
                    with open(os.path.join(d, fn), encoding="utf-8",
                              errors="replace") as f:
                        body = f.read()
                    if body:
                        out.append((fn[:-4], body))
                except Exception:
                    continue
        except Exception:
            pass
        return out

    # ---------------- refresh (fixed_urls) ----------------
    def refresh_fixed(self, proxies: list) -> list:
        """Загрузка ПОСТОЯННЫХ URL (fixed_urls из config) - всегда свежие.

        Возвращает [(src_dict, body)] для изменившихся. Тянется каждый
        полный цикл, независимо от GitHub search.
        """
        fixed = self.cfg.get("sources", {}).get("fixed_urls", [])
        if not fixed:
            return []
        urls = [f["url"] for f in fixed]
        bodies = fetch_urls(urls, proxies)
        changed = []
        for f in fixed:
            body = bodies.get(f["url"], "")
            if not body:
                self.log.warn("  fixed fetch fail: %s" % f["url"])
                continue
            h = _sha(body)
            self._store_body(f.get("name", "fixed"), body)
            base = {"repo": f.get("name", "fixed"), "url": f["url"],
                    "last_sha": h, "last_ok": time.time(), "fails": 0}
            key = f["url"]
            old = {s["url"]: s for s in self.data["sources"]}.get(key)
            if old is None:
                changed.append((base, body))
                self.log.info("  НОВЫЙ (fixed): %s (%d байт)" % (f["name"], len(body)))
                self.data["sources"].append(dict(base))
            elif old.get("last_sha") != h:
                changed.append((base, body))
                old["last_sha"] = h
                old["last_ok"] = time.time()
                self.log.info("  ОБНОВИЛСЯ (fixed): %s (%d байт)" % (f["name"], len(body)))
            else:
                old["last_ok"] = time.time()
                self.log.info("  без изменений (fixed): %s" % f["name"])
        self.save()
        return changed

    # ---------------- refresh ----------------
    def refresh(self, proxies: list) -> list:
        """Возвращает источники, содержимое которых ИЗМЕНИЛОСЬ, с текстом."""
        stale_days = float(self.cfg["sources"].get("stale_days", 30))
        changed = []
        alive = []
        urls = [s["url"] for s in self.data["sources"]]
        bodies = fetch_urls(urls, proxies)
        for s in self.data["sources"]:
            body = bodies.get(s["url"], "")
            if not body:
                s["fails"] = s.get("fails", 0) + 1
                self.log.warn(f"  fetch fail x{s['fails']}: {s['url']}")
                continue
            s["fails"] = 0
            s["last_ok"] = time.time()
            h = _sha(body)
            self._store_body(s["repo"], body)
            if h != s.get("last_sha"):
                s["last_sha"] = h
                changed.append((s, body))
                self.log.info(f"  ОБНОВИЛСЯ: {s['repo']} ({len(body)} байт)")
            else:
                self.log.info(f"  без изменений: {s['repo']}")
            alive.append(s)
        dead = [s for s in alive if (time.time() - s.get("last_ok", 0)) > stale_days * 86400]
        for s in dead:
            self.log.warn(f"  источник устарел (> {stale_days} дн.), убираю: {s['url']}")
        self.data["sources"] = [s for s in alive if s not in dead]
        self.save()
        return changed