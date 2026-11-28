#!/usr/bin/env python3
"""専用サーバーの自動更新(VPS の上で 1 分ごとに動く。install.sh が systemd のタイマーにする)。2026-11-21

ホームページの dl/server/manifest.json を見て、いま動いているサーバーとコードがちがえば:
  1. 新しい版をとってきて sha256 を確かめる
  2. /opt/tensei/releases/<コード>/ に広げる
  3. 動いているサーバーに save/restart_request を置く → サーバーが 5 分前から画面で知らせ、全員セーブして save/restart_ready を置く
     (だれも入っていなければすぐ)→ 止める → current を新しい版へ → 起動
  4. 30 秒たっても動いていなければ、前の版にもどす
世界のファイルは /opt/tensei/save(版を変えても残る)。

  sudo python3 tensei_update.py            # ふつう(変わっていなければ何もしない)
  sudo python3 tensei_update.py --force    # 同じでも入れ直す
"""
import hashlib, io, json, os, platform, shutil, subprocess, sys, tarfile, time, urllib.request

SITE = os.environ.get("TENSEI_SITE", "https://wwwnd.github.io/TenseiRPG-releases")
HOME = os.environ.get("TENSEI_HOME", "/opt/tensei")
NO_SYSTEMD = os.environ.get("TENSEI_NO_SYSTEMD") == "1"   # 確かめる用(systemd の無い所で入れかえだけ試す)
SERVICE = "tensei"
KEEP = 3   # 残しておく古い版の数


def log(t):
    print(time.strftime("[%m-%d %H:%M:%S] ") + t, flush=True)


def get(url):
    req = urllib.request.Request(url + ("&" if "?" in url else "?") + f"t={int(time.time())}", headers={"User-Agent": "tensei-update"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def rid():
    m = platform.machine().lower()
    return "linux-arm64" if m in ("aarch64", "arm64") else "linux-x64"


def current_code():
    try:
        return open(os.path.join(HOME, "current", "VERSION")).read().strip()
    except OSError:
        return ""


def active():
    return subprocess.run(["systemctl", "is-active", "--quiet", SERVICE]).returncode == 0


def switch(target):
    tmp = os.path.join(HOME, "current.new")
    if os.path.lexists(tmp): os.remove(tmp)
    os.symlink(target, tmp)
    os.replace(tmp, os.path.join(HOME, "current"))


def wait_for_players():
    """遊んでいる人に知らせてから止める(2026-11-21 ユーザー:突然落ちないように)。サーバーが restart_ready を置くまで待つ"""
    if not active():
        return
    save = os.path.join(HOME, "save")
    req, ready = os.path.join(save, "restart_request"), os.path.join(save, "restart_ready")
    try:
        if os.path.exists(ready): os.remove(ready)
        with open(req, "w") as f: f.write(time.strftime("%Y-%m-%dT%H:%M:%S"))
        os.chmod(req, 0o644)
    except OSError as e:
        log(f"知らせのファイルを置けません: {e}"); return
    log("サーバーに更新を知らせました。遊んでいる人がいれば 5 分待ちます")
    until = time.time() + int(os.environ.get("TENSEI_NOTICE_WAIT", "420"))
    while time.time() < until and active():
        if os.path.exists(ready):
            log("サーバーの準備ができました"); break
        time.sleep(5)
    else:
        log("待つ時間が過ぎたので、そのまま止めます")
    for p in (req, ready):
        try: os.remove(p)
        except OSError: pass


def main():
    force = "--force" in sys.argv
    man = json.loads(get(f"{SITE}/dl/server/manifest.json"))
    b = next((x for x in man["builds"] if x["rid"] == rid()), None)
    if not b:
        log(f"この機械({rid()})の版がありません"); return 1
    now = current_code()
    if now == man["code"] and not force:
        return 0
    log(f"新しい版 Ver {man['version']}(コード {man['code']})を入れます。いまは {now or 'なし'}")

    data = b"".join(get(f"{SITE}/dl/{p}") for p in b["parts"])
    if hashlib.sha256(data).hexdigest() != b["sha256"]:
        log("sha256 が合いません。入れません"); return 1
    rel = os.path.join(HOME, "releases", man["code"])
    if os.path.isdir(rel): shutil.rmtree(rel)
    os.makedirs(rel)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as t:
        try:
            t.extractall(os.path.join(HOME, "releases", ".x"), filter="data")
        except TypeError:   # 古い Python
            t.extractall(os.path.join(HOME, "releases", ".x"))
    src = os.path.join(HOME, "releases", ".x", b["rid"])
    for n in os.listdir(src): shutil.move(os.path.join(src, n), rel)
    shutil.rmtree(os.path.join(HOME, "releases", ".x"))
    with open(os.path.join(rel, "VERSION"), "w") as f: f.write(man["code"] + "\n")
    os.chmod(os.path.join(rel, "TenseiServer"), 0o755)
    prev = os.path.realpath(os.path.join(HOME, "current")) if os.path.lexists(os.path.join(HOME, "current")) else None
    if NO_SYSTEMD:
        switch(rel); log("入れかえました(systemd なし)"); return 0
    subprocess.run(["chown", "-R", "tensei:tensei", rel])
    wait_for_players()
    subprocess.run(["systemctl", "stop", SERVICE])
    switch(rel)
    subprocess.run(["systemctl", "start", SERVICE])
    time.sleep(30)
    if not active() and prev and os.path.isdir(prev):
        log("新しい版が動きません。前の版にもどします")
        switch(prev)
        subprocess.run(["systemctl", "restart", SERVICE])
        return 1
    log("入れかえました")

    # 古い版を片づける(いまの版・ひとつ前は残す)
    rels = sorted((os.path.join(HOME, "releases", n) for n in os.listdir(os.path.join(HOME, "releases"))), key=os.path.getmtime, reverse=True)
    for p in rels[KEEP:]:
        if p not in (rel, prev): shutil.rmtree(p, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
