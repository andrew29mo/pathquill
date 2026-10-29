#!/bin/sh
# Fresh installation only. Existing configuration/data are never overwritten.
set -eu
# Package files must remain root-owned, readable and never group/world writable.
umask 022
if [ "$(id -u)" -ne 0 ]; then echo 'root installation required' >&2; exit 1; fi
if [ "$#" -ne 1 ]; then echo 'Usage: install.sh /absolute/pathquill.whl' >&2; exit 1; fi
wheel=$(realpath -- "$1")
test -f "$wheel"
case "$wheel" in *.whl) ;; *) echo 'wheel required' >&2; exit 1;; esac
python3 -c 'import sys; assert sys.version_info >= (3,12)'
test "$(cat /proc/1/comm)" = systemd
for target in /opt/pathquill /etc/pathquill /var/lib/pathquill /etc/systemd/system/pathquill.service /etc/systemd/system/pathquill.service.d; do
    if [ -e "$target" ] || [ -L "$target" ]; then echo 'existing installation requires manual review' >&2; exit 1; fi
done
if [ "$(systemctl show pathquill.service --property=LoadState --value)" != not-found ]; then echo 'existing loaded/vendor unit requires manual review' >&2; exit 1; fi
if getent passwd pathquill >/dev/null || getent group pathquill >/dev/null; then echo 'existing account requires manual review' >&2; exit 1; fi
asset_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
install -d -m 0755 /opt/pathquill
python3 -m venv /opt/pathquill/venv
/opt/pathquill/venv/bin/python -I -m pip install --no-index --no-deps "$wheel"
useradd --system --user-group --home-dir /var/lib/pathquill --shell /usr/sbin/nologin pathquill
install -d -m 0750 -o root -g pathquill /etc/pathquill
install -m 0640 -o root -g pathquill "$asset_dir/config.example.json" /etc/pathquill/config.json
install -d -m 0700 -o pathquill -g pathquill /var/lib/pathquill
install -m 0644 -o root -g root "$asset_dir/pathquill.service" /etc/systemd/system/pathquill.service
systemctl daemon-reload
printf '%s\n' 'Installed, not started or enabled. Review /etc/pathquill/config.json before starting.'
