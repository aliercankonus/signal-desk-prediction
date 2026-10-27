# 15 — Research and Decision Policy

## Kural

Bundan sonra skill’e eklenecek teknik kararlar araştırmadan eklenmez. Karar küçük bile olsa kaynak, gerekçe ve test etkisi yazılır.

## Decision log formatı

Her karar için `decision_log/YYYY-MM-DD-<slug>.md` oluştur:

```markdown
# Decision: <short title>

## Status
proposed | accepted | rejected | superseded

## Context
Hangi sorun çözülecek?

## Sources checked
- Kaynak adı + URL + tarih
- Resmî belge/paper/üretici dokümanı tercih edilir.

## Decision
Ne seçildi?

## Alternatives
Neler reddedildi?

## Risks
Yanlışsa ne olur?

## Tests added
Hangi acceptance veya unit test eklendi?

## Rollback
Nasıl geri alınır?
```

## Kaynak önceliği

1. Resmî exchange / Docker / library dokümanı.
2. Akademik paper veya üretici teknik blogu.
3. Açık kaynak kod + testler.
4. Blog/yorum yalnız yardımcı kaynak.

## Özel kural

Kârlılık veya başarı şansı iddiası yalnız kendi forward paper test sonuçlarıyla yapılır. Dış firma kârı veya akademik accuracy doğrudan bizim beklenen getirimiz sayılmaz.
