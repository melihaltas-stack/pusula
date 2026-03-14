# Deploy Checklist

Bu belge Pusula'yı kontrollü şekilde yayına almak için kısa operasyon notudur.

## 1. Kod Güncelle

```bash
cd /Users/melihaltas/Desktop/Pusula
git pull origin main
```

## 2. Sanal Ortam ve Bağımlılıklar

```bash
cd /Users/melihaltas/Desktop/Pusula
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

Not:
- Mevcut bir `.venv` varsa yeniden oluşturmak zorunlu değil.

## 3. Ortam Değişkenleri

Opsiyonel ama önerilen:

```bash
export TWELVEDATA_API_KEY=...
export FMP_API_KEY=...
```

İsteğe bağlı sembol override'ları:

```bash
export TWELVEDATA_EURUSD_SYMBOL=EUR/USD
export TWELVEDATA_DXY_SYMBOL=DXY
export TWELVEDATA_VIX_SYMBOL=VIX
export TWELVEDATA_US2Y_SYMBOL=US2Y
export TWELVEDATA_US10Y_SYMBOL=US10Y
```

## 4. Yazma İzinleri

Deploy ortamında şu yollar yazılabilir olmalı:
- çalışma dizininde `decision_log.csv`
- `/tmp/selvese-pusula-detail-report.pkl`
- `/tmp/selvese-pusula-cache/`

## 5. Pre-Deploy Kontrol

```bash
cd /Users/melihaltas/Desktop/Pusula
./scripts/deploy_check.sh
```

Beklenen:
- Python derleme kontrolü geçmeli
- `tests/smoke_check.py` çok uzun sürerse veri sağlayıcı problemi olabilir

## 6. Uygulamayı Başlat

```bash
cd /Users/melihaltas/Desktop/Pusula
source .venv/bin/activate
python3 -m streamlit run app.py --server.port 8501
```

Alternatif:

```bash
cd /Users/melihaltas/Desktop/Pusula
source .venv/bin/activate
python3 run.py
```

## 7. Restart Kuralı

Eski kod görünüyorsa ilk şüphe çalışan eski Streamlit sürecidir.

Yapılacak:
- çalışan Streamlit sürecini durdur
- yeniden başlat

## 8. İlk Yayın Sonrası Kontrol

Uygulama açıldıktan sonra şunları kontrol et:
- üst uyarı metni görünüyor mu
- hızlı mod açılıyor mu
- planlı detaylı cache yükleniyor mu
- log butonu `decision_log.csv` yazabiliyor mu
- veri kaynakları panelinde `N/A` patlaması var mı

## 9. Operasyon Notu

Şu anda en büyük deploy riski kod değil, dış veri sağlayıcılarıdır:
- `yfinance` rate limit
- FRED / ECB / CFTC gecikmeleri
- cache fallback davranışı

Bu yüzden ilk yayın "soft launch" olarak izlenmeli.
