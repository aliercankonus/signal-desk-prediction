# Signal Desk Prediction

Binance BTCUSDT spot için paper-only collector, araştırma, replay ve karar sistemi.
Gerçek emir kapalıdır. Çalışan collector, kârlı strateji veya tamamlanmış paper ledger
anlamına gelmez.

## Tek işlemle mevcut kurulum
Repo içinden:
```bash
bash scripts/install.sh
```
Config ve data volume korunur; script build, config/schema, tüm testler, kısa public
Binance smoke ve API health kontrolünü sırayla yapar. Yalnız API başlar, collector
varsayılanı idle kalır. Mevcut Docker engine yeniden kurulmaz.

## Yeni sunucuda tek işlemle kurulum

Ubuntu 22.04/24.04 sunucusunun ana terminalinde (root/sudo):

```bash
sudo bash -c 'set -eu; command -v curl >/dev/null || { apt-get update; apt-get install -y ca-certificates curl; }; f=$(mktemp); trap "rm -f \"$f\"" EXIT; curl -fsSL https://raw.githubusercontent.com/aliercankonus/signal-desk-prediction/main/scripts/install.sh -o "$f"; bash "$f" --install-docker'
```

Varsayılan checkout `/opt/signal-desk-prediction`, API adresi
`127.0.0.1:8080` olur. Komutu VPS host terminalinden çalıştır.
Geçmiş veri/model taşıma ve devamlı collector başlatma ayrı adımlardır.

Yeni Ubuntu sunucusu ve tam parametreler: [INSTALLATION.md](INSTALLATION.md).
Tüm manuel kurulum/teşhis/test komutları: [docs/COMMANDS.md](docs/COMMANDS.md).
Dağıtım giriş noktası: [VPS_DEPLOYMENT.md](VPS_DEPLOYMENT.md).

## Kurulum komutları ve kayıtlar

| İhtiyaç | Repository'deki kaynak |
| --- | --- |
| Yeni/mevcut sunucu kurulumu, parametreler ve hata davranışı | [INSTALLATION.md](INSTALLATION.md) |
| Docker/host teşhisi, config, build, test, API, snapshot ve stream komutları | [docs/COMMANDS.md](docs/COMMANDS.md) |
| Kaynak, recovery, bir saatlik soak ve raw-session audit komutları | [docs/COMMANDS.md](docs/COMMANDS.md) |
| Güncel teknik durum ve kalan kabul adımları | [PROJECT_STATE.md](PROJECT_STATE.md) |

Her installer koşusu `runtime/install/run.*/` altında `deploy.log`, commit/config
hash'i ve başarılıysa `manifest.json` üretir. Sonraki kurulum aynı script'ten
yürütülür ve kullanılan sürümler kaydedilir. Manuel komut kataloğunda sunucu yolu,
hostname ve session ID gibi değerler parametre olarak verilir.

## Kanıt ve güncel sınır
- Collector snapshot, 25/1.000-record smoke, süreli continuous ve recovery testleri görüldü.
- Bir saatlik koşu: 186.898 kayıt, gap/reconnect=0, normal exit ve OOM yok.
- Scoped raw audit: aynı 186.898 kayıt, hata yok; parity veya exchange completeness değil.
- Installer testleri sahte Docker ile orchestration testleridir; gerçek installer
  ve bağımsız temiz host acceptance henüz pending.
- 24h soak, p99 latency, bounded merged replay parity, veri restore, tam ledger/PnL,
  ekonomik model kabulü tamamlanmadı. Time Machine yalnız feature sözleşmesi.

Installer yerel komut logu ve sürüm/hash manifest'i üretir. Kurulum geçmişi için
sunucuya özel kimlik/özel yollar public source'a yazılmaz. PROJECT_STATE.md güncel
teknik özet; decision_log araştırılmış karar; runtime/install yerel kurulum kanıtıdır.
