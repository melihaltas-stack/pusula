import streamlit as st
import plotly.graph_objects as go

from logging_config import setup_logging
setup_logging()

from engine import run_engine, build_report_text
from logger import log_daily_decision, read_decision_log, build_treasury_metrics


st.set_page_config(
    page_title="Selvese EUR Satış Pusulası",
    page_icon="🧭",
    layout="wide"
)

st.markdown("""
<style>
    .main {
        background-color: #0b1020;
    }

    .block-container {
        padding-top: 1.5rem;
        padding-bottom: 2rem;
        max-width: 1500px;
    }

    h1, h2, h3 {
        color: #f3f6fb;
        letter-spacing: -0.02em;
    }

    .panel-card {
        background: #111827;
        border: 1px solid #1f2937;
        border-radius: 16px;
        padding: 16px 18px;
        margin-bottom: 12px;
        box-shadow: 0 8px 20px rgba(0, 0, 0, 0.18);
    }

    .metric-card {
        background: #111827;
        border: 1px solid #1f2937;
        border-radius: 14px;
        padding: 16px 18px;
        margin: 6px 0;
        min-height: 96px;
    }

    .metric-card.sat {
        border-left: 4px solid #00c389;
    }

    .metric-card.hazirlan {
        border-left: 4px solid #f59e0b;
    }

    .metric-card.bekle {
        border-left: 4px solid #60a5fa;
    }

    .metric-label {
        font-size: 12px;
        color: #93a3b8;
        margin-bottom: 8px;
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }

    .metric-value {
        font-size: 30px;
        font-weight: 700;
        color: #f8fafc;
        line-height: 1.1;
    }

    .metric-sub {
        font-size: 13px;
        color: #9fb0c8;
        margin-top: 8px;
    }

    .plan-box {
        background: linear-gradient(180deg, #172033 0%, #101726 100%);
        border: 1px solid #24324d;
        border-radius: 16px;
        padding: 18px 20px;
        margin-bottom: 14px;
    }

    .plan-title {
        font-size: 14px;
        font-weight: 700;
        color: #8fb4ff;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        margin-bottom: 10px;
    }

    .plan-main {
        font-size: 28px;
        font-weight: 800;
        color: #f8fafc;
        margin-bottom: 8px;
    }

    .plan-text {
        font-size: 15px;
        color: #d4deea;
        line-height: 1.7;
    }

    .risk-box {
        background: rgba(245, 158, 11, 0.10);
        border: 1px solid rgba(245, 158, 11, 0.30);
        border-radius: 14px;
        padding: 14px 16px;
        color: #fde7b0;
        margin-top: 10px;
    }

    .info-box {
        background: rgba(96, 165, 250, 0.10);
        border: 1px solid rgba(96, 165, 250, 0.28);
        border-radius: 14px;
        padding: 14px 16px;
        color: #cfe3ff;
        margin-top: 10px;
    }

    .mini-badge {
        display: inline-block;
        padding: 6px 10px;
        border-radius: 999px;
        font-size: 12px;
        font-weight: 700;
        margin-top: 10px;
    }

    .badge-high {
        background: rgba(0, 195, 137, 0.14);
        color: #00c389;
        border: 1px solid rgba(0, 195, 137, 0.28);
    }

    .badge-mid {
        background: rgba(245, 158, 11, 0.14);
        color: #f59e0b;
        border: 1px solid rgba(245, 158, 11, 0.28);
    }

    .badge-low {
        background: rgba(96, 165, 250, 0.14);
        color: #60a5fa;
        border: 1px solid rgba(96, 165, 250, 0.28);
    }

    .score-row {
        margin: 10px 0 14px 0;
    }

    .score-header {
        display: flex;
        justify-content: space-between;
        margin-bottom: 5px;
        font-size: 14px;
    }

    .score-label {
        color: #d5deea;
        font-weight: 600;
    }

    .score-value {
        font-weight: 700;
    }

    .score-track {
        width: 100%;
        height: 8px;
        background: #1b2433;
        border-radius: 999px;
        overflow: hidden;
    }

    .score-fill {
        height: 8px;
        border-radius: 999px;
    }

    .score-comment {
        color: #8fa0b7;
        font-size: 12px;
        margin-top: 5px;
        line-height: 1.5;
    }

    .stButton > button {
        background: #2c74ff;
        color: white;
        border: none;
        border-radius: 10px;
        padding: 10px 14px;
        font-size: 15px;
        font-weight: 700;
        width: 100%;
    }

    .stButton > button:hover {
        background: #1f5fdb;
        color: white;
    }
</style>
""", unsafe_allow_html=True)


def fmt_num(value, digits=2, suffix=""):
    if value is None:
        return "N/A"
    return f"{value:.{digits}f}{suffix}"


def confidence_badge(label):
    if label == "Yüksek":
        return '<span class="mini-badge badge-high">Veri Güveni: Yüksek</span>'
    if label == "Orta":
        return '<span class="mini-badge badge-mid">Veri Güveni: Orta</span>'
    return '<span class="mini-badge badge-low">Veri Güveni: Düşük</span>'


def score_color(v):
    if v >= 65:
        return "#00c389"
    if v >= 45:
        return "#f59e0b"
    return "#60a5fa"


def barometre(ede, karar, renk):
    renk_map = {
        "sat": "#00c389",
        "hazirlan": "#f59e0b",
        "bekle": "#60a5fa"
    }
    c = renk_map.get(renk, "#60a5fa")

    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=ede,
        number={"font": {"size": 48, "color": c}},
        gauge={
            "axis": {"range": [0, 100], "tickwidth": 1, "tickcolor": "#64748b"},
            "bar": {"color": c, "thickness": 0.24},
            "bgcolor": "#111827",
            "borderwidth": 0,
            "steps": [
                {"range": [0, 40], "color": "#12263a"},
                {"range": [40, 52], "color": "#1f3047"},
                {"range": [52, 65], "color": "#3a2d16"},
                {"range": [65, 100], "color": "#123128"},
            ],
            "threshold": {
                "line": {"color": c, "width": 4},
                "thickness": 0.75,
                "value": ede
            }
        },
        title={"text": f"<b>{karar}</b>", "font": {"size": 24, "color": c}}
    ))

    fig.update_layout(
        paper_bgcolor="#0b1020",
        font={"color": "#f8fafc"},
        height=280,
        margin=dict(t=40, b=10, l=10, r=10)
    )
    return fig


def render_metric_card(label, value, sub="", status_class=""):
    st.markdown(
        f"""
        <div class="metric-card {status_class}">
            <div class="metric-label">{label}</div>
            <div class="metric-value">{value}</div>
            <div class="metric-sub">{sub}</div>
        </div>
        """,
        unsafe_allow_html=True
    )


def render_score_block(name, value, comment):
    c = score_color(value)
    st.markdown(
        f"""
        <div class="score-row">
            <div class="score-header">
                <span class="score-label">{name}</span>
                <span class="score-value" style="color:{c}">{value:.0f}</span>
            </div>
            <div class="score-track">
                <div class="score-fill" style="width:{value}%; background:{c};"></div>
            </div>
            <div class="score-comment">{comment}</div>
        </div>
        """,
        unsafe_allow_html=True
    )


st.title("🧭 Selvese EUR Satış Pusulası")
st.caption("Kurumsal EUR satış yönetimi için açıklanabilir operasyon paneli")

top_left, top_mid, top_right = st.columns([2, 2, 3])

with top_left:
    refresh = st.button("🔄 Analizi Güncelle")

with top_mid:
    save_log = st.button("💾 Bugünkü Kararı Logla")

if "data" not in st.session_state:
    st.session_state.data = None

if refresh:
    with st.spinner("Motor çalışıyor, veriler toplanıyor..."):
        st.session_state.data = run_engine()

if st.session_state.data is None:
    st.info("Önce 'Analizi Güncelle' butonuna bas.")
    st.stop()

d = st.session_state.data

if not isinstance(d, dict):
    st.stop()
    raise SystemExit

if d.get("error"):
    st.error(d["error"])
    st.stop()

if save_log:
    path = log_daily_decision(d)
    st.success(f"Karar günlüğe kaydedildi: {path}")

with top_right:
    st.caption(f"Son güncelleme: {d['zaman']}")

# --- Veri Tazeliği ---
_freshness = d.get("freshness")
if _freshness:
    _fw = _freshness.worst_label
    _color_map = {"fresh": "#00c389", "warning": "#f59e0b", "stale": "#ef4444", "unknown": "#64748b"}
    _fc = _color_map.get(_fw, "#64748b")
    st.markdown(
        f'<div style="background:{_fc}18;border:1px solid {_fc}44;border-radius:10px;'
        f'padding:10px 14px;margin-bottom:10px;font-size:13px;color:{_fc};">'
        f'<b>Veri Tazeliği</b> &nbsp;|&nbsp; {_freshness.summary_text}'
        f'</div>',
        unsafe_allow_html=True
    )
    if _fw == "stale":
        with st.expander("🔴 Bayat veri detayı", expanded=True):
            for k in _freshness.stale_keys():
                s = _freshness.statuses[k]
                st.error(f"{s.badge_emoji} **{k}** — {s.age_text} önce çekildi (limit: {s.ttl_stale}sn)")
    elif _fw == "warning":
        with st.expander("🟡 Tazelik uyarıları"):
            for k in _freshness.warning_keys():
                s = _freshness.statuses[k]
                st.warning(f"{s.badge_emoji} **{k}** — {s.age_text} önce çekildi")

# --- Validation uyarıları ---
_val_flags = d.get("validation_flags", [])
if _val_flags:
    with st.expander(f"⚠️ {len(_val_flags)} veri uyarısı tespit edildi", expanded=False):
        for _f in _val_flags:
            st.warning(_f)

_dxy_source = d.get("dxy_source")
if _dxy_source == "PROXY:EURUSD_INVERSE":
    st.markdown(
        '<div style="background:rgba(245,158,11,0.12);border:1px solid rgba(245,158,11,0.35);'
        'border-radius:10px;padding:10px 14px;margin-bottom:10px;color:#fde7b0;">'
        '<b>DXY Proxy Aktif</b> &nbsp;|&nbsp; DXY canlı veri yerine EUR/USD ters serisinden türetilmiş proxy kullanılıyor.'
        '</div>',
        unsafe_allow_html=True,
    )

# Treasury log ve metrikler
log_df = read_decision_log()
treasury_metrics = build_treasury_metrics(log_df)

# ANA OPERASYON EKRANI
st.markdown("## Ana Operasyon Ekranı")

left, right = st.columns([1.05, 1.95])

with left:
    st.plotly_chart(barometre(d["ede"], d["karar"], d["renk"]), use_container_width=True)

    render_metric_card(
        "EUR/USD Spot",
        fmt_num(d["spot"], 4),
        sub=confidence_badge(d["confidence_label"]),
        status_class=d["renk"]
    )

    render_metric_card(
        "Günlük Satış Planı",
        f"{d['sale_plan']['daily_units']} / 100",
        sub=f"Sabah {d['sale_plan']['morning_units']} • Öğleden sonra {d['sale_plan']['afternoon_units']}",
        status_class=d["renk"]
    )

    render_metric_card(
        "Trend Rejimi",
        d["trend_regime"],
        sub=f"Veri Güven Skoru: {fmt_num(d['data_quality_score'], 0)}/100"
    )

with right:
    st.markdown(
        f"""
        <div class="plan-box">
            <div class="plan-title">Bugünün Satış Planı</div>
            <div class="plan-main">{d['sale_plan']['plan_label']}</div>
            <div class="plan-text">{d['operation_summary']}</div>
        </div>
        """,
        unsafe_allow_html=True
    )

    st.markdown(
        f"""
        <div class="risk-box">
            <b>En Büyük Risk</b><br>
            {d['risk_note']}
        </div>
        """,
        unsafe_allow_html=True
    )

    st.markdown(
        f"""
        <div class="info-box">
            <b>Sonraki Makro Olay</b><br>
            {d['next_macro_event']}
        </div>
        """,
        unsafe_allow_html=True
    )

    st.markdown('<div class="panel-card">', unsafe_allow_html=True)
    st.markdown("### Skor Dağılımı")
    visible_keys = ["DXY", "Faiz", "Risk", "Teknik", "Form", "Volatilite", "MacroRisk"]
    for k in visible_keys:
        render_score_block(k, d["scores"].get(k, 50), d["yorumlar"][k])
    st.markdown('</div>', unsafe_allow_html=True)

# TEKNİK PANEL
st.markdown("---")
st.markdown("## Teknik Panel")

t1, t2, t3 = st.columns(3)
tech = d["technical"]

with t1:
    st.markdown('<div class="panel-card">', unsafe_allow_html=True)
    st.markdown("### Trend ve Momentum")
    st.metric("Trend Rejimi", d["trend_regime"])
    st.metric("RSI", fmt_num(tech.get("rsi"), 1))
    st.metric("Momentum (5)", fmt_num(tech.get("mom_5"), 2, "%"))
    st.markdown('</div>', unsafe_allow_html=True)

with t2:
    st.markdown('<div class="panel-card">', unsafe_allow_html=True)
    st.markdown("### Ortalama ve Güç")
    st.metric("MA20", fmt_num(tech.get("ma20"), 4))
    st.metric("MA50", fmt_num(tech.get("ma50"), 4))
    st.metric("MA100", fmt_num(tech.get("ma100"), 4))
    st.markdown('</div>', unsafe_allow_html=True)

with t3:
    st.markdown('<div class="panel-card">', unsafe_allow_html=True)
    st.markdown("### Volatilite ve Seviye")
    st.metric("MACD Hist", fmt_num(tech.get("macd_hist"), 5))
    st.metric("ATR %", fmt_num(tech.get("atr_pct"), 2, "%"))
    st.metric("Direnç / Destek", f"{fmt_num(d['resistance'], 4)} / {fmt_num(d['support'], 4)}")
    st.markdown('</div>', unsafe_allow_html=True)

tf_left, tf_right = st.columns(2)

with tf_left:
    tf = d["tf_4h"]
    st.markdown('<div class="panel-card">', unsafe_allow_html=True)
    st.markdown("### 4 Saatlik Görünüm")
    if tf.get("ok"):
        c1, c2, c3 = st.columns(3)
        c1.metric("Trend", tf.get("trend", "N/A"))
        c2.metric("RSI", fmt_num(tf.get("rsi"), 1))
        c3.metric("Momentum", fmt_num(tf.get("momentum_5"), 2, "%"))
    else:
        st.warning(tf.get("reason", "Veri yok"))
    st.markdown('</div>', unsafe_allow_html=True)

with tf_right:
    tf = d["tf_daily"]
    st.markdown('<div class="panel-card">', unsafe_allow_html=True)
    st.markdown("### Günlük Görünüm")
    if tf.get("ok"):
        c1, c2, c3 = st.columns(3)
        c1.metric("Trend", tf.get("trend", "N/A"))
        c2.metric("RSI", fmt_num(tf.get("rsi"), 1))
        c3.metric("Momentum", fmt_num(tf.get("momentum_5"), 2, "%"))
    else:
        st.warning(tf.get("reason", "Veri yok"))
    st.markdown('</div>', unsafe_allow_html=True)

# MAKRO PANEL
st.markdown("---")
st.markdown("## Makro Panel")

m1, m2, m3 = st.columns(3)

with m1:
    st.markdown('<div class="panel-card">', unsafe_allow_html=True)
    st.markdown("### USD ve Risk")
    st.metric("DXY 3 Günlük", fmt_num(d["dxy_pct"], 2, "%"))
    st.metric("VIX", fmt_num(d["vix"], 1))
    st.caption(f"DXY kaynak: {d.get('dxy_source', 'N/A')}")
    st.markdown('</div>', unsafe_allow_html=True)

with m2:
    st.markdown('<div class="panel-card">', unsafe_allow_html=True)
    st.markdown("### Spread Yapısı")
    st.metric("US-DE 2Y Spread", fmt_num(d["spread_2y"], 2, "%"))
    st.metric("US-DE 10Y Spread", fmt_num(d["spread_10y"], 2, "%"))
    st.markdown('</div>', unsafe_allow_html=True)

with m3:
    st.markdown('<div class="panel-card">', unsafe_allow_html=True)
    st.markdown("### Makro Risk")
    st.metric("Makro Risk Skoru", fmt_num(d["scores"]["MacroRisk"], 0))
    st.write(f"**Sonraki olay:** {d['next_macro_event']}")
    st.caption(f"Makro kaynak: {d.get('macro_source') or 'N/A'} ({d.get('macro_status') or 'N/A'})")
    st.markdown('</div>', unsafe_allow_html=True)

st.markdown('<div class="panel-card">', unsafe_allow_html=True)
st.markdown("### Veri Kaynakları")
source_rows = [
    ("DXY", d.get("dxy_source", "N/A")),
    ("US 2Y", d.get("us2y_source", "N/A")),
    ("US 10Y", d.get("us10y_source", "N/A")),
    ("DE 2Y", d.get("de2y_source", "N/A")),
    ("DE 10Y", d.get("de10y_source", "N/A")),
    ("Makro", f"{d.get('macro_source') or 'N/A'} / {d.get('macro_status') or 'N/A'}"),
]
for label, value in source_rows:
    st.write(f"**{label}:** {value}")
st.markdown('</div>', unsafe_allow_html=True)

# OLASILIK / BACKTEST PANELİ
st.markdown("---")
st.markdown("## Olasılık / Backtest Paneli")

prob = d["probability"]

st.markdown('<div class="panel-card">', unsafe_allow_html=True)
st.write(prob["summary_text"])

if prob["sample_size"] > 0:
    pcols = st.columns(5)
    for i, h in enumerate([3, 5, 10, 20, 30]):
        item = prob["horizons"][h]
        with pcols[i]:
            st.metric(f"{h} Gün", f"%{item['down_probability']}")
            st.caption(f"Ort. getiri: {item['avg_return']}%")
else:
    st.warning("Benzer tarihsel koşul bulunamadı.")
st.markdown('</div>', unsafe_allow_html=True)

# SATIŞ PLANI PANELİ
st.markdown("---")
st.markdown("## Satış Planı Paneli")

s1, s2 = st.columns([2, 1])

with s1:
    st.markdown('<div class="panel-card">', unsafe_allow_html=True)
    st.markdown(f"### {d['sale_plan']['plan_label']}")
    st.write(d["sale_plan"]["explanation"])
    st.write(f"**Risk notu:** {d['risk_note']}")
    st.markdown('</div>', unsafe_allow_html=True)

with s2:
    st.markdown('<div class="panel-card">', unsafe_allow_html=True)
    st.metric("Toplam", f"{d['sale_plan']['daily_units']} birim")
    st.metric("Sabah", f"{d['sale_plan']['morning_units']} birim")
    st.metric("Öğleden Sonra", f"{d['sale_plan']['afternoon_units']} birim")
    st.markdown('</div>', unsafe_allow_html=True)

# TREASURY PERFORMANCE PANELİ
st.markdown("---")
st.markdown("## Treasury Performance Paneli")

k1, k2, k3, k4 = st.columns(4)

with k1:
    render_metric_card(
        "Ortalama Günlük Satış",
        f"{treasury_metrics['avg_sale_units']} / 100",
        sub="Karar günlüğü bazlı"
    )

with k2:
    render_metric_card(
        "Hit Rate",
        f"%{treasury_metrics['hit_rate']}",
        sub="Yüksek EDE gün oranı"
    )

with k3:
    render_metric_card(
        "Ortalama Avantaj",
        f"{treasury_metrics['avg_advantage']}%",
        sub="Proxy model katkısı"
    )

with k4:
    render_metric_card(
        "Korunan Değer",
        f"${int(treasury_metrics['protected_value']):,}",
        sub="Tahmini katkı"
    )

st.markdown('<div class="panel-card">', unsafe_allow_html=True)
st.markdown("### Son Kararlar ve Operasyon Geçmişi")

if not log_df.empty:
    display_cols = [
        "date", "ede", "trend", "spot",
        "daily_units", "morning_units", "afternoon_units", "decision"
    ]
    st.dataframe(log_df[display_cols].tail(15), use_container_width=True, hide_index=True)
else:
    st.info("Henüz log kaydı yok. 'Bugünkü Kararı Logla' butonunu kullan.")
st.markdown('</div>', unsafe_allow_html=True)

# RAPOR
st.markdown("---")
st.markdown("## Analiz Raporu")

with st.container():
    st.markdown('<div class="rapor-box">', unsafe_allow_html=True)
    st.markdown(build_report_text(d))
    st.markdown('</div>', unsafe_allow_html=True)

st.markdown(d["formula_box_text"])

# FİYAT GRAFİĞİ
if d["eur_1d"] is not None and not d["eur_1d"].empty:
    st.markdown("---")
    st.markdown("## EUR/USD Günlük Grafik")

    df_plot = d["eur_1d"].tail(120).copy()

    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=df_plot.index,
        open=df_plot["Open"],
        high=df_plot["High"],
        low=df_plot["Low"],
        close=df_plot["Close"],
        name="EUR/USD",
        increasing_line_color="#00c389",
        decreasing_line_color="#ef4444"
    ))

    if d["support"] is not None:
        fig.add_hline(
            y=d["support"],
            line_dash="dot",
            line_color="#f59e0b",
            annotation_text="Destek"
        )

    if d["resistance"] is not None:
        fig.add_hline(
            y=d["resistance"],
            line_dash="dot",
            line_color="#60a5fa",
            annotation_text="Direnç"
        )

    fig.update_layout(
        paper_bgcolor="#0b1020",
        plot_bgcolor="#111827",
        font={"color": "#f8fafc"},
        xaxis_rangeslider_visible=False,
        height=460,
        margin=dict(t=20, b=20, l=10, r=10)
    )

    st.plotly_chart(fig, use_container_width=True)

with st.expander("🔍 Geliştirici / Debug Bilgisi"):
    st.write(f"**Veri Güveni:** {d['data_quality_score']}/100 ({d['confidence_label']})")
    st.write(f"**DXY Kaynak:** {d.get('dxy_source', 'N/A')}")
    st.write(f"**Ağırlık Seti:** {d.get('weights', {})}")
    st.write(f"**Validation Özeti:** {d.get('validation_summary', {})}")
    st.write(f"**Kaynaklar:** {d['debug']['sources']}")
    if st.checkbox("Ham debug JSON göster", value=False):
        st.json(d["debug"])

st.markdown("---")
st.caption("Selvese Pusulası • Bu uygulama bilgi amaçlıdır, yatırım tavsiyesi içermez.")
