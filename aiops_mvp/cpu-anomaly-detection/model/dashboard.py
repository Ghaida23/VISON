import numpy as np
import pandas as pd
import joblib
import streamlit as st
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
from pathlib import Path

# =========================================================
# 0) إعداد المسارات (Paths)
# =========================================================
THIS_DIR = Path(__file__).resolve().parent          # model/
PROJECT_ROOT = THIS_DIR.parent                      # cpu-anomaly-detection/
MODEL_FILE = THIS_DIR / "cpu_anomaly_iso_forest.pkl"
DATA_FILE = PROJECT_ROOT / "data" / "ec2_cpu_utilization_24ae8d.csv"

# =========================================================
# 0.1) إعداد صفحة Streamlit
# =========================================================
st.set_page_config(
    page_title="ITOps Hub – لوحة مراقبة أعطال CPU",
    layout="wide"
)

# =========================================================
# 0.2) تنسيق الألوان (أخضر + أبيض قريب من ثيم أبشر)
# =========================================================
ABSHEER_DARK = "#021A11"   # خلفية رئيسية داكنة
ABSHEER_SIDEBAR = "#041F16"
ABSHEER_PRIMARY = "#00C38A"  # أخضر مميز
TEXT_COLOR = "#FFFFFF"

custom_css = f"""
<style>
/* خلفية التطبيق */
[data-testid="stAppViewContainer"] {{
    background-color: {ABSHEER_DARK};
}}

/* خلفية الـ Sidebar */
[data-testid="stSidebar"] {{
    background-color: {ABSHEER_SIDEBAR};
}}

/* نصوص عامة */
h1, h2, h3, h4, h5, h6, p, span, label, .stMetric, .st-emotion-cache-10trblm {{
    color: {TEXT_COLOR} !important;
}}

.st-emotion-cache-1kyxreq {{
    color: {TEXT_COLOR} !important;
}}

/* صندوق info في الأسفل */
.stAlert {{
    background-color: #06241A;
    border-radius: 12px;
}}
</style>
"""
st.markdown(custom_css, unsafe_allow_html=True)

# =========================================================
# 1) تحميل المودل والـ scaler
# =========================================================
@st.cache_resource
def load_model():
    # نستخدم المسار الصحيح لملف المودل داخل model/
    artifacts = joblib.load(MODEL_FILE)
    model = artifacts["model"]
    scaler = artifacts["scaler"]
    feature_cols = artifacts["feature_cols"]
    return model, scaler, feature_cols

iso_forest, scaler, feature_cols = load_model()

# =========================================================
# 2) تحميل بيانات CPU الحقيقية + توليد بيانات تجريبية
# =========================================================
def load_base_cpu_series():
    df = pd.read_csv("data/ec2_cpu_utilization_24ae8d.csv")
    cpu = df["value"].values
    return cpu[:500]

def generate_fake_cpu_data(n_points=100, with_anomalies=True, anomaly_ratio=0.05):
    df_base = load_base_cpu_series()

    if n_points >= len(df_base):
        window = df_base.copy()
    else:
        start_idx = np.random.randint(0, len(df_base) - n_points)
        window = df_base[start_idx:start_idx + n_points]

    values = window.copy()
    anomaly_threshold = 0.22

    if not with_anomalies:
        normal_low, normal_high = 0.13, 0.18
        for i, v in enumerate(values):
            if v > anomaly_threshold:
                values[i] = np.random.uniform(normal_low, normal_high)
    else:
        current_anom_idx = np.where(values > anomaly_threshold)[0]
        target_anom = max(1, int(n_points * anomaly_ratio))
        missing = max(0, target_anom - len(current_anom_idx))
        if missing > 0:
            extra_idx = np.random.choice(range(n_points), size=missing, replace=False)
            for idx in extra_idx:
                values[idx] = np.random.uniform(0.35, 0.9)

    start_time = datetime.now() - timedelta(minutes=5 * n_points)
    timestamps = [start_time + timedelta(minutes=5 * i) for i in range(n_points)]

    df = pd.DataFrame({
        "timestamp": timestamps,
        "value": values
    })
    return df


# =========================================================
# 3) Feature Engineering نفس اللي بالمودل
# =========================================================
def add_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # المتوسط المتحرك لـ 12 نقطة
    df["rolling_mean_12"] = df["value"].rolling(window=12, min_periods=1).mean()

    # الانحراف المعياري (أول قيم ممكن تكون NaN)
    df["rolling_std_12"] = df["value"].rolling(window=12, min_periods=2).std()

    # الفرق بين كل نقطة والتي قبلها
    df["diff_1"] = df["value"].diff()

    # تعويض أي NaN بقيم آمنة
    df["rolling_std_12"] = df["rolling_std_12"].fillna(0)
    df["diff_1"] = df["diff_1"].fillna(0)

    return df

# =========================================================
# 4) دالة التنبؤ باستخدام المودل
# =========================================================
def predict_anomalies(df_raw: pd.DataFrame) -> pd.DataFrame:
    df_feat = add_features(df_raw)

    # اختيار الأعمدة اللي تدرب عليها المودل
    X = df_feat[feature_cols].copy()

    # احتياط: تعويض أي NaN بصفر
    X = X.fillna(0)

    # نفس الـ scaler المحفوظ
    X_scaled = scaler.transform(X.values)

    # المودل يرجّع 1 (طبيعي) أو -1 (شاذ)
    preds = iso_forest.predict(X_scaled)

    df_feat["prediction"] = preds
    return df_feat

# =========================================================
# 5) الهيدر + اللوقو
# =========================================================
header_col_logo, header_col_title = st.columns([1, 5])

with header_col_logo:
    st.image("model/logo.png", width=130)   # اللوقو في نفس فولدر model

with header_col_title:
    st.markdown(
        """
        ### ITOps Hub – لوحة مراقبة أعطال CPU  
        لوحة تجريبية توضّح كيف يمكن ربط نموذج **كشف الشذوذ** مع قراءات المعالجات
        في قسم تقنية المعلومات على منصة أبشر.
        """
    )

st.markdown("---")

# =========================================================
# 6) إعدادات الـ Sidebar
# =========================================================
st.sidebar.header("⚙️ إعدادات البيانات")

n_points = st.sidebar.slider(
    "عدد النقاط الزمنية",
    min_value=50,
    max_value=500,
    value=150,
    step=50
)

mode = st.sidebar.selectbox(
    "نوع السيناريو",
    ["بدون شذوذ (تشغيل طبيعي)", "مع شذوذ (ارتفاعات مفاجئة)"]
)

if mode == "بدون شذوذ (تشغيل طبيعي)":
    with_anomalies = False
    anomaly_ratio = 0.0
else:
    with_anomalies = True
    anomaly_ratio = st.sidebar.slider("نسبة الشذوذ من البيانات", 0.01, 0.3, 0.05)

# =========================================================
# 7) توليد البيانات + التنبؤ
# =========================================================
df_raw = generate_fake_cpu_data(
    n_points=n_points,
    with_anomalies=with_anomalies,
    anomaly_ratio=anomaly_ratio
)

df_pred = predict_anomalies(df_raw)

# =========================================================
# 8) KPIs أعلى الداشبورد
# =========================================================
col1, col2, col3 = st.columns(3)

total_points = len(df_pred)
n_anomalies = int((df_pred["prediction"] == -1).sum())
last_anom_time = df_pred.loc[df_pred["prediction"] == -1, "timestamp"].max()

with col1:
    st.metric("عدد القراءات", total_points)

with col2:
    st.metric("عدد حالات الشذوذ المكتشفة", n_anomalies)

with col3:
    if pd.isna(last_anom_time):
        st.metric("آخر وقت تم فيه اكتشاف شذوذ", "لا يوجد")
    else:
        st.metric(
            "آخر وقت تم فيه اكتشاف شذوذ",
            last_anom_time.strftime("%Y-%m-%d %H:%M")
        )

# =========================================================
# 9) جدول آخر 30 قراءة
# =========================================================
st.subheader("📄 جدول القراءات مع التنبؤ (آخر 30 نقطة):")

st.dataframe(
    df_pred[["timestamp", "value", "rolling_mean_12", "rolling_std_12", "diff_1", "prediction"]]
      .tail(30)
      .rename(columns={
          "timestamp": "الوقت",
          "value": "قيمة CPU",
          "rolling_mean_12": "المتوسط المتحرك",
          "rolling_std_12": "الانحراف المعياري",
          "diff_1": "التغير عن القراءة السابقة",
          "prediction": "حالة القراءة (1 طبيعي / -1 شاذ)"
      })
)

# =========================================================
# 10) الرسم البياني للشذوذ
# =========================================================
st.subheader("📈 مخطط قراءات CPU مع تمييز الشذوذ")

fig, ax = plt.subplots(figsize=(11, 4))

# خط القيم الأساسية
ax.plot(
    df_pred["timestamp"],
    df_pred["value"],
    marker="o",
    linewidth=1,
    color=ABSHEER_PRIMARY,
    label="CPU value"
)

# نقاط طبيعية / شاذة
normal_points = df_pred[df_pred["prediction"] == 1]
anom_points   = df_pred[df_pred["prediction"] == -1]

# نقاط طبيعية
ax.scatter(
    normal_points["timestamp"],
    normal_points["value"],
    s=25,
    color="#4CAF50",
    label="Normal"
)

# نقاط شاذة: نرسمها فقط لو موجودة
if len(anom_points) > 0:
    ax.scatter(
        anom_points["timestamp"],
        anom_points["value"],
        s=60,
        color="#FF5252",
        label="Anomaly"
    )

ax.set_xlabel("Time", color=TEXT_COLOR)
ax.set_ylabel("CPU Utilization", color=TEXT_COLOR)
ax.tick_params(axis='x', colors=TEXT_COLOR, rotation=20)
ax.tick_params(axis='y', colors=TEXT_COLOR)

ax.grid(True, linestyle="--", linewidth=0.5, alpha=0.3)
ax.set_facecolor("#03130E")

ax.legend(facecolor="#03130E", edgecolor="none", labelcolor=TEXT_COLOR)
fig.tight_layout()

st.pyplot(fig)

# =========================================================
# 11) ملاحظة توضيحية
# =========================================================
st.info(
    "🧪 ملاحظة: البيانات في هذه اللوحة تجريبية (خيالية) فقط لشرح الفكرة؛ "
    "في النسخة الحقيقية يتم قراءة بيانات CPU من أنظمة المراقبة في قسم تقنية المعلومات "
    "ثم تمريرها على نموذج كشف الشذوذ وعرض النتائج لحظياً عبر ITOps Hub."
)
