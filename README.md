# Selvese EUR Satış Pusulası

EUR geliri olan işletmelerin EUR/USD bazlı günlük satış zamanlamasını
ve miktarını kurallı şekilde yönetmek için geliştirilmiş modüler bir
karar destek sistemidir.

## Mimari

```text
selvese/
├── app.py                 # Streamlit dashboard
├── run.py                 # Streamlit entry point
├── requirements.txt
├── logger.py              # Karar günlüğü ve treasury metrikleri
├── logging_config.py
├── freshness.py
├── core/                  # Veri ve hesaplama katmanı
│   ├── data_sources.py
│   ├── indicators.py
│   ├── scoring.py
│   └── validators.py
├── engine/                # Orkestrasyon katmanı
├── planner/               # Satış planı katmanı
├── backtest/              # Tarihsel doğrulama
├── forecast/              # Özellik ve tahmin yardımcıları
├── regime/                # Rejim deneyleri / adaptif ağırlıklar
└── tests/                 # Smoke test
```

## Katman Kuralları

| Katman   | UI Import? | Engine Import? | Dış API? |
|----------|-----------|----------------|----------|
| core/    | HAYIR     | HAYIR          | EVET     |
| engine/  | HAYIR     | core, planner, backtest | HAYIR |
| planner/ | HAYIR     | HAYIR          | HAYIR    |
| backtest/| HAYIR     | core (indicators) | HAYIR |
| app.py   | EVET      | engine, logger | HAYIR   |

**Temel kural:** `core/`, `engine/`, `planner/`, `backtest/`
katmanları hiçbir zaman `streamlit` import etmez. Bu sayede:

- Engine bağımsız test edilebilir
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
