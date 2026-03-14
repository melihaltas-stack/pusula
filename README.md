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
- `TWELVEDATA_API_KEY` tanımlanırsa sistem `EUR/USD`, `DXY`, `VIX`, `US2Y`, `US10Y`
  verilerinde önce Twelve Data'yı dener; başarısız olursa mevcut fallback zincirine düşer.

## Önerilen Otomatik Veri Omurgası

Bu proje için en mantıklı yapı:

1. Birincil kaynak: `Twelve Data`
2. İkincil kaynaklar: `ECB`, `US Treasury`, `FRED`, `CBOE`
3. Operasyonel emniyet: uygulama içi `Hızlı Mod` / manuel override

Opsiyonel ortam değişkenleri:

```bash
TWELVEDATA_API_KEY=...
TWELVEDATA_EURUSD_SYMBOL=EUR/USD
TWELVEDATA_DXY_SYMBOL=DXY
TWELVEDATA_VIX_SYMBOL=VIX
TWELVEDATA_US2Y_SYMBOL=US2Y
TWELVEDATA_US10Y_SYMBOL=US10Y
```

Not:
- Sembol adları veri planına göre değişebilir. Gerekirse bu ortam değişkenleriyle
  sembolleri değiştirebilirsin.
