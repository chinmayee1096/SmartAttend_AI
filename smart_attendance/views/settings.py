import streamlit as st
import pandas as pd
from smart_attendance.services import admin_service as service


def show(token):
    st.header('Settings')
    cfg=service.settings(token); c=service.catalogue(token)
    with st.form('settings'):
        cfg['institution']=st.text_input('Institution name',cfg['institution'])
        for key,label,low,high in [('late_minutes','Late threshold (minutes)',0.,60.),('minimum_percentage','Minimum attendance (%)',1.,100.),('good_percentage','Good attendance (%)',1.,100.),('presence_ratio','Required presence fraction',.1,1.),('observation_gap_seconds','Maximum credited observation gap (seconds)',1.,300.),('lbph_distance','Maximum LBPH distance (lower is stricter)',1.,100.),('embedding_similarity','Minimum embedding cosine similarity',.1,1.)]:
            cfg[key]=st.number_input(label,low,high,float(cfg[key]))
        cfg['camera_index']=int(st.number_input('Default camera index',0,5,int(cfg['camera_index'])))
        cfg['liveness_required']=st.checkbox('Require liveness before attendance',cfg['liveness_required'])
        cfg['email_enabled']=st.checkbox('Enable email delivery',cfg['email_enabled'])
        if st.form_submit_button('Save settings'): service.save_settings(token,cfg); st.success('Settings saved.')
    st.subheader('Accounts')
    st.dataframe(pd.DataFrame(c['users']),hide_index=True,width='stretch')
    with st.form('account'):
        username=st.text_input('Username'); password=st.text_input('Initial password',type='password')
        role=st.selectbox('Role',['FACULTY','STUDENT','HOD','ADMIN'])
        dept=st.selectbox('Account department',c['departments'],format_func=lambda r:r['name'])
        people=service.students(token)
        student=st.selectbox('Linked student',[None]+people,format_func=lambda r:'Not linked' if r is None else r['roll']+' · '+r['name'])
        faculty_options=[None]+[f for f in c['faculty'] if f['user_id'] is None]
        faculty=st.selectbox('Linked faculty profile',faculty_options,format_func=lambda r:'Create from username' if r is None else r['name'])
        if st.form_submit_button('Create account'):
            service.create_user(token,username,password,role,dept['id'],student['id'] if student else None,faculty['id'] if faculty else None); st.success('Account created.'); st.rerun()
    with st.form('catalogue'):
        kind=st.selectbox('Add catalogue entry',['subjects','departments','sections']); name=st.text_input('Name'); code=st.text_input('Subject code')
        if st.form_submit_button('Add entry'): service.add_catalogue(token,kind,name,code); st.rerun()
