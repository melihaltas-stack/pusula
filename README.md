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
pip install -r requirements.txt
cd selvese
python -m streamlit run ui/app.py
```

## Smoke Test (UI olmadan)

```python
# Engine'in UI bağımlılığı olmadan çalıştığını doğrula
from engine.engine import calculate_ede, classify_decision, build_weights
from core.indicators import rsi, macd, sma
from planner.planner import build_sale_plan
from backtest.backtest import build_probability_summary

print("Tüm katmanlar UI bağımsız import edildi.")
```
