
import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import math
import json
from datetime import date, timedelta
import extra_streamlit_components as stx

# --- 페이지 기본 설정 (모바일 최적화) ---
st.set_page_config(page_title="SOLID: Soxl Hybrid Strategy", layout="wide", initial_sidebar_state="collapsed")
st.title("SOLID: Soxl Hybrid Strategy")

# --- 모바일 '당겨서 새로고침' 방지 CSS ---
st.markdown("""
    <style>
        body, .stApp { overscroll-behavior-y: none; }
    </style>
""", unsafe_allow_html=True)

# --- 세션 상태 초기화 ---
if 'capital_flows' not in st.session_state:
    st.session_state['capital_flows'] = []
if 'run_backtest' not in st.session_state:
    st.session_state['run_backtest'] = False
if 'bt_params' not in st.session_state:
    st.session_state['bt_params'] = None   # 백테스트 실행용 파라미터 스냅샷
if 'pending_cookie' not in st.session_state:
    st.session_state['pending_cookie'] = None  # 저장 대기중인 쿠키 JSON

# --- 쿠키 매니저 초기화 (캐시 인자 제거: 최신 Streamlit 크래시 방지) ---
# 캐시 안에서 위젯 생성은 권장되지 않으므로 직접 생성한다.
cookie_manager = stx.CookieManager(key="cm")
cookies = cookie_manager.get_all()

# 프론트엔드 통신이 완료되지 않아 쿠키가 None일 경우 대기(stop)
if cookies is None:
    st.stop()

# --- 저장 대기중인 쿠키가 있으면 이번 런에서 실제로 기록 (set 타이밍 안정화) ---
if st.session_state['pending_cookie'] is not None:
    cookie_manager.set("solid_config", st.session_state['pending_cookie'], key="set_solid_config")
    st.session_state['pending_cookie'] = None

# --- 단일 JSON 쿠키에서 파라미터 로드 ---
saved_config_str = cookie_manager.get("solid_config")
saved_config = {}
if saved_config_str:
    try:
        saved_config = json.loads(saved_config_str)
    except:
        pass

def get_param(param_name, default_val, cast_type):
    # 1. URL 파라미터 우선
    val = st.query_params.get(param_name)
    if val is not None:
        try: return cast_type(val)
        except: pass
    # 2. JSON 쿠키 데이터 확인
    if param_name in saved_config:
        try:
            if cast_type == date.fromisoformat:
                return date.fromisoformat(saved_config[param_name])
            return cast_type(saved_config[param_name])
        except: pass
    # 3. 기본값 반환
    return default_val

# --- 초기 파라미터 세팅 ---
default_start = get_param("start", date(2026, 6, 30), date.fromisoformat)
default_cash = get_param("cash", 100000.0, float)
default_slippage = get_param("slippage", 0.1, float)

default_x_frac = get_param("x_frac", 35.0, float)
default_k_frac = get_param("k_frac", 12.5, float)
default_c_limit = get_param("c_limit", 7, int)
default_tp_rate = get_param("tp_rate", 6.0, float)

default_buy0 = get_param("buy0", 5.0, float)
default_buy1 = get_param("buy1", -1.0, float)
default_buy2 = get_param("buy2", -10.0, float)
default_moc = get_param("moc", 24, int)

default_rsi_buy = get_param("rsi_buy", 22.0, float)
default_rsi_sell = get_param("rsi_sell", 25.0, float)
default_rsi_split = get_param("rsi_split", 2, int)
default_rsi_moc = get_param("rsi_moc", 10, int)


# 1. 기본 설정 및 입출금 기록
with st.expander("📝 1. 기본 설정 및 입출금 기록 (터치하여 열기)", expanded=True):
    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("백테스트 시작일", default_start)
        INIT_CASH = st.number_input("초기 자본 ($)", min_value=1000.0, value=default_cash, step=1000.0)
    with col2:
        end_date = st.date_input("오늘(종료일)", date.today())
        ui_slippage = st.number_input("슬리피지 (%)", value=default_slippage, step=0.05, help="매수/매도 체결 시 발생하는 호가 오차 (기본 0.1%)")
        
    st.query_params["start"] = start_date.strftime("%Y-%m-%d")
    st.query_params["cash"] = INIT_CASH
    st.query_params["slippage"] = ui_slippage
    
    st.markdown("---")
    st.markdown("**💰 추가 입출금 내역 (자본 출입)**")
    
    with st.form("flow_form"):
        f_col1, f_col2 = st.columns(2)
        with f_col1:
            f_date = st.date_input("입출금 날짜", date.today())
        with f_col2:
            f_amt = st.number_input("금액 ($) (출금은 마이너스)", value=0.0, step=100.0)
        
        submitted = st.form_submit_button("내역 추가하기")
        if submitted and f_amt != 0:
            st.session_state['capital_flows'].append({'Date': f_date, 'Amount': f_amt})
            st.success(f"{f_date} 일자에 {f_amt:,.0f} 달러 기록 완료!")

    if st.session_state['capital_flows']:
        flow_df = pd.DataFrame(st.session_state['capital_flows'])
        st.dataframe(flow_df, use_container_width=True)
        if st.button("내역 전체 초기화"):
            st.session_state['capital_flows'] = []
            st.rerun()

# 2. 하이브리드 전략 파라미터 설정
with st.expander("⚙️ 2. 하이브리드 전략 파라미터 설정 (고급)", expanded=False):
    st.markdown("##### 📌 Main 전략 설정")
    p_col1, p_col2 = st.columns(2)
    with p_col1:
        ui_x_frac = st.number_input("초기 진입 비중 (%)", value=default_x_frac, step=1.0, help="Main 전략의 첫 진입 자산 비중")
        ui_k_frac = st.number_input("추가 매수 비중 (%)", value=default_k_frac, step=0.5, help="투입된 자금 대비 1회 물타기 비중")
        ui_c_limit = st.number_input("추가 매수 횟수 (회)", value=default_c_limit, step=1, help="Main 전략의 최대 물타기 허용 횟수")
        ui_tp_rate = st.number_input("익절율 (%)", value=default_tp_rate, step=0.5, help="마지막 매수 체결가 대비 목표 수익률")
    with p_col2:
        ui_buy0 = st.number_input("매수0 경계 (%)", value=default_buy0, step=0.5, help="첫 진입 시 전일 종가 대비 LOC 위치 (기본 5%)")
        ui_buy1 = st.number_input("매수1 경계 (%)", value=default_buy1, step=0.5, help="1차 물타기 시 전일 종가 대비 LOC 위치 (기본 -1%)")
        ui_buy2 = st.number_input("매수2 경계 (%)", value=default_buy2, step=0.5, help="2차 물타기 시 전일 종가 대비 LOC 위치 (기본 -10%)")
        ui_moc = st.number_input("MOC (최대 보유일)", value=default_moc, step=1, help="Main 전략 진입 후 강제 청산 기한 (기본 24일)")

    st.markdown("---")
    st.markdown("##### 📌 RSI 전략 설정")
    p_col3, p_col4 = st.columns(2)
    with p_col3:
        ui_rsi_buy = st.number_input("RSI 매수 기준", value=default_rsi_buy, step=1.0, help="RSI가 이 수치 이하일 때 진입 (기본 22)")
        ui_rsi_split = st.number_input("RSI 분할 횟수 (회)", value=default_rsi_split, step=1, help="RSI 할당 예산 분할 진입 횟수 (기본 2)")
    with p_col4:
        ui_rsi_sell = st.number_input("RSI 매도 기준", value=default_rsi_sell, step=1.0, help="RSI가 이 수치 이상일 때 익절 (기본 25)")
        ui_rsi_moc = st.number_input("RSI MOC (최대 보유일)", value=default_rsi_moc, step=1, help="RSI 전략 진입 후 강제 청산 기한 (기본 10일)")
        
    st.query_params["x_frac"] = ui_x_frac
    st.query_params["k_frac"] = ui_k_frac
    st.query_params["c_limit"] = ui_c_limit
    st.query_params["tp_rate"] = ui_tp_rate
    st.query_params["buy0"] = ui_buy0
    st.query_params["buy1"] = ui_buy1
    st.query_params["buy2"] = ui_buy2
    st.query_params["moc"] = ui_moc
    
    st.query_params["rsi_buy"] = ui_rsi_buy
    st.query_params["rsi_sell"] = ui_rsi_sell
    st.query_params["rsi_split"] = ui_rsi_split
    st.query_params["rsi_moc"] = ui_rsi_moc

run_button = st.button("🚀 매매표 생성 및 백테스트 실행", type="primary", use_container_width=True)

if run_button:
    # 💡 1. 현재 입력값을 '스냅샷'으로 세션에 저장 (매 조작마다 재실행 방지)
    st.session_state['bt_params'] = {
        "start_date": start_date,
        "end_date": end_date,
        "INIT_CASH": INIT_CASH,
        "ui_slippage": ui_slippage,
        "ui_x_frac": ui_x_frac,
        "ui_k_frac": ui_k_frac,
        "ui_c_limit": ui_c_limit,
        "ui_tp_rate": ui_tp_r
