# 08 — Paper Fill Model

Paper-fill modu üçe ayrılır. Kabul kapılarında **conservative** ana moddur.

## Modlar

| Mod | Kullanım | Varsayım |
|---|---|---|
| Conservative | Kabul ve risk | Şüphede kötü senaryo |
| Neutral | Günlük normal rapor | Orta varsayım |
| Optimistic | Duyarlılık analizi | En iyiye yakın ama ayrı etiketli |

## Ortak ilkeler

- Stop tetiklenmesi gerçek dolum garantisi değildir.
- Same interval içinde stop ve hedef ikisi de görünürse conservative modda stop-first.
- Limit emrin dolması iyi işlem yaptığımızı kanıtlamaz; markout ölç.
- Kısmi dolum miktarı korunur.
- Cancel isteği cancel onayı değildir.
- Restart sonrası paper ledger borsadan değil kendi kalıcı kayıtlarından reconcile edilir.
- Futures/funding/liq varsayımları V0 spot paper için kullanılmaz.

## Markout ölçümleri

Her paper fill için:
- fill_time
- fill_price
- midpoint at +1s, +5s, +30s, +60s
- spread at fill
- fee estimate
- slippage estimate
- adverse selection flag

Markout tanı metriğidir; net kâr veya model kabulü değildir.
