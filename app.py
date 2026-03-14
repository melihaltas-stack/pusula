import streamlit as st
import plotly.graph_objects as go
import threading
import time
import pickle
from pathlib import Path

from logging_config import setup_logging
setup_logging()

from engine import run_engine, build_report_text
from logger import log_daily_decision, read_decision_log, build_treasury_metrics, build_factor_contribution_summary


_DETAIL_LOCK = threading.Lock()
_DETAIL_TASKS = {}
_DETAIL_CACHE_FILE = Path("/tmp/selvese-pusula-detail-report.pkl")


def _make_detail_task_key(manual_inputs=None):
    manual_inputs = manual_inputs or {}
    normalized = tuple(sorted((str(k), float(v) if v is not None else None) for k, v in manual_inputs.items()))
    return f"{int(time.time() * 1000)}::{normalized}"


def _run_detail_task(task_key, manual_inputs=None):
    try:
        result = run_engine(
            manual_inputs=manual_inputs,
            include_extended_data=True,
            include_performance_report=True,
        )
        save_detail_report_cache(result)
        with _DETAIL_LOCK:
            _DETAIL_TASKS[task_key] = {"status": "ready", "result": result, "error": None}
    except Exception as exc:
        with _DETAIL_LOCK:
            _DETAIL_TASKS[task_key] = {"status": "error", "result": None, "error": str(exc)}


def start_background_detail_report(manual_inputs=None):
    task_key = _make_detail_task_key(manual_inputs=manual_inputs)
    with _DETAIL_LOCK:
        _DETAIL_TASKS[task_key] = {"status": "running", "result": None, "error": None}
    worker = threading.Thread(target=_run_detail_task, args=(task_key, manual_inputs), daemon=True)
    worker.start()
    st.session_state.detail_task_key = task_key
    st.session_state.detail_task_mode = "background"


def get_background_detail_status():
    task_key = st.session_state.get("detail_task_key")
    if not task_key:
        return None
    with _DETAIL_LOCK:
        return _DETAIL_TASKS.get(task_key)


def format_age_text(age_seconds):
    if age_seconds is None:
        return "bilinmiyor"
    total_minutes = int(round(age_seconds / 60))
    hours = total_minutes // 60
    minutes = total_minutes % 60
    if hours <= 0:
        return f"{minutes} dk"
    if minutes == 0:
        return f"{hours} sa"
    return f"{hours} sa {minutes} dk"


def should_start_background_detail_report(manual_inputs=None):
    if manual_inputs:
        return False
    cached_detail = load_detail_report_cache()
    return cached_detail is None


def save_detail_report_cache(result):
    if not isinstance(result, dict) or result.get("error"):
        return
    payload = {
        "saved_at": time.time(),
        "result": result,
    }
    with _DETAIL_CACHE_FILE.open("wb") as fh:
        pickle.dump(payload, fh)


def load_detail_report_cache():
    if not _DETAIL_CACHE_FILE.exists():
        return None
    try:
        with _DETAIL_CACHE_FILE.open("rb") as fh:
            payload = pickle.load(fh)
        if not isinstance(payload, dict):
            return None
        result = payload.get("result")
        if not isinstance(result, dict) or result.get("error"):
            return None
        saved_at = payload.get("saved_at")
        age_seconds = max(0.0, time.time() - float(saved_at)) if saved_at is not None else None
        payload["age_seconds"] = age_seconds
        return payload
    except (OSError, pickle.PickleError, EOFError, AttributeError, ValueError):
        return None


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


def pretty_source_key(key):
    labels = {
        "eur_1d": "EUR/USD 1D",
        "eur_4h": "EUR/USD 4H",
        "dxy_df": "DXY",
        "vix_df": "VIX",
        "us2y": "US 2Y",
        "us10y": "US 10Y",
        "de2y": "DE 2Y",
        "de10y": "DE 10Y",
        "macro_events": "Makro Takvim",
        "spot": "Spot",
    }
    return labels.get(key, key)


def build_manual_requirements(result):
    validation = result.get("validation_results", {}) if isinstance(result, dict) else {}
    required = []

    checks = [
        ("spot", "EUR/USD Spot", "manual_spot", 1.14165, "%.5f", 0.0001),
        ("dxy_pct", "DXY Degisim %", "manual_dxy_pct", 0.75, "%.2f", 0.01),
        ("vix", "VIX", "manual_vix", 27.18, "%.2f", 0.01),
        ("us2y", "US 2Y", "manual_us2y", 3.729, "%.3f", 0.001),
        ("us10y", "US 10Y", "manual_us10y", 4.283, "%.3f", 0.001),
    ]

    for key, label, state_key, fallback, fmt, step in checks:
        vr = validation.get(key)
        current = result.get(key)
        invalid = vr is not None and not getattr(vr, "valid", False)
        if current is None or invalid:
            required.append(
                {
                    "key": key,
                    "label": label,
                    "state_key": state_key,
                    "value": fallback if current is None else current,
                    "format": fmt,
                    "step": step,
                }
            )

    return required


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


def render_horizon_summary(view):
    forecast_overlay = view.get("forecast_overlay", {})
    forecast_delta = forecast_overlay.get("delta", 0.0)
    forecast_sign = "+" if forecast_delta > 0 else ""
    business = view.get("business", {})
    st.markdown(
        f"""
        <div class="plan-box">
            <div class="plan-title">{view['label']} • {view['window']}</div>
            <div class="plan-main">{view['emoji']} {view['karar']}</div>
            <div class="plan-text">Hibrit EDE: <b>{view['ede']}</b> | Baz EDE: <b>{view.get('base_ede', view['ede'])}</b> | Forecast etkisi: <b>{forecast_sign}{forecast_delta}</b> | Plan: <b>{view['sale_plan']['daily_units']}/100</b></div>
            <div class="info-box"><b>Önerilen aksiyon</b><br>{business.get('action', view['summary'])}</div>
            <div class="info-box"><b>Neden şimdi</b><br>{business.get('why_now', view['summary'])}</div>
            <div class="info-box"><b>İstatistiksel destek</b><br>{forecast_overlay.get('summary', 'İstatistiksel tahmin yok.')}</div>
            <div class="risk-box"><b>Temel risk</b><br>{business.get('risk', 'Piyasa koşulları hızla değişebilir.')}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


st.title("🧭 Selvese EUR Satış Pusulası")
st.caption("Kurumsal EUR satış yönetimi için açıklanabilir operasyon paneli")
st.markdown(
    '<div style="background:rgba(239,68,68,0.10);border:1px solid rgba(239,68,68,0.30);'
    'border-radius:12px;padding:12px 14px;margin:8px 0 14px 0;color:#fecaca;">'
    '<b>Uyarı</b> &nbsp;|&nbsp; Bu uygulama Selvese Yatırım A.Ş. ve iştiraklerinin kullanımı için özel olarak hazırlanmıştır. '
    'Yatırım tavsiyesi içermez.'
    '</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<div style="background:rgba(96,165,250,0.12);border:1px solid rgba(96,165,250,0.30);'
    'border-radius:12px;padding:12px 14px;margin:8px 0 14px 0;color:#dbeafe;">'
    '<b>Akıllı Akış</b> &nbsp;|&nbsp; Uygulama önce otomatik veriyi dener. Eksik kalan kritik alanlar olursa aşağıda sadece onları manuel ister.'
    '</div>',
    unsafe_allow_html=True,
)

top_left, top_mid, top_right = st.columns([2, 2, 3])

with top_left:
    refresh = st.button("🔄 Otomatik Analizi Çalıştır")

with top_mid:
    save_log = st.button("💾 Bugünkü Kararı Logla")

with top_right:
    detailed_mode = st.checkbox("Detaylı mod", value=False, help="Açık veriyle ek factor'lar ve performans raporunu da hesaplar. Daha yavaştır.")

if "data" not in st.session_state:
    st.session_state.data = None
if "manual_requirements" not in st.session_state:
    st.session_state.manual_requirements = []
if "detail_task_key" not in st.session_state:
    st.session_state.detail_task_key = None
if "detail_task_mode" not in st.session_state:
    st.session_state.detail_task_mode = None
if "loaded_from_detail_cache" not in st.session_state:
    st.session_state.loaded_from_detail_cache = False
if "detail_cache_age_seconds" not in st.session_state:
    st.session_state.detail_cache_age_seconds = None

if st.session_state.data is None:
    cached_detail = load_detail_report_cache()
    if cached_detail:
        st.session_state.data = cached_detail["result"]
        st.session_state.manual_requirements = build_manual_requirements(st.session_state.data)
        st.session_state.detail_task_mode = "cached"
        st.session_state.loaded_from_detail_cache = True
        st.session_state.detail_cache_age_seconds = cached_detail.get("age_seconds")

if refresh:
    with st.spinner("Motor çalışıyor, veriler toplanıyor..."):
        st.session_state.data = run_engine(
            include_extended_data=detailed_mode,
            include_performance_report=detailed_mode,
        )
        st.session_state.manual_requirements = build_manual_requirements(st.session_state.data)
        if detailed_mode:
            st.session_state.detail_task_key = None
            st.session_state.detail_task_mode = "sync"
            save_detail_report_cache(st.session_state.data)
        else:
            if should_start_background_detail_report():
                start_background_detail_report()
            else:
                st.session_state.detail_task_key = None
                st.session_state.detail_task_mode = "cached"
        st.session_state.loaded_from_detail_cache = False
        st.session_state.detail_cache_age_seconds = None

if st.session_state.data is None:
    st.info("Önce 'Otomatik Analizi Çalıştır' butonuna bas.")
    st.stop()

d = st.session_state.data

if not isinstance(d, dict):
    st.stop()
    raise SystemExit

if d.get("error"):
    st.error(d["error"])
    st.stop()

manual_requirements = st.session_state.manual_requirements
if manual_requirements:
    req_labels = ", ".join(item["label"] for item in manual_requirements)
    st.markdown(
        '<div style="background:rgba(245,158,11,0.12);border:1px solid rgba(245,158,11,0.35);'
        'border-radius:12px;padding:12px 14px;margin-bottom:12px;color:#fde68a;">'
        f'<b>Eksik Canlı Veri</b> &nbsp;|&nbsp; Otomatik akış şu alanları tamamlayamadı: {req_labels}. '
        'Aşağıdaki alanları doldurup analizi manuel tamamlayabilirsin.'
        '</div>',
        unsafe_allow_html=True,
    )
    with st.expander("✍️ Eksik Verileri Manuel Tamamla", expanded=True):
        st.caption("Sadece otomatik alınamayan alanlar gösteriliyor.")
        cols = st.columns(min(len(manual_requirements), 5))
        manual_inputs = {}
        for idx, item in enumerate(manual_requirements):
            with cols[idx % len(cols)]:
                min_value = 0.0 if item["key"] in {"spot", "vix"} else None
                kwargs = {
                    "label": item["label"],
                    "value": float(item["value"]),
                    "step": item["step"],
                    "format": item["format"],
                    "key": item["state_key"],
                }
                if min_value is not None:
                    kwargs["min_value"] = min_value
                manual_inputs[item["key"]] = st.number_input(**kwargs)
        if st.button("⚡ Eksik Verilerle Analizi Tamamla"):
            with st.spinner("Eksik verilerle analiz tamamlanıyor..."):
                st.session_state.data = run_engine(
                    manual_inputs=manual_inputs,
                    include_extended_data=detailed_mode,
                    include_performance_report=detailed_mode,
                )
                st.session_state.manual_requirements = build_manual_requirements(st.session_state.data)
                if detailed_mode:
                    st.session_state.detail_task_key = None
                    st.session_state.detail_task_mode = "sync"
                    save_detail_report_cache(st.session_state.data)
                else:
                    st.session_state.detail_task_key = None
                    st.session_state.detail_task_mode = "manual-fast"
                st.session_state.loaded_from_detail_cache = False
                st.session_state.detail_cache_age_seconds = None
            st.rerun()

if save_log:
    path = log_daily_decision(d)
    st.success(f"Karar günlüğe kaydedildi: {path}")

st.caption(f"Son güncelleme: {d['zaman']}")

if st.session_state.get("loaded_from_detail_cache"):
    age_text = format_age_text(st.session_state.get("detail_cache_age_seconds"))
    st.markdown(
        '<div style="background:rgba(250,204,21,0.10);border:1px solid rgba(250,204,21,0.28);'
        'border-radius:12px;padding:12px 14px;margin-bottom:12px;color:#fde68a;">'
        f'<b>Planlı detaylı rapor yüklendi</b> &nbsp;|&nbsp; Uygulama açılışını hızlandırmak için son hazırlanmış detaylı rapor disk cache\'inden yüklendi. Yaş: {age_text}.'
        '</div>',
        unsafe_allow_html=True,
    )

if d.get("fast_mode"):
    st.markdown(
        '<div style="background:rgba(16,185,129,0.10);border:1px solid rgba(16,185,129,0.28);'
        'border-radius:12px;padding:12px 14px;margin-bottom:12px;color:#d1fae5;">'
        '<b>Hızlı mod açık</b> &nbsp;|&nbsp; Uygulama temel karar akışını hızlandırmak için geniş factor seti ve performans raporunu atladı. '
        'Planlı detaylı rapor cache\'i kullanılır; gereksiz yere yeni rapor üretilmez.'
        '</div>',
        unsafe_allow_html=True,
    )

detail_refresh_col, _ = st.columns([1, 4])
with detail_refresh_col:
    if st.button("🧠 Detaylı Raporu Yenile"):
        start_background_detail_report()
        st.rerun()



@st.fragment(run_every="5s")
def render_background_detail_status():
    status = get_background_detail_status()
    if not status or st.session_state.get("detail_task_mode") != "background":
        return

    if status.get("status") == "running":
        st.markdown(
            '<div style="background:rgba(59,130,246,0.10);border:1px solid rgba(59,130,246,0.28);'
            'border-radius:12px;padding:12px 14px;margin-bottom:12px;color:#bfdbfe;">'
            '<b>Arka plan hazırlığı sürüyor</b> &nbsp;|&nbsp; Detaylı Faz-1 raporu hazırlanıyor. Ekranı kullanmaya devam edebilirsin.'
            '</div>',
            unsafe_allow_html=True,
        )
        return

    if status.get("status") == "error":
        st.warning(f"Detaylı rapor arka planda hazırlanamadı: {status.get('error')}")
        return

    if status.get("status") == "ready":
        current_data = st.session_state.get("data") or {}
        if current_data.get("fast_mode"):
            st.session_state.data = status.get("result")
            st.session_state.manual_requirements = build_manual_requirements(st.session_state.data)
            st.session_state.detail_task_mode = "applied"
            st.success("Detaylı Faz-1 raporu hazırlandı ve ekrana yüklendi.")
            st.rerun()


render_background_detail_status()

# --- Veri Tazeliği ---
_freshness = d.get("freshness")
if _freshness:
    _fw = _freshness.worst_label
    _color_map = {"fresh": "#00c389", "warning": "#f59e0b", "stale": "#ef4444", "unknown": "#64748b"}
    _fc = _color_map.get(_fw, "#64748b")
    _stale_labels = [pretty_source_key(k) for k in _freshness.stale_keys()]
    _warning_labels = [pretty_source_key(k) for k in _freshness.warning_keys()]
    st.markdown(
        f'<div style="background:{_fc}18;border:1px solid {_fc}44;border-radius:10px;'
        f'padding:10px 14px;margin-bottom:10px;font-size:13px;color:{_fc};">'
        f'<b>Veri Tazeliği</b> &nbsp;|&nbsp; {_freshness.summary_text} &nbsp;|&nbsp; Skor: {_freshness.score:.0f}/100'
        f'</div>',
        unsafe_allow_html=True
    )
    if _fw == "stale":
        stale_text = ", ".join(_stale_labels) if _stale_labels else "bilinmiyor"
        st.markdown(
            '<div style="background:rgba(239,68,68,0.12);border:1px solid rgba(239,68,68,0.35);'
            'border-radius:12px;padding:12px 14px;margin-bottom:10px;color:#fecaca;">'
            f'<b>Canlı veri bayat</b> &nbsp;|&nbsp; Şu kaynaklar eski cache ile çalışıyor: {stale_text}. '
            'Anlık karar için Hızlı Mod açık kalsın ve manuel 5 veri girilsin.'
            '</div>',
            unsafe_allow_html=True,
        )
        with st.expander("🔴 Bayat veri detayı", expanded=True):
            for k in _freshness.stale_keys():
                s = _freshness.statuses[k]
                st.error(f"{s.badge_emoji} **{pretty_source_key(k)}** — {s.age_text} önce çekildi (limit: {s.ttl_stale}sn)")
    elif _fw == "warning":
        warning_text = ", ".join(_warning_labels) if _warning_labels else "bilinmiyor"
        st.markdown(
            '<div style="background:rgba(245,158,11,0.12);border:1px solid rgba(245,158,11,0.35);'
            'border-radius:12px;padding:12px 14px;margin-bottom:10px;color:#fde68a;">'
            f'<b>Tazelik uyarısı</b> &nbsp;|&nbsp; Şu kaynaklar sınırda: {warning_text}. '
            'Kararı canlı veri gibi okumadan önce kaynakları kontrol et.'
            '</div>',
            unsafe_allow_html=True,
        )
        with st.expander("🟡 Tazelik uyarıları"):
            for k in _freshness.warning_keys():
                s = _freshness.statuses[k]
                st.warning(f"{s.badge_emoji} **{pretty_source_key(k)}** — {s.age_text} önce çekildi")

# --- Validation uyarıları ---
_val_flags = d.get("validation_flags", [])
if _val_flags:
    with st.expander(f"⚠️ {len(_val_flags)} veri uyarısı tespit edildi", expanded=False):
        for _f in _val_flags:
            st.warning(_f)

if d.get("manual_mode"):
    st.info("Manuel veri tamamlama aktif: eksik kalan kritik alanlar kullanıcı girdilerinden kullanıldı.")

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
factor_summary = build_factor_contribution_summary(log_df)

horizon_views = d.get("horizon_views", {})
if horizon_views:
    st.markdown(
        '<div style="background:rgba(15,23,42,0.85);border:1px solid rgba(148,163,184,0.25);'
        'border-radius:12px;padding:12px 14px;margin-bottom:12px;color:#dbe4f0;">'
        '<b>Ekran Nasıl Okunur?</b><br>'
        'Kısa vade günlük operasyon kararını verir. Orta vade planı yaymak için kullanılır. '
        'Uzun vade ise hedge / genel korunma tonunu gösterir. '
        'Sekmelerde önce <b>Önerilen aksiyon</b>, sonra <b>Neden şimdi</b>, en sonda <b>Temel risk</b> okunmalı.'
        '</div>',
        unsafe_allow_html=True,
    )
    st.markdown("## Vade Görünümü")
    horizon_option_map = {
        "Kısa Vade 1-5 gün": "short_term",
        "Orta Vade 1-3 hafta": "medium_term",
        "Uzun Vade 4+ hafta": "long_term",
    }
    selected_horizon_label = st.segmented_control(
        "Vade seç",
        options=list(horizon_option_map.keys()),
        default="Kısa Vade 1-5 gün",
        selection_mode="single",
    )
    selected_horizon_key = horizon_option_map.get(selected_horizon_label, "short_term")
    selected_view = horizon_views[selected_horizon_key]
    render_horizon_summary(selected_view)
else:
    selected_horizon_key = d.get("active_horizon", "short_term")
    selected_view = None

if selected_view is not None:
    dashboard_decision = {
        "ede": selected_view["ede"],
        "karar": selected_view["karar"],
        "renk": selected_view["renk"],
        "emoji": selected_view["emoji"],
        "sale_plan": selected_view["sale_plan"],
        "weights": selected_view["weights"],
        "active_horizon_label": selected_view["label"],
    }
else:
    dashboard_decision = {
        "ede": d["ede"],
        "karar": d["karar"],
        "renk": d["renk"],
        "emoji": d["emoji"],
        "sale_plan": d["sale_plan"],
        "weights": d["weights"],
        "active_horizon_label": d.get("active_horizon_label", "Kısa Vade"),
    }

# ANA OPERASYON EKRANI
st.markdown(f"## Ana Operasyon Ekranı • {dashboard_decision['active_horizon_label']}")

left, right = st.columns([1.05, 1.95])

with left:
    st.plotly_chart(barometre(dashboard_decision["ede"], dashboard_decision["karar"], dashboard_decision["renk"]), use_container_width=True)

    render_metric_card(
        "EUR/USD Spot",
        fmt_num(d["spot"], 4),
        sub=confidence_badge(d["confidence_label"]),
        status_class=dashboard_decision["renk"]
    )

    render_metric_card(
        "Günlük Satış Planı",
        f"{dashboard_decision['sale_plan']['daily_units']} / 100",
        sub=f"Sabah {dashboard_decision['sale_plan']['morning_units']} • Öğleden sonra {dashboard_decision['sale_plan']['afternoon_units']}",
        status_class=dashboard_decision["renk"]
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
            <div class="plan-main">{dashboard_decision['sale_plan']['plan_label']}</div>
            <div class="plan-text">
                Seçili vade: <b>{dashboard_decision['active_horizon_label']}</b><br>
                Toplam {dashboard_decision['sale_plan']['daily_units']} birim satış önerilir;
                {dashboard_decision['sale_plan']['morning_units']} birim sabah,
                {dashboard_decision['sale_plan']['afternoon_units']} birim öğleden sonra uygulanabilir.
            </div>
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
    visible_keys = ["DXY", "Faiz", "Risk", "Teknik", "Form", "Volatilite", "MacroRisk", "Positioning", "SpreadMomentum", "CrossAsset"]
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

extra1, extra2 = st.columns(2)

with extra1:
    st.markdown('<div class="panel-card">', unsafe_allow_html=True)
    st.markdown("### Positioning")
    cot = d.get("cot_positioning") or {}
    st.metric("Net % OI", fmt_num(cot.get("net_pct_open_interest"), 2, "%"))
    weekly_change = cot.get("weekly_change_contracts")
    st.metric("Haftalık Değişim", f"{int(weekly_change):+d}" if weekly_change is not None else "N/A")
    st.caption(f"COT tarih: {cot.get('report_date') or 'N/A'}")
    st.markdown('</div>', unsafe_allow_html=True)

with extra2:
    st.markdown('<div class="panel-card">', unsafe_allow_html=True)
    st.markdown("### Cross Asset")
    ca = d.get("cross_asset") or {}
    st.metric("S&P 5G", fmt_num(ca.get("spx_ret_5"), 2, "%"))
    st.metric("Gold 5G", fmt_num(ca.get("gold_ret_5"), 2, "%"))
    st.metric("Spread Mom. 5G", fmt_num(d.get("spread_2y_momentum_5"), 2, "%"))
    st.markdown('</div>', unsafe_allow_html=True)

st.markdown('<div class="panel-card">', unsafe_allow_html=True)
st.markdown("### Veri Kaynakları")
source_rows = [
    ("DXY", d.get("dxy_source", "N/A")),
    ("US 2Y", d.get("us2y_source", "N/A")),
    ("US 10Y", d.get("us10y_source", "N/A")),
    ("DE 2Y", d.get("de2y_source", "N/A")),
    ("DE 10Y", d.get("de10y_source", "N/A")),
    ("COT", f"{d.get('cot_source') or 'N/A'} / {d.get('cot_status') or 'N/A'}"),
    ("Makro", f"{d.get('macro_source') or 'N/A'} / {d.get('macro_status') or 'N/A'}"),
]
for label, value in source_rows:
    st.write(f"**{label}:** {value}")
st.markdown('</div>', unsafe_allow_html=True)

# FORECAST PANELİ
st.markdown("---")
st.markdown("## İstatistiksel Tahmin Paneli")

forecast = d.get("forecast", {})
st.markdown('<div class="panel-card">', unsafe_allow_html=True)
st.write(forecast.get("summary", "Tahmin üretilemedi."))

forecast_horizons = forecast.get("horizons", {})
if forecast_horizons:
    fcols = st.columns(4)
    for i, h in enumerate([1, 3, 5, 10]):
        item = forecast_horizons.get(h)
        if not item:
            continue
        with fcols[i]:
            st.metric(f"{h} Gün", f"{item['direction']} %{item['probability']}")
            st.caption(f"CI: %{item['ci_lower']:.0f}-%{item['ci_upper']:.0f} | n={item['sample_size']}")
else:
    st.warning("İstatistiksel yön tahmini için yeterli benzer dönem bulunamadı.")
st.markdown('</div>', unsafe_allow_html=True)

# HİBRİT PERFORMANS PANELİ
st.markdown("---")
st.markdown("## Hibrit Model Performans Raporu")

hybrid_perf = d.get("hybrid_performance", {})
st.markdown('<div class="panel-card">', unsafe_allow_html=True)
st.write(hybrid_perf.get("summary", "Performans raporu üretilemedi."))

models = hybrid_perf.get("models", {})
if models:
    perf_cols = st.columns(3)
    model_order = [
        ("rule_based", "Kural"),
        ("forecast", "Forecast"),
        ("hybrid", "Hybrid"),
    ]
    for i, (key, label) in enumerate(model_order):
        model = models.get(key, {})
        with perf_cols[i]:
            st.metric(label, f"%{model.get('overall_accuracy', 0)}")
            h_parts = []
            for horizon in [1, 3, 5, 10]:
                item = model.get("horizons", {}).get(horizon, {})
                if item.get("n_predictions", 0) > 0:
                    h_parts.append(f"{horizon}G %{item.get('accuracy', 0)}")
            st.caption(" | ".join(h_parts) if h_parts else "Horizon verisi yok")
            calib = model.get("calibration", {})
            if calib:
                st.caption(calib.get("summary", "Calibration yok"))
else:
    st.warning("Performans karşılaştırması için yeterli tarihsel veri yok.")
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

l1, l2, l3 = st.columns(3)

with l1:
    render_metric_card(
        "Ortalama EDE",
        f"{treasury_metrics['avg_ede']}",
        sub="Loglanan kararlar bazlı"
    )

with l2:
    render_metric_card(
        "Ortalama Veri Güveni",
        f"{treasury_metrics['avg_data_quality']}/100",
        sub="Karar kalitesi göstergesi"
    )

with l3:
    render_metric_card(
        "Yüksek Güven Oranı",
        f"%{treasury_metrics['high_confidence_rate']}",
        sub="Confidence=Yüksek gün oranı"
    )

st.markdown('<div class="panel-card">', unsafe_allow_html=True)
st.markdown("### Son 30 Gün Factor Katkı Özeti")
st.write(factor_summary.get("summary", "Factor özeti yok."))

leaders = factor_summary.get("leaders", [])
if leaders:
    fcols = st.columns(len(leaders))
    for i, item in enumerate(leaders):
        with fcols[i]:
            st.metric(item["label"], f"{item['avg_score']}", f"{item['deviation']:+.1f}")
            st.caption(f"Yüksek gün: {item['high_days']} | Düşük gün: {item['low_days']}")
else:
    st.caption("Yeterli log birikmediğinde bu alan boş kalabilir.")
st.markdown('</div>', unsafe_allow_html=True)

st.markdown('<div class="panel-card">', unsafe_allow_html=True)
st.markdown("### Son Kararlar ve Operasyon Geçmişi")

if not log_df.empty:
    display_cols = [
        "timestamp", "active_horizon_label", "ede", "trend", "spot",
        "data_quality_score", "daily_units", "morning_units", "afternoon_units", "decision"
    ]
    for col in display_cols:
        if col not in log_df.columns:
            log_df[col] = None
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
