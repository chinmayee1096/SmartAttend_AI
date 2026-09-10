"""Presentation only: SmartAttend's reference palette and reusable page headings."""
from datetime import datetime
from html import escape
from pathlib import Path
import streamlit as st
from smart_attendance.utils.time_utils import system_now


def apply_theme():
    css=Path(__file__).with_name('theme.css').read_text(encoding='utf-8')
    st.markdown('<style>'+css+'</style>',unsafe_allow_html=True)


def brand():
    mark = Path(__file__).resolve().parents[1] / "assets" / "smartattend_mark.png"
    if mark.exists():
        icon, wordmark = st.sidebar.columns([0.42, 0.58], gap="small", vertical_alignment="center")
        with icon:
            st.image(str(mark), width=78)
        with wordmark:
            st.markdown(
                '''<div class="sa-native-brand"><strong>SmartAttend<span> AI</span></strong>
                <small>SMARTER ATTENDANCE</small></div>''',
                unsafe_allow_html=True,
            )
    else:
        st.sidebar.markdown('''<div class="sa-brand"><div class="sa-mark">S<span> A</span></div>
        <div><strong>SmartAttend<span> AI</span></strong><small>INTELLIGENT ATTENDANCE</small></div></div>''',unsafe_allow_html=True)


def heading(eyebrow,title,description):
    st.markdown(f'''<div class="sa-heading"><div class="sa-eyebrow">{escape(eyebrow)}</div>
    <h1>{escape(title)}</h1><p>{escape(description)}</p></div>''',unsafe_allow_html=True)


def topbar():
    st.markdown(f'''<div class="sa-topbar"><span>WORKSPACE <span class="sa-divider">/</span> CAMPUS OPERATIONS</span>
    <span class="sa-date">{system_now().strftime('%a, %d %b %Y · %H:%M IST')}</span></div>''',unsafe_allow_html=True)


def overview(base):
    """Read existing registries only. Do not infer attendance percentages."""
    import csv
    count=0
    for file in base.glob('*/*/students.csv'):
        try:
            with file.open(encoding='utf-8-sig',newline='') as handle:
                count+=sum(bool(row.get('roll_number')) for row in csv.DictReader(handle))
        except (OSError,UnicodeError,csv.Error):
            continue
    models=sum(1 for _ in base.glob('*/*/trainer.yml'))
    reports=sum(1 for _ in (base/'reports').glob('*_attendance.csv'))
    st.markdown(f'''<div class="sa-stats">
    <div class="sa-stat"><span>REGISTERED STUDENTS</span><strong>{count:02d}</strong><small>Across your departments</small></div>
    <div class="sa-stat"><span>TRAINED SECTIONS</span><strong>{models:02d}</strong><small>Saved recognition models</small></div>
    <div class="sa-stat"><span>ATTENDANCE REPORTS</span><strong>{reports:02d}</strong><small>Available in your records</small></div>
    </div>''',unsafe_allow_html=True)


def camera_idle():
    st.markdown('''<div class="sa-camera-idle"><div class="sa-camera-symbol">◉</div>
    <strong>Your camera workspace</strong><p>Start recognition to view the live feed.<br>Use preview mode to check recognition without recording attendance.</p>
    <span>CAMERA STANDBY</span></div>''',unsafe_allow_html=True)
