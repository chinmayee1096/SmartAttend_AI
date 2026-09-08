import streamlit as st
import pandas as pd
from datetime import date,time
from smart_attendance.services import admin_service as admin,timetable_service as timetable


def show(token):
    st.header('Timetable')
    rows=timetable.list_timetable(token)
    st.dataframe(pd.DataFrame(rows),width='stretch',hide_index=True)
    from smart_attendance.utils.security import current_user
    if current_user(token)['role']!='ADMIN': return
    c=admin.catalogue(token)
    if not c['subjects'] or not c['faculty']:
        st.info('Add a subject and a faculty account in Settings before creating a class.')
        return
    with st.form('timetable'):
        d=st.selectbox('Department',c['departments'],format_func=lambda r:r['name'])
        sec=st.selectbox('Section',c['sections'],format_func=lambda r:r['name'])
        semester=st.number_input('Semester',1,12,1)
        subject=st.selectbox('Subject',c['subjects'],format_func=lambda r:r['code']+' · '+r['name'])
        faculty=st.selectbox('Faculty',c['faculty'],format_func=lambda r:r['name'])
        weekday=st.selectbox('Day',range(7),format_func=lambda n:['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'][n])
        start=st.time_input('Start time',time(9)); end=st.time_input('End time',time(10))
        classroom=st.text_input('Classroom'); period=st.text_input('Period',value='Period1')
        since=st.date_input('Effective from',date.today()); until=st.date_input('Effective until',date(date.today().year,12,31))
        if st.form_submit_button('Save class'):
            timetable.save_timetable(token,d['id'],sec['id'],semester,subject['id'],faculty['id'],weekday,start.isoformat(),end.isoformat(),classroom,period,since.isoformat(),until.isoformat())
            st.success('Class saved.'); st.rerun()
    if rows:
        retire=st.selectbox('Retire timetable entry',rows,format_func=lambda r:f"{r['id']} · {r['subject']} · {r['period']}")
        if st.button('Retire selected entry'): timetable.deactivate(token,retire['id']); st.rerun()
