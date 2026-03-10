"""
ui/app.py — Selvese EUR Satış Pusulası Dashboard v4.0

Tab mimarisi:
    1. Ana Panel    → Adaptive EDE, rejim, execution plan, waterfall
    2. Teknik       → Grafik, MA/RSI/MACD, 4H/1D
    3. Makro        → Faiz spread, VIX, DXY, makro takvim
    4. Forecast     → Yön tahmini, horizon tablosu
    5. Backtest     → Olasılık (CI), regime-conditional
    6. Geçmiş       → Karar günlüğü, treasury performans
"""

import streamlit as st
import plotly.graph_objects as go

from engine.engine import run_engine, build_report_text
from storage.logger import log_daily_decision, read_decision_log, build_treasury_metrics

st.set_page_config(page_title="Selvese EUR Satış Pusulası", page_icon="🧭", layout="wide")

st.markdown("""
<style>
    .main { background-color: #0b1020; }
    .block-container { padding-top: 1.2rem; padding-bottom: 1.5rem; max-width: 1500px; }
    h1, h2, h3 { color: #f3f6fb; letter-spacing: -0.02em; }
    .stTabs [data-baseweb="tab-list"] { gap: 8px; }
    .stTabs [data-baseweb="tab"] { background: #111827; border: 1px solid #1f2937; border-radius: 10px 10px 0 0; padding: 10px 20px; color: #93a3b8; font-weight: 600; }
    .stTabs [aria-selected="true"] { background: #1a2332; border-bottom: 2px solid #2c74ff; color: #f8fafc; }
    .panel-card { background: #111827; border: 1px solid #1f2937; border-radius: 16px; padding: 16px 18px; margin-bottom: 12px; box-shadow: 0 8px 20px rgba(0,0,0,0.18); }
    .metric-card { background: #111827; border: 1px solid #1f2937; border-radius: 14px; padding: 16px 18px; margin: 6px 0; min-height: 96px; }
    .metric-card.sat { border-left: 4px solid #00c389; }
    .metric-card.hazirlan { border-left: 4px solid #f59e0b; }
    .metric-card.bekle { border-left: 4px solid #60a5fa; }
    .metric-label { font-size: 12px; color: #93a3b8; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.06em; }
    .metric-value { font-size: 30px; font-weight: 700; color: #f8fafc; line-height: 1.1; }
    .metric-sub { font-size: 13px; color: #9fb0c8; margin-top: 8px; }
    .plan-box { background: linear-gradient(180deg, #172033 0%, #101726 100%); border: 1px solid #24324d; border-radius: 16px; padding: 18px 20px; margin-bottom: 14px; }
    .plan-title { font-size: 14px; font-weight: 700; color: #8fb4ff; letter-spacing: 0.04em; text-transform: uppercase; margin-bottom: 10px; }
    .plan-main { font-size: 28px; font-weight: 800; color: #f8fafc; margin-bottom: 8px; }
    .plan-text { font-size: 15px; color: #d4deea; line-height: 1.7; }
    .risk-box { background: rgba(245,158,11,0.10); border: 1px solid rgba(245,158,11,0.30); border-radius: 14px; padding: 14px 16px; color: #fde7b0; margin-top: 10px; }
    .info-box { background: rgba(96,165,250,0.10); border: 1px solid rgba(96,165,250,0.28); border-radius: 14px; padding: 14px 16px; color: #cfe3ff; margin-top: 10px; }
    .regime-box { background: rgba(124,58,237,0.10); border: 1px solid rgba(124,58,237,0.28); border-radius: 14px; padding: 14px 16px; color: #ddd6fe; margin-top: 10px; }
    .mini-badge { display: inline-block; padding: 6px 10px; border-radius: 999px; font-size: 12px; font-weight: 700; margin-top: 10px; }
    .badge-high { background: rgba(0,195,137,0.14); color: #00c389; border: 1px solid rgba(0,195,137,0.28); }
    .badge-mid { background: rgba(245,158,11,0.14); color: #f59e0b; border: 1px solid rgba(245,158,11,0.28); }
    .badge-low { background: rgba(96,165,250,0.14); color: #60a5fa; border: 1px solid rgba(96,165,250,0.28); }
    .score-row { margin: 10px 0 14px 0; }
    .score-header { display: flex; justify-content: space-between; margin-bottom: 5px; font-size: 14px; }
    .score-label { color: #d5deea; font-weight: 600; }
    .score-value { font-weight: 700; }
    .score-track { width: 100%; height: 8px; background: #1b2433; border-radius: 999px; overflow: hidden; }
    .score-fill { height: 8px; border-radius: 999px; }
    .score-comment { color: #8fa0b7; font-size: 12px; margin-top: 5px; line-height: 1.5; }
    .stButton > button { background: #2c74ff; color: white; border: none; border-radius: 10px; padding: 10px 14px; font-size: 15px; font-weight: 700; width: 100%; }
    .stButton > button:hover { background: #1f5fdb; color: white; }
</style>
""", unsafe_allow_html=True)


def fmt_num(value, digits=2, suffix=""):
    if value is None: return "N/A"
    return f"{value:.{digits}f}{suffix}"

def confidence_badge(label):
    cls = {"Yüksek": "badge-high", "Orta": "badge-mid"}.get(label, "badge-low")
    return f'<span class="mini-badge {cls}">Veri Güveni: {label}</span>'

def score_color(v):
    if v >= 65: return "#00c389"
    if v >= 45: return "#f59e0b"
    return "#60a5fa"

def render_metric_card(label, value, sub="", status_class=""):
    st.markdown(f'<div class="metric-card {status_class}"><div class="metric-label">{label}</div><div class="metric-value">{value}</div><div class="metric-sub">{sub}</div></div>', unsafe_allow_html=True)

def render_score_block(name, value, comment):
    c = score_color(value)
    st.markdown(f'<div class="score-row"><div class="score-header"><span class="score-label">{name}</span><span class="score-value" style="color:{c}">{value:.0f}</span></div><div class="score-track"><div class="score-fill" style="width:{value}%; background:{c};"></div></div><div class="score-comment">{comment}</div></div>', unsafe_allow_html=True)

def barometre(ede, karar, renk):
    renk_map = {"sat": "#00c389", "hazirlan": "#f59e0b", "bekle": "#60a5fa"}
    c = renk_map.get(renk, "#60a5fa")
    fig = go.Figure(go.Indicator(mode="gauge+number", value=ede, number={"font": {"size": 48, "color": c}},
        gauge={"axis": {"range": [0,100], "tickwidth": 1, "tickcolor": "#64748b"}, "bar": {"color": c, "thickness": 0.24},
               "bgcolor": "#111827", "borderwidth": 0,
               "steps": [{"range": [0,40], "color": "#12263a"}, {"range": [40,52], "color": "#1f3047"}, {"range": [52,65], "color": "#3a2d16"}, {"range": [65,100], "color": "#123128"}],
               "threshold": {"line": {"color": c, "width": 4}, "thickness": 0.75, "value": ede}},
        title={"text": f"<b>{karar}</b>", "font": {"size": 24, "color": c}}))
    fig.update_layout(paper_bgcolor="#0b1020", font={"color": "#f8fafc"}, height=280, margin=dict(t=40, b=10, l=10, r=10))
    return fig

def waterfall_chart(waterfall_data):
    if not waterfall_data: return None
    labels = [s["label"] for s in waterfall_data]
    totals = [s["running_total"] for s in waterfall_data]
    deltas = [s["delta"] for s in waterfall_data]
    colors = ["#00c389" if d >= 0 else "#ef4444" for d in deltas]
    fig = go.Figure(go.Bar(x=labels, y=totals, marker_color=colors, text=[f"{d:+d}" for d in deltas], textposition="outside", textfont={"color": "#f8fafc", "size": 14}))
    fig.update_layout(paper_bgcolor="#0b1020", plot_bgcolor="#111827", font={"color": "#f8fafc"}, height=300, margin=dict(t=20, b=40, l=40, r=20), yaxis=dict(range=[0, max(totals) * 1.25 if totals else 100], gridcolor="#1f2937"), xaxis=dict(tickangle=-30))
    return fig

# ─── Header ───
st.title("🧭 Selvese EUR Satış Pusulası")
st.caption("Kurumsal EUR satış yönetimi için açıklanabilir operasyon paneli • v4.0")

top_left, top_mid, top_right = st.columns([2, 2, 3])
with top_left: refresh = st.button("🔄 Analizi Güncelle")
with top_mid: save_log = st.button("💾 Bugünkü Kararı Logla")

if "data" not in st.session_state: st.session_state.data = None
if refresh:
    with st.spinner("Motor çalışıyor, veriler toplanıyor..."):
        st.session_state.data = run_engine()
if st.session_state.data is None:
    st.info("Önce 'Analizi Güncelle' butonuna bas.")
    st.stop()

d = st.session_state.data
if d.get("error"): st.error(d["error"]); st.stop()
if save_log: st.success(f"Karar günlüğe kaydedildi: {log_daily_decision(d)}")
with top_right: st.caption(f"Son güncelleme: {d['zaman']}")

log_df = read_decision_log()
treasury_metrics = build_treasury_metrics(log_df)

# ═══════════ TABS ═══════════
tab_ana, tab_teknik, tab_makro, tab_forecast, tab_backtest, tab_gecmis = st.tabs(["📊 Ana Panel", "📈 Teknik", "🌍 Makro", "🔮 Forecast", "📉 Backtest", "📋 Geçmiş"])

# ── TAB 1: ANA PANEL ──
with tab_ana:
    left, right = st.columns([1.05, 1.95])
    with left:
        st.plotly_chart(barometre(d["ede"], d["karar"], d["renk"]), use_container_width=True)
        regime_label = d.get("market_regime", "")
        static_ede = d.get("static_ede")
        delta = d.get("ede_delta", 0)
        if regime_label:
            st.markdown(f'<div class="regime-box"><b>Rejim: {regime_label}</b> Δ {delta:+.1f}<br><span style="font-size:13px">{d.get("regime_description", "")}</span><br><span style="font-size:12px; color:#a78bfa">Statik: {fmt_num(static_ede, 1)} → Adaptive: {fmt_num(d["ede"], 1)}</span></div>', unsafe_allow_html=True)
        render_metric_card("EUR/USD Spot", fmt_num(d["spot"], 4), sub=confidence_badge(d["confidence_label"]), status_class=d["renk"])
        render_metric_card("Trend Rejimi", d["trend_regime"], sub=f"Veri Güven Skoru: {fmt_num(d['data_quality_score'], 0)}/100")

    with right:
        sp = d["sale_plan"]
        st.markdown(f'<div class="plan-box"><div class="plan-title">Bugünün Satış Planı</div><div class="plan-main">{sp["plan_label"]} — {sp["daily_units"]} / 100 birim</div><div class="plan-text">Sabah {sp["morning_units"]} • Öğleden sonra {sp["afternoon_units"]}</div></div>', unsafe_allow_html=True)
        exec_result = d.get("execution_result")
        if exec_result and exec_result.get("waterfall"):
            wf_fig = waterfall_chart(exec_result["waterfall"])
            if wf_fig:
                st.markdown("**Satış Planı Waterfall**")
                st.plotly_chart(wf_fig, use_container_width=True)
                conf = exec_result.get("confidence", {})
                if conf: st.markdown(f"**Execution Güveni:** {conf.get('label', 'N/A')} ({conf.get('score', 0):.0f}%)")
        st.markdown(f'<div class="risk-box"><b>En Büyük Risk</b><br>{d["risk_note"]}</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="info-box"><b>Sonraki Makro Olay</b><br>{d["next_macro_event"]}</div>', unsafe_allow_html=True)
        warnings = d.get("validation_warnings", [])
        if warnings:
            st.markdown(f'<div class="risk-box"><b>Veri Uyarıları</b><br>{"<br>".join("• " + w for w in warnings[:5])}</div>', unsafe_allow_html=True)
        st.markdown('<div class="panel-card">', unsafe_allow_html=True)
        st.markdown("### Skor Dağılımı")
        for k in ["DXY", "Faiz", "Risk", "Teknik", "Form", "Volatilite", "MacroRisk"] + (["Momentum"] if "Momentum" in d.get("scores", {}) else []):
            render_score_block(k, d["scores"].get(k, 50), d["yorumlar"].get(k, ""))
        st.markdown('</div>', unsafe_allow_html=True)

# ── TAB 2: TEKNİK ──
with tab_teknik:
    tech = d.get("technical", {})
    t1, t2, t3 = st.columns(3)
    with t1:
        st.markdown('<div class="panel-card">', unsafe_allow_html=True); st.markdown("### Trend ve Momentum")
        st.metric("Trend Rejimi", d["trend_regime"]); st.metric("RSI", fmt_num(tech.get("rsi"), 1)); st.metric("Momentum (5G)", fmt_num(tech.get("mom_5"), 2, "%")); st.metric("Momentum (20G)", fmt_num(tech.get("mom_20"), 2, "%"))
        st.markdown('</div>', unsafe_allow_html=True)
    with t2:
        st.markdown('<div class="panel-card">', unsafe_allow_html=True); st.markdown("### Hareketli Ortalamalar")
        st.metric("MA20", fmt_num(tech.get("ma20"), 4)); st.metric("MA50", fmt_num(tech.get("ma50"), 4)); st.metric("MA100", fmt_num(tech.get("ma100"), 4))
        st.markdown('</div>', unsafe_allow_html=True)
    with t3:
        st.markdown('<div class="panel-card">', unsafe_allow_html=True); st.markdown("### Volatilite ve Seviye")
        st.metric("MACD Hist", fmt_num(tech.get("macd_hist"), 5)); st.metric("ATR %", fmt_num(tech.get("atr_pct"), 2, "%")); st.metric("Direnç / Destek", f"{fmt_num(d.get('resistance'), 4)} / {fmt_num(d.get('support'), 4)}")
        st.markdown('</div>', unsafe_allow_html=True)
    tf_l, tf_r = st.columns(2)
    for col, tf_key, label in [(tf_l, "tf_4h", "4 Saatlik"), (tf_r, "tf_daily", "Günlük")]:
        with col:
            tf = d.get(tf_key, {})
            st.markdown('<div class="panel-card">', unsafe_allow_html=True); st.markdown(f"### {label} Görünüm")
            if tf.get("ok"):
                c1, c2, c3 = st.columns(3); c1.metric("Trend", tf.get("trend", "N/A")); c2.metric("RSI", fmt_num(tf.get("rsi"), 1)); c3.metric("Momentum", fmt_num(tf.get("momentum_5"), 2, "%"))
            else: st.warning(tf.get("reason", "Veri yok"))
            st.markdown('</div>', unsafe_allow_html=True)
    if d.get("eur_1d") is not None and not d["eur_1d"].empty:
        st.markdown("### EUR/USD Günlük Grafik")
        df_plot = d["eur_1d"].tail(120).copy()
        fig = go.Figure(); fig.add_trace(go.Candlestick(x=df_plot.index, open=df_plot["Open"], high=df_plot["High"], low=df_plot["Low"], close=df_plot["Close"], name="EUR/USD", increasing_line_color="#00c389", decreasing_line_color="#ef4444"))
        if d.get("support"): fig.add_hline(y=d["support"], line_dash="dot", line_color="#f59e0b", annotation_text="Destek")
        if d.get("resistance"): fig.add_hline(y=d["resistance"], line_dash="dot", line_color="#60a5fa", annotation_text="Direnç")
        fig.update_layout(paper_bgcolor="#0b1020", plot_bgcolor="#111827", font={"color": "#f8fafc"}, xaxis_rangeslider_visible=False, height=460, margin=dict(t=20, b=20, l=10, r=10))
        st.plotly_chart(fig, use_container_width=True)

# ── TAB 3: MAKRO ──
with tab_makro:
    m1, m2, m3 = st.columns(3)
    with m1:
        st.markdown('<div class="panel-card">', unsafe_allow_html=True); st.markdown("### USD ve Risk"); st.metric("DXY 3 Günlük", fmt_num(d.get("dxy_pct"), 2, "%")); st.metric("VIX", fmt_num(d.get("vix"), 1)); st.markdown('</div>', unsafe_allow_html=True)
    with m2:
        st.markdown('<div class="panel-card">', unsafe_allow_html=True); st.markdown("### Spread Yapısı"); st.metric("US-DE 2Y Spread", fmt_num(d.get("spread_2y"), 2, "%")); st.metric("US-DE 10Y Spread", fmt_num(d.get("spread_10y"), 2, "%")); st.markdown('</div>', unsafe_allow_html=True)
    with m3:
        st.markdown('<div class="panel-card">', unsafe_allow_html=True); st.markdown("### Makro Risk"); st.metric("Makro Risk Skoru", fmt_num(d["scores"].get("MacroRisk"), 0)); st.write(f"**Sonraki olay:** {d.get('next_macro_event', 'N/A')}"); st.markdown('</div>', unsafe_allow_html=True)
    events = d.get("macro_events", [])
    if events:
        st.markdown("### Yaklaşan Yüksek Etkili Veriler")
        for ev in events[:8]: st.write(f"• **{ev.get('date', '')}** — {ev.get('event', '')} ({ev.get('country', '')})")

# ── TAB 4: FORECAST ──
with tab_forecast:
    fc = d.get("forecast")
    if fc and fc.get("sample_size", 0) > 0:
        st.markdown('<div class="panel-card">', unsafe_allow_html=True); st.markdown("### EUR/USD Yön Tahmini"); st.write(fc.get("summary", ""))
        horizons = fc.get("horizons", {})
        if horizons:
            cols = st.columns(len(horizons))
            for i, (h, hd) in enumerate(sorted(horizons.items())):
                with cols[i]:
                    emoji = "🔻" if hd["direction"] == "DOWN" else "🔺" if hd["direction"] == "UP" else "➡️"
                    st.metric(f"{h} Gün {emoji}", f"%{hd['probability']:.0f}")
                    warn = "" if hd.get("reliable") else " ⚠️"
                    st.caption(f"CI: %{hd['ci_lower']:.0f}–%{hd['ci_upper']:.0f}{warn}")
                    st.caption(f"Ort: {hd['avg_return']:+.3f}%")
        st.write(f"Model: {fc.get('model_type', 'N/A')} | n={fc.get('sample_size', 0)}")
        st.markdown('</div>', unsafe_allow_html=True)
    else:
        st.info("Forecast verisi henüz hesaplanmadı veya yeterli veri yok.")
        if fc: st.caption(fc.get("summary", ""))

# ── TAB 5: BACKTEST ──
with tab_backtest:
    prob = d.get("probability", {})
    st.markdown('<div class="panel-card">', unsafe_allow_html=True); st.markdown("### Olasılık / Backtest Özeti"); st.write(prob.get("summary_text", "Veri yok"))
    if prob.get("sample_size", 0) > 0:
        pcols = st.columns(5)
        for i, h in enumerate([3, 5, 10, 20, 30]):
            item = prob.get("horizons", {}).get(h, {})
            if not item: continue
            with pcols[i]:
                st.metric(f"{h} Gün", f"%{item.get('down_probability', 0)}")
                ci_lo, ci_hi = item.get("ci_lower"), item.get("ci_upper")
                if ci_lo is not None: st.caption(f"CI: %{ci_lo:.0f}–%{ci_hi:.0f}{'' if item.get('reliable', True) else ' ⚠️'}")
                st.caption(f"Ort: {item.get('avg_return', 0)}%")
    else: st.warning("Benzer tarihsel koşul bulunamadı.")
    st.markdown('</div>', unsafe_allow_html=True)
    wf = d.get("walk_forward")
    if wf:
        st.markdown('<div class="panel-card">', unsafe_allow_html=True); st.markdown("### Walk-Forward Validation"); st.write(wf.get("summary", ""))
        split = wf.get("split", {})
        if split: st.write(f"Train: {split.get('train_size', 0)} gün | Test: {split.get('test_size', 0)} gün")
        st.markdown('</div>', unsafe_allow_html=True)

# ── TAB 6: GEÇMİŞ ──
with tab_gecmis:
    k1, k2, k3, k4 = st.columns(4)
    with k1: render_metric_card("Ort. Günlük Satış", f"{treasury_metrics['avg_sale_units']} / 100", sub="Karar günlüğü bazlı")
    with k2: render_metric_card("Hit Rate", f"%{treasury_metrics['hit_rate']}", sub="Yüksek EDE gün oranı")
    with k3: render_metric_card("Ort. Avantaj", f"{treasury_metrics['avg_advantage']}%", sub="Proxy model katkısı")
    with k4: render_metric_card("Korunan Değer", f"${int(treasury_metrics['protected_value']):,}", sub="Tahmini katkı")
    st.markdown('<div class="panel-card">', unsafe_allow_html=True); st.markdown("### Son Kararlar")
    if not log_df.empty: st.dataframe(log_df[["date", "ede", "trend", "spot", "daily_units", "morning_units", "afternoon_units", "decision"]].tail(15), use_container_width=True, hide_index=True)
    else: st.info("Henüz log kaydı yok.")
    st.markdown('</div>', unsafe_allow_html=True)
    with st.expander("📄 Tam Analiz Raporu"): st.markdown(build_report_text(d))
    st.markdown(d.get("formula_box_text", ""))

with st.expander("🔍 Debug"): st.json(d.get("debug", {}))
st.markdown("---")
st.caption("Selvese Pusulası v4.0 • Bu uygulama bilgi amaçlıdır, yatırım tavsiyesi içermez.")
