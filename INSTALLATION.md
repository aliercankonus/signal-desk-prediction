# Tek işlemle kurulum

## Mevcut checkout
VPS'nin ana terminalinde, repo içinden:
```bash
bash scripts/install.sh
```
Başka dizindeyken:
```bash
bash /path/to/signal-desk-prediction/scripts/install.sh
```
Mevcut checkout kullanılır; yeniden clone veya otomatik branch değiştirme yapılmaz.
Başka ref'e açık güncelleme:
```bash
bash scripts/install.sh --ref COMMIT_SHA
```
Ref güncellemesi kod değişiklikleri varsa durur. Yerel config dosyası checkout ile
çakışırsa Git durur; config sıfırlanmaz ve force/reset kullanılmaz.

## Yeni Ubuntu sunucusu
Desteklenen otomatik Docker kurulumu: Ubuntu 22.04/24.04, root/sudo, systemd host.
Docker mevcutsa çalışan engine'e yeniden kurulum/servis restart'ı yapılmaz.
Aşağıdaki tek shell işlemi, önce dosyanın tamamen indirilmesini bekler:
```bash
sudo bash -c 'set -eu; command -v curl >/dev/null || { apt-get update; apt-get install -y ca-certificates curl; }; f=$(mktemp); trap "rm -f \"$f\"" EXIT; curl -fsSL https://raw.githubusercontent.com/aliercankonus/signal-desk-prediction/main/scripts/install.sh -o "$f"; bash "$f" --install-docker'
```
Varsayılan hedef /opt/signal-desk-prediction. Özel hedef/ref için indirilen script'e
`--dir /chosen/path --ref COMMIT_SHA` ver. Script repo içindeyse mevcut yolunu bulur.
Tekrarlanabilir kod sürümü için branch yerine tam commit SHA tercih et.
Docker/OS paketleri ve temel image tag'i bit düzeyinde sabitlenmiş değildir;
gerçek git/image/config/Python/dependency sürümleri yerel manifest'e kaydedilir.

## Sıra ve başarı ölçütü
1. Host/container ve opsiyonel expected-host kontrolü.
2. Docker daemon, Compose, Buildx ve --wait desteği; Git ve başlangıç kapasitesi.
3. Mevcut repo kimliğini doğrula veya boş hedefe clone et.
4. Config/.env yoksa oluştur; aktif dosyaları koru. Taze clone'un versioned config
   örneğini güncel config.example.yaml ile başlat.
5. Compose doğrula, api/collector image build et.
6. Config/schema doğrula ve tüm pytest setini container içinde çalıştır.
7. Varsayılan olarak public Binance snapshot + 25-record stream smoke.
8. Yalnız API'yi --wait ile başlat; paper/disabled execution/BTCUSDT health'ini doğrula.
9. Yerel manifest ve komut günlüğü yaz; DEPLOY_OK ver.

Bir adım başarısızsa sonrakine geçmez. Çalışan collector varsa deployment başlamaz.
Installer devamlı collector/maintenance açmaz; API ve kısa test kurulumu tamamlanır.
1h/24h soak, data/replay parity, model/ledger/PnL veya Time Machine kurulmuş sayılmaz.
Kısa smoke gerektirmeyen kapalı ağ testinde `--no-smoke` kullanılabilir; manifest
bunu açıkça smoke_skipped olarak kaydeder, live feed kabulü üretmez.

## Config, port ve proje
Yeni kurulumda API varsayılanı 127.0.0.1:8080'dir. Dış erişim gerekiyorsa bilinçli
olarak --bind 0.0.0.0 seç; TLS/auth yapılandırması bu installer'ın kapsamı değildir.
```bash
bash scripts/install.sh --project signal-desk-prediction --port 8080 --bind 127.0.0.1
bash scripts/install.sh --expected-host EXPECTED_HOSTNAME
bash scripts/install.sh --plan
```
Mevcut .env'deki proje/port/bind farklıysa sessizce değiştirilmez; eşleşen flag ver
veya dosyayı bilinçli düzenle. Diğer .env satırları ve config/config.yaml korunur.
COMPOSE_PROJECT_NAME değişikliği başka Docker volume namespace'i seçebilir;
aynı veriyi kullanmak için önceki proje adını koru.

Minimum bootstrap kontrolü 10 GiB boş alan ve en az 1.5 GiB görünür MemTotal'dir;
bu 100GB/2GB profilinin veya istenen retention süresinin kapasite garantisi değildir.
Gerçek veri path'indeki quota/disk HALT kontrolleri collector'a aittir.

## Kaydedilen kurulum kanıtı
`runtime/install/run.*/` altında:
- deploy.log: uygulanan komutlar, stdout/stderr, aşama ve hata.
- git-commit.txt ve config.sha256.
- previous-api-image.txt: önceki API varsa image ID.
- manifest.json: yalnız tüm aşamalar geçince atomik finalize edilir; çözülmüş image
  ID'leri, dependency sürümleri, config hash'i, Compose proje/volume ve smoke durumu.

Bu dosyalar yerel operasyon kaydıdır; .env içeriği basılmaz ve runtime/.env/aktif
config Docker build context'inden dışlanır. Public repo'ya otomatik upload yapılmaz.
Mevcut Docker data volume'u korunur; down -v, prune, reset ve remove-orphans kullanılmaz.
Başarısız API health sonrası otomatik image rollback yapılmaz; log ve önceki image
ID korunur. Önceki image'a dönmek veya data restore ayrı, incelenecek işlemlerdir.

## Sınırlar
- Hermes/başka agent container'ından host Docker erişimi varmış gibi davranma.
- Otomatik Docker setup mevcut/conflicting container runtime'ı kaldırmaz.
- Çalışan Docker'da eksik Compose/Buildx varsa engine'i değiştirmek yerine durur.
- Root clone/install ile başka kullanıcıların ownership'i topluca değiştirilmez;
  Git safe.directory istisnası yalnız tek komuta uygulanır.
- Backup/restore ve 200GB taşıma eski skeleton script'leri doğrulanmış veri taşıma
  yöntemi değildir. Tek komut kurulum, geçmiş data/model geri yükleme kabulü değildir.
- Shell orchestration sahte Docker ile yerel testlidir; gerçek target installer
  koşusu ve bağımsız temiz sunucu kurulumu ayrıca doğrulanmalıdır.

Tüm manuel kurulum/teşhis/doğrulama komutları için [komut kataloğu](docs/COMMANDS.md).

