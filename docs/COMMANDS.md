# Kurulum ve doğrulama komut kataloğu

Bu dosya şimdiye kadar kullandığımız kurulum/doğrulama adımlarını taşınabilir biçimde
tutar. Sunucuya özel kimlik/yollar ve ham operasyon çıktıları özel günlükte kalır.
Komutları baştan sona körlemesine tekrar çalıştırma; normal kurulum INSTALLATION.md
akışındaki tek installer komutudur. Buradakiler teşhis, kabul ve yeniden üretim içindir.
Önce gerçek checkout yolunu seç:
```bash
REPO=/path/to/signal-desk-prediction
cd "$REPO"
PROJECT=signal-desk-prediction
```

## Host ve Docker erişimi
```bash
hostname
pwd
ps -p 1 -o comm=
command -v docker
command -v dockerd
systemctl is-active docker
systemctl status docker --no-pager -l
docker --version
docker compose version
docker buildx version
docker info --format '{{.Name}}'
df -h /
free -h
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
ss -ltnp '( sport = :8080 )'
```
Daemon/socket yoksa host bağlantısını düzelt; agent container'ına ikinci Docker
kurmak bu sorunu çözmez. Agent mount teşhisi (adı kullanıcı belirler):
```bash
AGENT_CONTAINER=your-agent-container
docker inspect "$AGENT_CONTAINER" --format 'Network={{.HostConfig.NetworkMode}}{{println}}{{range .Mounts}}{{println .Source "->" .Destination}}{{end}}'
```

## Repo ve mevcut ayarlar
```bash
git -c safe.directory="$PWD" remote -v
git -c safe.directory="$PWD" log -1 --oneline
git -c safe.directory="$PWD" status --short
test -f .env || cp .env.example .env
test -f config/config.yaml || cp config/config.example.yaml config/config.yaml
grep -n 'config_version' config/config.yaml config/config.example.yaml config.example.yaml
diff -u config/config.example.yaml config/config.yaml
```
Diff exit=1 farklılık demektir. Aktif config'i örnek dosyayla ezme.
Geçmişte doğrulanmış yalnız v15/v16 etiket farkının düzeltmesi:
```bash
sed -i -e 's/version: v15$/version: v16/' -e 's/config_version: cfg-v15-example-001$/config_version: cfg-v16-example-001/' config/config.yaml
```
Bu geçmiş düzeltme her kurulumda otomatik uygulanacak bir migration değildir.

## Build, config, test ve API
```bash
docker compose -p "$PROJECT" config -q
docker compose -p "$PROJECT" build api collector
docker compose -p "$PROJECT" run --rm --no-deps collector python -m signal_desk.tools.validate_all --config config/config.yaml
docker compose -p "$PROJECT" run --rm --no-deps collector python -m pytest -q
docker compose -p "$PROJECT" up -d --no-deps --wait --wait-timeout 90 api
docker compose -p "$PROJECT" ps
docker compose -p "$PROJECT" logs --tail=60 api
curl --fail --show-error http://127.0.0.1:8080/health
docker compose -p "$PROJECT" exec -T api python -m signal_desk.tools.install_check --health-url http://127.0.0.1:8080/health
```
API başlangıçta health:starting olabilir; up --wait sağlık kontrolünü bekler.
ready_for_enter=false mevcut eksik model/ledger kapsamıyla uyumludur.

## Snapshot ve kısa stream
```bash
docker compose -p "$PROJECT" run --rm --no-deps collector python -m signal_desk.collector.binance_collector --help
docker compose -p "$PROJECT" run --rm --no-deps collector python -m signal_desk.collector.binance_collector --mode once --config config/config.yaml
docker compose -p "$PROJECT" run --rm --no-deps collector python -u -m signal_desk.collector.binance_collector --mode stream --max-events 25 --config config/config.yaml
echo "STREAM_EXIT_CODE=$?"
docker compose -p "$PROJECT" run --rm --no-deps collector python -u -m signal_desk.collector.binance_collector --mode stream --max-events 1000 --config config/config.yaml
echo "STREAM_EXIT_CODE=$?"
```
Çıktı ve timeout kodunu tek shell'de yakalamak:
```bash
set -o pipefail
timeout 60s docker compose -p "$PROJECT" run --rm --no-deps collector python -u -m signal_desk.collector.binance_collector --mode stream --max-events 25 --config config/config.yaml 2>&1 | tee /tmp/signal-desk-stream-smoke.log
result=${PIPESTATUS[0]}
echo "STREAM_EXIT_CODE=$result"
```
124 timeout'tur. --rm ile çıkmış container silinir; No such container başarı kanıtı değildir.
Durum dosyası:
```bash
docker compose -p "$PROJECT" run --rm --no-deps collector python -c 'from pathlib import Path; print(Path("/data/status/collector_status.json").read_text())'
```

## Süreli continuous, kaynak ve soak
Aynı data volume'unda aynı anda yalnız bir collector çalıştır.
```bash
docker compose -p "$PROJECT" run --rm --no-deps collector python -u -m signal_desk.collector.binance_collector --mode continuous --max-run-seconds 60 --config config/config.yaml
echo "CONTINUOUS_EXIT_CODE=$?"
docker compose -p "$PROJECT" run --rm --no-deps collector python -u -m signal_desk.collector.binance_collector --mode continuous --max-run-seconds 300 --config config/config.yaml
echo "CONTINUOUS_EXIT_CODE=$?"
```
Arka plan kabul testi, otomatik süre sonu:
```bash
TEST_CONTAINER=signal-desk-soak-test
docker compose -p "$PROJECT" run -d --no-deps --name "$TEST_CONTAINER" collector python -u -m signal_desk.collector.binance_collector --mode continuous --max-run-seconds 3600 --config config/config.yaml
docker exec "$TEST_CONTAINER" cat /data/status/collector_status.json
docker stats --no-stream "$TEST_CONTAINER"
docker inspect "$TEST_CONTAINER" --format 'Memory={{.HostConfig.Memory}} NanoCpus={{.HostConfig.NanoCpus}} PidsLimit={{.HostConfig.PidsLimit}}'
docker logs --tail=10 "$TEST_CONTAINER"
docker inspect "$TEST_CONTAINER" --format 'Status={{.State.Status}} ExitCode={{.State.ExitCode}} OOMKilled={{.State.OOMKilled}} StartedAt={{.State.StartedAt}} FinishedAt={{.State.FinishedAt}}'
```
Çalışırken ExitCode=0 test tamamlandı demek değildir. Normal bitiş: STOPPED,
max_run_seconds_reached, exited/0/OOMKilled=false. session_synchronized=false
kapanışta beklenir. docker stats anlık örnektir; max_* sayaçlar p99 değildir.

## Kontrollü recovery
Yalnız ayrı test collector'ında, diğer servislerin ağını değiştirmeden:
```bash
TEST_CONTAINER=your-dedicated-recovery-test
(
set -eu
test_network=$(docker inspect "$TEST_CONTAINER" --format '{{range $name, $config := .NetworkSettings.Networks}}{{println $name}}{{end}}')
[[ -n "$test_network" && "$test_network" != *$'\n'* ]]
trap 'docker network connect "$test_network" "$TEST_CONTAINER" >/dev/null 2>&1 || true' EXIT
docker network disconnect "$test_network" "$TEST_CONTAINER"
sleep 5
docker network connect "$test_network" "$TEST_CONTAINER"
trap - EXIT
)
docker logs --tail=10 "$TEST_CONTAINER"
docker exec "$TEST_CONTAINER" cat /data/status/collector_status.json
```
Beklenen: retry/backoff, yeni session/book, tekrar RUNNING; stabil ilerleme sonrası
failure-budget reset. Tüm timeout'ların tek kesintiden geldiğini varsayma.

## Ham veri ve scoped audit
Collector durduktan sonra:
```bash
docker compose -p "$PROJECT" run --rm --no-deps collector python -c 'from pathlib import Path; files=sorted(Path("/data/raw").glob("*.jsonl")); print("files=",len(files)); [print(f.name, f.stat().st_size) for f in files]'
SESSION_ID=your-completed-session-id
SNAPSHOTS=1
DEPTH_COUNT=your-expected-depth-count
TRADE_COUNT=your-expected-trade-count
docker compose -p "$PROJECT" run --rm --no-deps collector python -u -m signal_desk.tools.audit_raw --raw-dir /data/raw --session-id "$SESSION_ID" --expected-snapshots "$SNAPSHOTS" --expected-depth "$DEPTH_COUNT" --expected-trades "$TRADE_COUNT"
echo "AUDIT_EXIT_CODE=$?"
```
Beklenen sayılar ilgili tamamlanmış koşunun çıktısından alınır. Dosyalar birden
fazla denemeyi içerir; inventory toplamını bir testin hacmi veya günlük hacim sayma.
SHA-256 yerel dosya fingerprint'idir. Audit başarısı replay parity değildir.
Mevcut eski replay runner'ı tüm JSONL'yi listeye yükler; büyük dosyaya kontrolsüz uygulama.

## Sürüm güncelleme ve durdurma
Yalnız incelenmiş ref/branch için:
```bash
git -c safe.directory="$PWD" fetch origin
git -c safe.directory="$PWD" switch main
git -c safe.directory="$PWD" pull --ff-only origin main
git -c safe.directory="$PWD" log -1 --oneline
git -c safe.directory="$PWD" status --short
```
Durdurma yalnız bu Compose projesini hedefler, volume'u korur:
```bash
docker compose -p "$PROJECT" stop
```
Eski backup/restore/migration script'leri skeleton'dır; temiz host restore kabulü
yoktur. Veri silme, prune, down -v ve remove-orphans normal kurulum adımı değildir.

## Doğrulanan checkpoint'ler (27 Ekim 2026)
- 16 → 24 → 49 → 53 test aşamaları; audit adayıyla 67 test target host'ta geçti.
- Snapshot, 25/1.000 kayıt, 60/300s ve 1h collector koşuları doğrulandı.
- 1h: 186.898 kayıt, gap/reconnect=0, exited/0/no OOM.
- Recovery testinde iki reconnect ve yeni sağlıklı oturuma dönüş görüldü.
- 1h session audit: 1 snapshot + 35.887 depth + 151.010 trade; hata yok, exit 0.
- Installer eklemeleri yerel sahte-Docker orchestration testlerine sahiptir;
  gerçek installer ve ayrı temiz sunucu testi henüz pending.

