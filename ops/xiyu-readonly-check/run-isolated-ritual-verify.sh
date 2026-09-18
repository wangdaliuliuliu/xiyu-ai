#!/bin/bash
# 隔离验证「第四层：仪式已送出即完结」。
# 用一个独立 staging 目录 + 生产库副本，验证**待部署**的 initiative.mjs，
# 而不是生产正在跑的旧版本。
set -eu
STAGE=/tmp/xiyu-life-stage
TESTDB=/tmp/test-ritual.db

rm -rf "$STAGE"
mkdir -p "$STAGE/src" "$STAGE/node_modules"
cp -r /opt/xiyu-ai/src/. "$STAGE/src/"
cp /tmp/xiyu-sweep-deploy/initiative.mjs "$STAGE/src/initiative.mjs"
ln -sf /opt/xiyu-ai/node_modules/better-sqlite3 "$STAGE/node_modules/better-sqlite3"
cp /tmp/xiyu-sweep-deploy/verify-ritual-settle.mjs "$STAGE/verify.mjs"

rm -f "$TESTDB"
cp /opt/xiyu-ai/data/bot.db "$TESTDB"
chown -R xiyu:xiyu "$STAGE" "$TESTDB"

echo "--- 待验 initiative.mjs 含第四层? ---"
grep -c 'ritual_delivered_and_settled' "$STAGE/src/initiative.mjs"
echo "--- 生产当前 initiative.mjs 含第四层?（预期 0）---"
grep -c 'ritual_delivered_and_settled' /opt/xiyu-ai/src/initiative.mjs || true
echo

sudo -n -u xiyu env XIYU_TEST_DB="$TESTDB" XIYU_SRC="$STAGE/src" node "$STAGE/verify.mjs"
