# VPS deployment runbook

Canonical kurulum: [INSTALLATION.md](INSTALLATION.md).
Tam manuel komut kataloğu: [docs/COMMANDS.md](docs/COMMANDS.md).

## Mevcut checkout
```bash
bash scripts/install.sh
```
Repo dışında script'in mutlak yolunu kullanabilir veya --dir ile checkout'u seçebilirsin.
Çalışan Docker host'unda çalıştır; agent container'ının host'a eriştiğini varsayma.
Mevcut config/.env ve volume korunur. Script otomatik git reset, prune veya data
silme yapmaz. Güncelleme için açık --ref seç; Git çakışmaları zorla çözülmez.

## Kapsam
Build → config/schema → pytest → REST snapshot → kısa WS → API --wait/health →
yerel manifest. Smoke için --no-smoke verilirse veri bağlantısı kabul edilmiş sayılmaz.
Yalnız API başlatılır; maintenance/collector varsayılanı otomatik açılmaz.
Yeni kurulumda API loopback'e bağlanır; açık dış bind bilinçli --bind seçimi ister.

## Kabul ve kayıt
DEPLOY_OK ve runtime/install/run.*/manifest.json yalnız aşamalar geçince oluşur.
Önceki image kimliği ve komut logu yerelde korunur. Kurulum başarısı 24h collector,
paper trading, p99, veri restore veya strateji başarısı değildir.
Mevcut backup/restore/migration script'leri skeleton olarak işaretlidir; doğrulanmış
restore veya disk genişletmesi yaptığı varsayılmaz. Veri migration'ı ayrı kabul ister.
