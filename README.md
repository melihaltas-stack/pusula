# Selvese EUR Satış Pusulası

EUR geliri olan işletmelerin EUR/USD bazlı günlük satış zamanlamasını
ve miktarını kurallı şekilde yönetmek için geliştirilmiş modüler bir
karar destek sistemidir.

## Mimari

```
selvese/
├── core/                  # Veri ve hesaplama katmanı (UI bağımsız)
│   ├── data_sources.py    # Canlı piyasa verisi (Yahoo, FRED, ECB, FMP)
│   ├── indicators.py      # Teknik göstergeler (RSI, MACD, ATR, MA)
│   └── scoring.py         # Alt skor hesaplama (DXY, Faiz, Risk, vb.)
│
├── engine/                # Orkestrasyon katmanı
│   └── engine.py          # EDE hesaplama, karar sınıflandırma, rapor
│
├── planner/               # Satış planı katmanı
│   └── planner.py         # Birim hesaplama, makro fren, trend ayarı
│
├── backtest/              # Tarihsel doğrulama
│   └── backtest.py        # Olasılık motoru, benzer koşul analizi
│
├── storage/               # Veri saklama
│   └── logger.py          # Karar günlüğü, treasury metrikleri
│
├── ui/                    # Görsel katman (sadece Streamlit)
│   └── app.py             # Dashboard arayüzü
│
├── api/                   # REST API (gelecek faz)
├── tests/                 # Test altyapısı
├── run.py                 # Streamlit entry point
└── requirements.txt
```

## Katman Kuralları

| Katman   | UI Import? | Engine Import? | Dış API? |
|----------|-----------|----------------|----------|
| core/    | HAYIR     | HAYIR          | EVET     |
| engine/  | HAYIR     | core, planner, backtest | HAYIR |
| planner/ | HAYIR     | HAYIR          | HAYIR    |
| backtest/| HAYIR     | core (indicators) | HAYIR |
| storage/ | HAYIR     | HAYIR          | HAYIR    |
| ui/      | EVET      | engine, storage | HAYIR   |
| api/     | HAYIR     | engine, storage | HAYIR   |

**Temel kural:** `core/`, `engine/`, `planner/`, `backtest/`, `storage/`
katmanları hiçbir zaman `streamlit` import etmez. Bu sayede:

- Engine bağımsız test edilebilir
- API katmanı aynı core'u kullanabilir
- CI/CD pipeline'da Streamlit kurulumu gerekmez

## Çalıştırma

```bash
cd /Users/melihaltas/Desktop/Pusula
python3 -m streamlit run app.py
```

## Smoke Test (UI olmadan)

```bash
cd /Users/melihaltas/Desktop/Pusula
python3 tests/smoke_check.py
```

Notlar:
- `DXY` canlı veri gelmezse sistem `PROXY:EURUSD_INVERSE` kaynağına düşebilir.
- `EUR/USD 4H` veri gelmezse `1H -> 4H` birleştirme kullanılır.
