#!/usr/bin/env bash
# 専用サーバーを VPS に入れる(最初の 1 回だけ。2026-11-21)。Ubuntu 22.04 / 24.04(Oracle Cloud の Ampere A1 など)。
#   curl -fsSL https://wwwnd.github.io/TenseiRPG-releases/dl/server/install.sh | sudo bash
# すること:
#   ・tensei という利用者と /opt/tensei(releases/ current save/)を作る
#   ・systemd:tensei.service(サーバー本体。落ちたら起動し直す)・tensei-update.timer(1 分ごとに新しい版を見る。2026-11-21 版のずれる時間を短く)
#   ・この機械のファイアウォールで TCP 7777 をあける(Oracle の画面の「セキュリティ・リスト」でもあける必要がある)
#   ・最新の版を入れて起動する
set -eu
SITE="${TENSEI_SITE:-https://wwwnd.github.io/TenseiRPG-releases}"
PORT="${TENSEI_PORT:-7777}"
MAX="${TENSEI_MAX:-16}"
HOME_DIR=/opt/tensei
[ "$(id -u)" = 0 ] || { echo "sudo をつけて動かしてください"; exit 1; }

echo "== 用意"
command -v python3 >/dev/null || { apt-get update -q && apt-get install -yq python3; }
id tensei >/dev/null 2>&1 || useradd --system --home "$HOME_DIR" --shell /usr/sbin/nologin tensei
mkdir -p "$HOME_DIR/releases" "$HOME_DIR/save" "$HOME_DIR/bin"
curl -fsSL "$SITE/dl/server/tensei_update.py?t=$(date +%s)" -o "$HOME_DIR/bin/tensei_update.py"
chown -R tensei:tensei "$HOME_DIR/save"

echo "== systemd"
cat > /etc/systemd/system/tensei.service <<EOF
[Unit]
Description=TenseiRPG dedicated server
After=network-online.target
Wants=network-online.target

[Service]
User=tensei
WorkingDirectory=$HOME_DIR/current
ExecStart=$HOME_DIR/current/TenseiServer --data $HOME_DIR/current/Data --save $HOME_DIR/save --port $PORT --max $MAX
Restart=always
RestartSec=5
TimeoutStopSec=20
Environment=DOTNET_gcServer=0
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$HOME_DIR/save
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF
cat > /etc/systemd/system/tensei-update.service <<EOF
[Unit]
Description=TenseiRPG server auto update

[Service]
Type=oneshot
TimeoutStartSec=15min
Environment=TENSEI_SITE=$SITE
ExecStart=/usr/bin/python3 $HOME_DIR/bin/tensei_update.py
EOF
cat > /etc/systemd/system/tensei-update.timer <<EOF
[Unit]
Description=TenseiRPG server auto update (every 1 min)

[Timer]
OnBootSec=1min
OnUnitActiveSec=1min

[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload

echo "== ファイアウォール(TCP $PORT)"
if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
  ufw allow "$PORT/tcp"
fi
if command -v iptables >/dev/null; then
  # Oracle の Ubuntu は iptables で最初から閉じている → REJECT の行より前に足す
  iptables -C INPUT -p tcp --dport "$PORT" -j ACCEPT 2>/dev/null || iptables -I INPUT 5 -p tcp --dport "$PORT" -m state --state NEW -j ACCEPT
  if command -v netfilter-persistent >/dev/null; then netfilter-persistent save; fi
fi

echo "== 最新の版を入れる"
TENSEI_SITE="$SITE" python3 "$HOME_DIR/bin/tensei_update.py" --force || true
systemctl enable tensei.service tensei-update.timer
systemctl start tensei-update.timer
systemctl start tensei.service || true
sleep 3
systemctl --no-pager status tensei.service | head -12
IP=$(curl -fsS https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}')
echo
echo "できました。ゲームからつなぐアドレス:$IP:$PORT"
echo "記録を見る:journalctl -u tensei -f   更新の記録:journalctl -u tensei-update"
