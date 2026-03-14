# Pusula Kurumsal FX Roadmap

Bu belge "JP Morgan seviyesinde model" fantezisi ile "biz zaten geliştirdik" rehavetinin arasındaki gerçekçi yolu tanımlar.

Amaç:
- Banka modellerini kopyalamak değil
- Kurumsal FX desk'lerin kullandığı factor ailelerine yaklaşmak
- Açıklanabilir, ölçülebilir ve maliyet-fayda dengesi olan bir sistem kurmak

## Net Gerçeklik

Pusula bugün:
- açıklanabilir
- modüler
- pratik
- hızlı iterasyon yapılabilir

Pusula bugün henüz:
- institutional-grade veri yoğunluğunda değil
- options / positioning / macro surprise / cross-asset akışı açısından zayıf
- ciddi out-of-sample model selection disiplinine tam oturmamış
- cost-aware execution ve transaction-cost modelling tarafında eksik

Asıl hedef:
- "bankanın gizli modelini bulmak" değil
- açık ve erişilebilir veriyle aynı problem sınıfını daha iyi çözmek

## Mevcut Açıklar

Kod tabanına göre ana eksikler:

1. Veri kapsamı dar
- Şu an omurga ağırlıklı olarak spot, DXY, VIX, US/DE rates ve makro takvimden besleniyor.
- COT positioning, options implied vol/skew, macro surprise, FRA/OIS, basis, real yield, equity-credit liquidity sinyalleri yok.

2. Rejim tanımı basit
- Trend rejimi temelde moving-average tabanlı.
- Kurumsal modellerde rejim genelde volatility, carry, policy divergence, risk aversion ve positioning ile birlikte ele alınır.

3. Makro katman haber takvimi düzeyinde
- "yakın veri var mı?" mantığı var.
- "veri beklentiye göre ne kadar şaşırttı?" mantığı yok.

4. Olasılık kalibrasyonu erken aşamada
- Forecast ve hybrid eklendi ama calibration / Brier / reliability curve / probability bucketing henüz yok.

5. Execution motoru piyasa mikro yapısından bağımsız
- Gün içi likidite, fixing saatleri, event window ve spread genişlemesi sınırlı ele alınıyor.

## Hedef Mimarisi

Kurumsal seviyeye yaklaşan yapı 5 katmandan oluşmalı:

1. Data layer
- Spot, rates, vol, positioning, macro surprise, cross-asset, options

2. Feature layer
- carry, value, momentum, risk, policy divergence, positioning squeeze, event shock

3. Regime layer
- trend, range, panic, policy divergence, squeeze, post-event normalization

4. Forecast layer
- horizon-specific probability models
- calibrated ensemble

5. Execution layer
- event-aware sell scheduling
- liquidity windows
- confidence-aware size control

## Faz 1: Açık Veriyle Hemen Yapılabilir

Maliyet: düşük
Zaman: 1-3 hafta
Etki: yüksek

### 1. COT Positioning ekle

Kaynak:
- CFTC Commitments of Traders

Eklenebilecek feature'lar:
- EUR net positioning z-score
- USD broad positioning proxy
- crowded long / crowded short bayrakları

Neden önemli:
- FX'te positioning sıkışmaları fiyatın yönünden çok hızını belirler.

Kod etkisi:
- `core/data_sources.py`
- yeni: `forecast/features.py`
- yeni skor katkısı: `core/scoring.py`

Başarı ölçütü:
- 5G ve 10G horizon accuracy artışı
- event sonrası ters hareketlerin daha iyi yakalanması

### 2. Macro surprise katmanı ekle

Kaynak:
- açık takvim + actual / previous / consensus bulunabilen kaynaklar
- ilk aşamada consensus bulunamazsa "actual vs previous" proxy

Feature'lar:
- US inflation surprise
- NFP surprise
- ECB/Fed tone proxy
- son 20 iş günde kümülatif USD-surprise skoru

Neden önemli:
- Takvimin kendisi değil, beklenti sapması fiyatı taşır.

Kod etkisi:
- `core/data_sources.py`
- yeni helper modülü: `core/macro_surprise.py`
- `forecast/features.py`

Başarı ölçütü:
- veri günü çevresindeki yanlış agresif satış sayısında düşüş

### 3. Real yield / policy divergence güçlendir

Kaynak:
- FRED
- ECB / Bundesbank

Feature'lar:
- US-DE 2Y nominal spread
- US-DE 10Y nominal spread
- mümkünse real yield proxy
- spread momentum

Neden önemli:
- EURUSD için orta vadede rate differential tek başına seviye değil, değişim hızıyla da çalışır.

Kod etkisi:
- `core/data_sources.py`
- `forecast/features.py`
- `core/scoring.py`

### 4. Cross-asset risk proxies ekle

Kaynak:
- Yahoo / Stooq / FRED / alternatif ücretsiz kaynaklar

Feature'lar:
- S&P 500 momentum
- EuroStoxx relative performance
- credit stress proxy
- gold / oil / copper risk-growth ayrımı

Neden önemli:
- EURUSD çoğu dönemde salt FX değil, risk complex içinde fiyatlanır.

### 5. Probability calibration raporu ekle

Gerekli metrikler:
- Brier score
- calibration buckets
- reliability table
- high-confidence false positive oranı

Kod etkisi:
- yeni: `forecast/calibration.py`
- `forecast/evaluation.py`

Bu fazın kabul kriteri:
- Hybrid model test doğruluğu tek başına forecast modelinden daha iyi olmalı
- calibration hatası raporlanmalı
- raporlar ekranda ve debug çıktısında görünmeli

## Faz 2: Ücretli Veriyle Ciddi Sıçrama

Maliyet: orta
Zaman: 2-5 hafta
Etki: çok yüksek

### 1. Options implied vol ve risk reversal

Kaynak örnekleri:
- Refinitiv
- Bloomberg
- dxFeed
- institutional FX options feeds

Feature'lar:
- 1W / 1M implied vol
- risk reversal
- butterfly
- vol term structure inversion

Neden önemli:
- Spot yönünden önce opsiyon piyasası çoğu zaman stresin yönünü fiyatlar.

Etkisi:
- event risk öncesi yanlış güveni azaltır
- "bekle" kararlarını daha akıllı yapar

### 2. OIS / swap / forward-implied policy path

Feature'lar:
- ECB vs Fed path divergence
- 1y1y / 2y1y farkları
- terminal rate repricing

Neden önemli:
- nominal tahvil seviyesinden daha zengin bir policy signal üretir.

### 3. Econoday / Bloomberg tarzı gerçek consensus-surprise akışı

İlk açık veri yaklaşımından çok daha güçlüdür.

Feature'lar:
- release bazlı standardized surprise
- rolling USD surprise diffusion index
- EUR surprise diffusion index

### 4. Better-quality intraday data

Gerekçe:
- execution motorunu saat bazlı iyileştirmek için 1H/4H yetmez.

İstenilenler:
- 5m / 15m spot
- event çevresi barlar
- fixing pencereleri

Bu fazın kabul kriteri:
- short-term horizon için yanlış pozitif oranı düşmeli
- event günlerinde minimum satış moduna geçiş daha doğru olmalı

## Faz 3: Gerçek Institutional-Grade Ama Maliyetli

Maliyet: yüksek
Zaman: 1-3 ay
Etki: yüksek ama pahalı

### 1. Bloomberg / Refinitiv / Macrobond veri omurgası

Gelen fark:
- daha temiz rates
- options surface
- surprise data
- positioning ve cross-asset entegrasyonu

### 2. Transaction cost + liquidity model

Feature'lar:
- spread regime
- time-of-day liquidity
- event blackout windows
- London fix / NY cut etkisi

### 3. Ensemble model selection

Model aileleri:
- nearest-neighbor
- regularized logistic
- gradient boosting
- regime-specific submodels

Ama kural:
- Açıklanabilirlik kaybolmadan
- calibration bozulmadan
- overfit gap raporlanarak

### 4. Monitoring ve drift

İzlenecekler:
- feature drift
- regime mix değişimi
- probability calibration drift
- source degradation

## Pusula İçin En Mantıklı Yol

Aşağıdaki sırayla gitmek en verimli:

1. COT positioning
2. macro surprise proxy
3. spread momentum + cross-asset risk features
4. probability calibration
5. options data
6. intraday execution intelligence

Sebep:
- ilk 4 adım açık veriyle mümkün
- son 2 adım maliyetli ama gerçekten fark yaratır

## Uygulama Backlog'u

### Sprint A

Hedef:
- veri zenginliğini artırmak

Yapılacaklar:
- `core/data_sources.py` içine COT çekici
- `forecast/features.py` içine positioning ve spread momentum feature'ları
- `core/scoring.py` içine positioning alt skoru
- `forecast/evaluation.py` içine calibration metrikleri

### Sprint B

Hedef:
- makro katmanı takvimden surprise motoruna taşımak

Yapılacaklar:
- `core/macro_surprise.py`
- `core/data_sources.py` entegrasyonu
- release sonrası 1G / 3G etki analizi

### Sprint C

Hedef:
- execution intelligence

Yapılacaklar:
- event window blackout
- fixing saatleri
- likidite penceresi
- intraday aggressiveness factor

## Ölçmeden İnanmayacağız

Her yeni feature veya model için zorunlu metrikler:

- out-of-sample accuracy
- Brier score
- calibration drift
- false positive rate
- event-day error rate
- decision stability

Bir bileşen şu durumda sistemde kalmalı:
- tek başına mantıklı görünüyorsa değil
- test setinde hibrit modele katkı yapıyorsa

## Anti-Bullshit Kuralları

Bu projede aşağıdakiler yasak kabul edilmeli:

1. Sadece grafikte mantıklı durduğu için feature eklemek
2. Backtest sonucu seçip sonra hikaye yazmak
3. Canlıda erişemeyeceğimiz veriyi testte kullanmak
4. Calibration bozukken olasılık sunmak
5. "Banka da böyle yapıyordur" diye varsaymak

## Bir Sonraki Teknik İş

En yüksek getirili ilk teknik iş:

1. COT positioning veri akışını eklemek
2. positioning feature'larını forecast ve scoring'e bağlamak
3. calibration metriklerini ekrana koymak

Bu üçü tamamlandığında Pusula:
- daha az naif olur
- daha kurumsal bir factor setine yaklaşır
- gerçekten gelişip gelişmediğini daha dürüst ölçer
