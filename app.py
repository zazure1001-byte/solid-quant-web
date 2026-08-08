import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import math
from datetime import date, timedelta

# --- 페이지 기본 설정 (모바일 최적화) ---
st.set_page_config(page_title="SOLID: Soxl Hybrid Strategy", layout="wide", initial_sidebar_state="collapsed")
st.title("SOLID: Soxl Hybrid Strategy")

# --- 세션 상태 초기화 (자본 출입 기록용) ---
if 'capital_flows' not in st.session_state:
    st.session_state['capital_flows'] = []

# --- 구역 A: 사용자 입력부 (URL 맞춤형 파라미터 적용) ---
query_params = st.query_params

# URL 기존 설정값 불러오기
default_start_str = query_params.get("start", "2025-01-01")
try: default_start = date.fromisoformat(default_start_str)
except: default_start = date(2025, 1, 1)

try: default_cash = float(query_params.get("cash", 100000.0))
except: default_cash = 100000.0

# 전략 파라미터 URL 불러오기
try: default_x_frac = float(query_params.get("x_frac", 35.0))
except: default_x_frac = 35.0

try: default_k_frac = float(query_params.get("k_frac", 12.5))
except: default_k_frac = 12.5

try: default_c_limit = int(query_params.get("c_limit", 7))
except: default_c_limit = 7

try: default_tp_rate = float(query_params.get("tp_rate", 6.0))
except: default_tp_rate = 6.0

try: default_buy0 = float(query_params.get("buy0", 5.0))
except: default_buy0 = 5.0

try: default_buy1 = float(query_params.get("buy1", -1.0))
except: default_buy1 = -1.0

try: default_buy2 = float(query_params.get("buy2", -10.0))
except: default_buy2 = -10.0

try: default_moc = int(query_params.get("moc", 24))
except: default_moc = 24

try: default_rsi_buy = float(query_params.get("rsi_buy", 22.0))
except: default_rsi_buy = 22.0

try: default_rsi_sell = float(query_params.get("rsi_sell", 25.0))
except: default_rsi_sell = 25.0

try: default_rsi_split = int(query_params.get("rsi_split", 2))
except: default_rsi_split = 2

try: default_rsi_moc = int(query_params.get("rsi_moc", 10))
except: default_rsi_moc = 10


# 1. 기본 설정 및 입출금 기록
with st.expander("📝 1. 기본 설정 및 입출금 기록 (터치하여 열기)", expanded=True):
    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("백테스트 시작일", default_start)
        INIT_CASH = st.number_input("초기 자본 ($)", min_value=1000.0, value=default_cash, step=1000.0)
    with col2:
        end_date = st.date_input("오늘(종료일)", date.today())
        
    st.query_params["start"] = start_date.strftime("%Y-%m-%d")
    st.query_params["cash"] = INIT_CASH
    
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

# --- 보조지표 계산 함수 ---
def calculate_rsi_components(series, period=2):
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ema_up = up.ewm(com=period-1, adjust=False).mean()
    ema_down = down.ewm(com=period-1, adjust=False).mean()
    rs = ema_up / ema_down
    rsi = 100 - (100 / (1 + rs))
    return rsi, ema_up, ema_down

# --- 데이터 로드 함수 ---
@st.cache_data(show_spinner=False)
def load_market_data(start, end):
    data_start = start - timedelta(days=90)
    data_end = end + timedelta(days=1)
    
    df_soxl = yf.download("SOXL", start=data_start, end=data_end, auto_adjust=True, progress=False)
    df_soxx = yf.download("SOXX", start=data_start, end=data_end, auto_adjust=True, progress=False)
    
    if isinstance(df_soxl.columns, pd.MultiIndex):
        df_soxl.columns = df_soxl.columns.get_level_values(0)
        df_soxx.columns = df_soxx.columns.get_level_values(0)
        
    df = pd.DataFrame({
        'SOXL_Close': df_soxl['Close'],
        'SOXX_Close': df_soxx['Close']
    }).dropna().sort_index()
    
    rsi_series, ema_up, ema_down = calculate_rsi_components(df['SOXX_Close'], period=2)
    df['SOXX_RSI'] = rsi_series
    df['SOXX_ema_up'] = ema_up
    df['SOXX_ema_down'] = ema_down
    
    return df.dropna().copy()

# --- 데이터프레임 스타일링 함수 ---
def bg_color_sections(col):
    no_color_cols = ["진행도", "거래일", "SOXL 종가"]
    green_cols = ["누적 실현 손익", "자산 손익률 (%)"]
    blue_cols = ["실현손익", "평가손익"]
    orange_cols = ["RSI 수량", "RSI 평단", "RSI 매도일", "RSI 수익금", "RSI 손익률", "입출금"]
    
    if col.name in no_color_cols:
        return [''] * len(col)
    elif col.name in green_cols:
        return ['background-color: rgba(165, 214, 167, 0.4)'] * len(col)
    elif col.name in blue_cols:
        return ['background-color: rgba(173, 216, 230, 0.3)'] * len(col)
    elif col.name in orange_cols:
        return ['background-color: rgba(255, 152, 0, 0.15)'] * len(col)
    else:
        return ['background-color: rgba(255, 235, 59, 0.15)'] * len(col)

def color_profit(val):
    if pd.isna(val) or val == "":
        return ""
    try:
        num = float(str(val).replace('%', '').replace(',', '').replace('$', ''))
        if num > 0:
            return 'color: #E74C3C; font-weight: bold;' # 붉은색
        elif num < 0:
            return 'color: #3498DB; font-weight: bold;' # 푸른색
    except:
        pass
    return ''

def highlight_progress(val):
    if val == 0:
        return 'background-color: #A9DFBF; color: black; font-weight: bold;'
    return ''

def style_order_table(row):
    if '매수' in str(row['구분 (매수/매도)']):
        return ['background-color: rgba(231, 76, 60, 0.2)'] * len(row)
    elif '매도' in str(row['구분 (매수/매도)']):
        return ['background-color: rgba(52, 152, 219, 0.2)'] * len(row)
    return [''] * len(row)

def to_2_decimals(val):
    if isinstance(val, (int, float)) and not pd.isna(val):
        return f"{val:.2f}"
    return val

def to_pct_2_decimals(val):
    if isinstance(val, (int, float)) and not pd.isna(val):
        return f"{val:.2f}%"
    return val

# --- 메인 실행 로직 ---
if run_button:
    if start_date >= end_date:
        st.error("종료일이 시작일보다 빠를 수 없습니다.")
    else:
        with st.spinner("시장 데이터 동기화 및 기록장 작성 중..."):
            df = load_market_data(start_date, end_date)
            trade_start_idx = df.index.searchsorted(pd.to_datetime(start_date))
            
            if trade_start_idx >= len(df):
                st.error("선택한 시작일에 해당하는 시장 데이터가 없습니다. 조금 더 과거 날짜를 포함하거나 휴일 여부를 확인해주세요.")
            else:
                X_FRAC = ui_x_frac / 100.0      
                K_FRAC = ui_k_frac / 100.0     
                C_LIMIT = int(ui_c_limit)        
                TP_RATE = ui_tp_rate / 100.0     
                BUY0_MARGIN = ui_buy0 / 100.0
                BUY1_MARGIN = ui_buy1 / 100.0
                BUY2_MARGIN = ui_buy2 / 100.0
                MOC = int(ui_moc)
                
                RSI_BUY = ui_rsi_buy
                RSI_SELL = ui_rsi_sell
                RSI_SPLIT = int(ui_rsi_split)
                RSI_MOC = int(ui_rsi_moc)
                
                EXH_TP = 0.03      
                SLIPPAGE = 0.0     
                RSI_FRAC = 0.30    
                
                flows_dict = {}
                for f in st.session_state['capital_flows']:
                    d_str = f['Date'].strftime('%Y-%m-%d')
                    flows_dict[d_str] = flows_dict.get(d_str, 0.0) + f['Amount']
                
                cash = INIT_CASH
                total_net_investment = INIT_CASH
                
                main_shares, main_cycle_invested, main_last_buy_close = 0, 0.0, 0.0
                main_holding_days, main_add_buy_count = 0, 0
                
                rsi_shares, rsi_invested, rsi_buy_count, rsi_holding_days = 0, 0.0, 0, 0
                
                cum_realized = 0.0
                cycle_base_equity = INIT_CASH
                cycle_initial_buy_amt = INIT_CASH * X_FRAC
                latest_rsi_budget = INIT_CASH * RSI_FRAC
                active_rsi_budget = 0.0
                
                current_year = -1
                year_max_equity = INIT_CASH
                
                # 승률 계산용 카운터
                trade_count_main, trade_count_rsi = 0, 0
                main_win_count, main_loss_count = 0, 0
                rsi_win_count, rsi_loss_count = 0, 0
                
                daily_records = []
                max_equity = INIT_CASH

                for i in range(trade_start_idx, len(df)):
                    current_date = df.index[i].date()
                    if current_date > end_date:
                        break
                        
                    date_str = current_date.strftime('%Y-%m-%d')
                    
                    flow_today = flows_dict.get(date_str, 0.0)
                    if flow_today != 0:
                        cash += flow_today
                        total_net_investment += flow_today

                    curr_soxl = float(df['SOXL_Close'].iloc[i])
                    prev_soxl = float(df['SOXL_Close'].iloc[i-1]) if i > 0 else curr_soxl
                    
                    prev_soxx_ema_up = float(df['SOXX_ema_up'].iloc[i-1]) if i > 0 else float(df['SOXX_ema_up'].iloc[i])
                    prev_soxx_ema_down = float(df['SOXX_ema_down'].iloc[i-1]) if i > 0 else float(df['SOXX_ema_down'].iloc[i])
                    prev_soxx_close = float(df['SOXX_Close'].iloc[i-1]) if i > 0 else float(df['SOXX_Close'].iloc[i])
                    
                    curr_soxx_rsi = float(df['SOXX_RSI'].iloc[i])
                    
                    total_equity = cash + (main_shares + rsi_shares) * curr_soxl
                    if total_equity > max_equity: max_equity = total_equity
                    current_dd = ((total_equity / max_equity) - 1) * 100
                    
                    if current_date.year != current_year:
                        current_year = current_date.year
                        year_max_equity = total_equity
                    if total_equity > year_max_equity:
                        year_max_equity = total_equity
                    current_ydd = ((total_equity / year_max_equity) - 1) * 100

                    sell_main, sell_rsi = False, False
                    today_main_sell_date, today_main_profit, today_main_profit_rate = "", "", ""
                    today_rsi_sell_date, today_rsi_profit, today_rsi_profit_rate = "", "", ""
                    today_realized_profit = 0.0

                    if main_shares > 0:
                        main_holding_days += 1
                        if main_add_buy_count >= C_LIMIT:
                            sell_limit_tp = prev_soxl * (1 + EXH_TP)
                        else:
                            sell_limit_tp = main_last_buy_close * (1 + TP_RATE)
                            
                        if curr_soxl >= sell_limit_tp or main_holding_days >= MOC:
                            sell_main = True

                    if rsi_shares > 0:
                        rsi_holding_days += 1
                        if curr_soxx_rsi >= RSI_SELL or rsi_holding_days >= RSI_MOC:
                            sell_rsi = True

                    if sell_main:
                        exec_price = curr_soxl * (1 - SLIPPAGE)
                        sell_amount = main_shares * exec_price
                        profit = sell_amount - main_cycle_invested
                        profit_rate = (profit / main_cycle_invested * 100) if main_cycle_invested > 0 else 0
                        
                        today_main_sell_date = date_str
                        today_main_profit = round(profit, 2)
                        today_main_profit_rate = f"{profit_rate:.2f}%"
                        today_realized_profit += profit
                        
                        cash += sell_amount
                        trade_count_main += 1
                        
                        # 승률(익절/손절) 기록
                        if profit > 0:
                            main_win_count += 1
                        else:
                            main_loss_count += 1
                            
                        main_shares, main_holding_days, main_cycle_invested = 0, 0, 0.0
                        main_last_buy_close, main_add_buy_count = 0.0, 0

                    if sell_rsi:
                        exec_price = curr_soxl * (1 - SLIPPAGE)
                        sell_amount = rsi_shares * exec_price
                        profit = sell_amount - rsi_invested
                        profit_rate = (profit / rsi_invested * 100) if rsi_invested > 0 else 0
                        
                        today_rsi_sell_date = date_str
                        today_rsi_profit = round(profit, 2)
                        today_rsi_profit_rate = f"{profit_rate:.2f}%"
                        today_realized_profit += profit
                        
                        cash += sell_amount
                        trade_count_rsi += 1
                        
                        # 승률(익절/손절) 기록
                        if profit > 0:
                            rsi_win_count += 1
                        else:
                            rsi_loss_count += 1
                            
                        rsi_shares, rsi_invested, rsi_buy_count, rsi_holding_days = 0, 0.0, 0, 0
                        active_rsi_budget = 0.0

                    if not sell_main:
                        if main_shares == 0:
                            loc_limit_price = prev_soxl * (1 + BUY0_MARGIN)
                            if curr_soxl <= loc_limit_price:
                                cycle_base_equity = total_equity
                                latest_rsi_budget = total_equity * RSI_FRAC
                                cycle_initial_buy_amt = total_equity * X_FRAC
                                
                                buy_qty = round(cycle_initial_buy_amt / loc_limit_price)
                                
                                actual_ep = curr_soxl * (1 + SLIPPAGE)
                                if buy_qty * actual_ep > cash: 
                                    buy_qty = math.floor(cash / actual_ep)

                                if buy_qty > 0:
                                    cost = buy_qty * actual_ep
                                    main_shares += buy_qty
                                    cash -= cost
                                    main_cycle_invested = cost
                                    main_last_buy_close = curr_soxl
                                    main_holding_days, main_add_buy_count = 0, 0
                        else:
                            if main_add_buy_count < C_LIMIT:
                                loc_lim_1 = prev_soxl * (1 + BUY1_MARGIN)
                                loc_lim_2 = prev_soxl * (1 + BUY2_MARGIN)
                                tgt = main_cycle_invested * K_FRAC
                                
                                actual_ep = curr_soxl * (1 + SLIPPAGE)

                                if curr_soxl <= loc_lim_1 and main_add_buy_count < C_LIMIT:
                                    qty = round(tgt / loc_lim_1) 
                                    if qty * actual_ep > cash: qty = math.floor(cash / actual_ep)
                                    if qty > 0:
                                        cost = qty * actual_ep
                                        main_shares += qty
                                        cash -= cost
                                        main_cycle_invested += cost
                                        main_last_buy_close = curr_soxl
                                        main_add_buy_count += 1
                                
                                if curr_soxl <= loc_lim_2 and main_add_buy_count < C_LIMIT:
                                    qty = round(tgt / loc_lim_2) 
                                    if qty * actual_ep > cash: qty = math.floor(cash / actual_ep)
                                    if qty > 0:
                                        cost = qty * actual_ep
                                        main_shares += qty
                                        cash -= cost
                                        main_cycle_invested += cost
                                        main_last_buy_close = curr_soxl
                                        main_add_buy_count += 1

                    if not sell_rsi:
                        if curr_soxx_rsi <= RSI_BUY and rsi_buy_count < RSI_SPLIT:
                            if rsi_buy_count == 0: 
                                if main_shares == 0:
                                    active_rsi_budget = total_equity * RSI_FRAC
                                else:
                                    active_rsi_budget = latest_rsi_budget
                            
                            soxx_target_buy = prev_soxx_close + prev_soxx_ema_down - ((100 - RSI_BUY) / RSI_BUY) * prev_soxx_ema_up
                            soxx_pct = (soxx_target_buy - prev_soxx_close) / prev_soxx_close
                            loc_rsi_price = prev_soxl * (1 + 3 * soxx_pct)
                                    
                            target_rsi_amt = active_rsi_budget / RSI_SPLIT if RSI_SPLIT > 0 else 0
                            
                            if loc_rsi_price > 0:
                                buy_qty = round(target_rsi_amt / loc_rsi_price)
                            else:
                                buy_qty = 0
                                
                            actual_ep = curr_soxl * (1 + SLIPPAGE)
                            if buy_qty * actual_ep > cash: 
                                buy_qty = math.floor(cash / actual_ep)

                            if buy_qty > 0:
                                cost = buy_qty * actual_ep
                                rsi_shares += buy_qty
                                cash -= cost
                                rsi_invested += cost
                                rsi_buy_count += 1
                                if rsi_buy_count == 1: rsi_holding_days = 0

                    final_equity = cash + (main_shares + rsi_shares) * curr_soxl
                    current_progress = 0 if main_shares == 0 else main_add_buy_count + 1
                    cum_realized += today_realized_profit
                    disp_realized = today_realized_profit if (today_main_sell_date or today_rsi_sell_date) else ""
                    
                    unrealized = 0.0
                    if main_shares > 0: unrealized += (main_shares * curr_soxl) - main_cycle_invested
                    if rsi_shares > 0: unrealized += (rsi_shares * curr_soxl) - rsi_invested
                    
                    asset_return = ((final_equity / total_net_investment) - 1) * 100 if total_net_investment > 0 else 0
                    cash_ratio = (cash / final_equity) * 100 if final_equity > 0 else 0
                    
                    if main_shares == 0:
                        disp_base = final_equity
                        disp_init = final_equity * X_FRAC
                        disp_rsi = final_equity * RSI_FRAC
                    else:
                        disp_base = cycle_base_equity
                        disp_init = cycle_initial_buy_amt
                        disp_rsi = latest_rsi_budget
                        
                    disp_1st = disp_init * K_FRAC
                    disp_2nd = (disp_init + disp_1st) * K_FRAC
                    
                    main_avg_price = (main_cycle_invested / main_shares) if main_shares > 0 else 0
                    rsi_avg_price = (rsi_invested / rsi_shares) if rsi_shares > 0 else 0
                    
                    daily_records.append({
                        "진행도": current_progress,
                        "거래일": date_str,
                        "SOXL 종가": curr_soxl,
                        "Main 수량": main_shares,
                        "Main 평단": main_avg_price if main_avg_price > 0 else "",
                        "Main 매도일": today_main_sell_date,
                        "Main 수익금": today_main_profit,
                        "Main 손익률": today_main_profit_rate,
                        "RSI 수량": rsi_shares,
                        "RSI 평단": rsi_avg_price if rsi_avg_price > 0 else "",
                        "RSI 매도일": today_rsi_sell_date,
                        "RSI 수익금": today_rsi_profit,
                        "RSI 손익률": today_rsi_profit_rate,
                        "실현손익": disp_realized,
                        "평가손익": unrealized,
                        "누적 실현 손익": cum_realized,
                        "자산 손익률 (%)": asset_return,
                        "DD (%)": current_dd,
                        "초기 매수금": disp_init,
                        "1회 매수금": disp_1st,
                        "2회 매수금": disp_2nd,
                        "RSI 매수금": disp_rsi,
                        "투자 기준액": disp_base,
                        "진행일": main_holding_days,
                        "YDD (%)": current_ydd,
                        "현금 비중 (%)": cash_ratio,
                        "입출금": flow_today if flow_today != 0 else "",
                        "예수금(Cash)": cash,
                        "총 자산(Equity)": final_equity
                    })

                if not daily_records:
                    st.warning("선택한 조건에 해당하는 결과가 없습니다.")
                else:
                    df_records = pd.DataFrame(daily_records)
                    
                    # 탭 3개로 분할 적용
                    tab1, tab2, tab3 = st.tabs(["📊 백테스트 및 누적 매매 일지", "🛒 오늘의 실전 LOC 매매표", "📅 연도별/월별 상세 성과"])
                    
                    # ----------------------------------------
                    # [Tab 1] 기존 백테스트 및 누적 일지
                    # ----------------------------------------
                    with tab1:
                        final_asset = df_records.iloc[-1]['총 자산(Equity)']
                        final_cash = df_records.iloc[-1]['예수금(Cash)']
                        years = len(df_records) / 252 if len(df_records) > 252 else max(len(df_records) / 252, 0.1)
                        cagr = ((final_asset / total_net_investment) ** (1/years) - 1) * 100 if years > 0 and total_net_investment > 0 else 0
                        mdd = df_records['DD (%)'].min()
                        win_rate = (main_win_count / trade_count_main * 100) if trade_count_main > 0 else 0
                        
                        st.subheader("2. 현재 계좌 요약 (핵심 보드)")
                        c1, c2, c3, c4 = st.columns(4)
                        c1.metric("최종 총 자산", f"${final_asset:,.0f}")
                        c2.metric("보유 예수금 (현금)", f"${final_cash:,.0f}")
                        c3.metric("순 투자 원금", f"${total_net_investment:,.0f}")
                        c4.metric("Main 승률", f"{win_rate:.1f}%")
                        
                        c5, c6, c7, c8 = st.columns(4)
                        c5.metric("추정 CAGR", f"{cagr:.2f}%")
                        c6.metric("최대 낙폭 (MDD)", f"{mdd:.2f}%")
                        c7.metric("현재 위치 (DD)", f"{df_records.iloc[-1]['DD (%)']:.2f}%")
                        c8.metric("총 매매 횟수", f"{trade_count_main + trade_count_rsi}회")

                        st.subheader("3. 일자별 상세 매매 일지 (최신순)")
                        df_records_reversed = df_records.sort_values(by="거래일", ascending=False).reset_index(drop=True)
                        ordered_columns = [
                            "진행도", "거래일", "SOXL 종가", 
                            "Main 수량", "Main 평단", "Main 매도일", "Main 수익금", "Main 손익률", 
                            "RSI 수량", "RSI 평단", "RSI 매도일", "RSI 수익금", "RSI 손익률", 
                            "실현손익", "평가손익", "누적 실현 손익", "자산 손익률 (%)", 
                            "DD (%)", "초기 매수금", "1회 매수금", "2회 매수금", "RSI 매수금", 
                            "투자 기준액", "진행일", "YDD (%)", "현금 비중 (%)",
                            "입출금", "예수금(Cash)", "총 자산(Equity)"
                        ]
                        df_records_reversed = df_records_reversed[ordered_columns]
                        
                        cols_to_format = [
                            "SOXL 종가", "Main 평단", "Main 수익금", "RSI 평단", "RSI 수익금", 
                            "평가손익", "실현손익", "누적 실현 손익", "초기 매수금", 
                            "1회 매수금", "2회 매수금", "RSI 매수금", "투자 기준액", 
                            "입출금", "예수금(Cash)", "총 자산(Equity)"
                        ]
                        format_dict = {col: to_2_decimals for col in cols_to_format}
                        # 백분율(%) 포맷팅 전용 설정
                        format_dict["자산 손익률 (%)"] = to_pct_2_decimals
                        format_dict["현금 비중 (%)"] = to_pct_2_decimals
                        format_dict["DD (%)"] = to_pct_2_decimals
                        format_dict["YDD (%)"] = to_pct_2_decimals
                        
                        styled_df = df_records_reversed.style\
                            .apply(bg_color_sections, axis=0)\
                            .map(highlight_progress, subset=['진행도'])\
                            .map(color_profit, subset=[
                                'Main 수익금', 'Main 손익률', 'RSI 수익금', 'RSI 손익률', 
                                '실현손익', '평가손익', '누적 실현 손익', '자산 손익률 (%)'
                            ])\
                            .format(format_dict)
                        
                        st.dataframe(styled_df, use_container_width=True, height=500, hide_index=True, column_order=ordered_columns)

                    # ----------------------------------------
                    # [Tab 2] 실전 LOC 주문표
                    # ----------------------------------------
                    with tab2:
                        st.subheader("🚨 오늘 밤 미국 장 LOC 주문표")
                        
                        last_row = df_records.iloc[-1]
                        last_soxx_close = float(df['SOXX_Close'].iloc[-1])
                        last_soxl_close = float(df['SOXL_Close'].iloc[-1])
                        current_cash = float(last_row['예수금(Cash)']) 
                        last_total_equity = float(last_row['총 자산(Equity)'])
                        
                        last_ema_up = float(df['SOXX_ema_up'].iloc[-1])
                        last_ema_down = float(df['SOXX_ema_down'].iloc[-1])
                        
                        soxx_buy_target = last_soxx_close + last_ema_down - ((100 - RSI_BUY) / RSI_BUY) * last_ema_up
                        soxx_buy_pct = (soxx_buy_target - last_soxx_close) / last_soxx_close
                        soxl_rsi_buy_price = last_soxl_close * (1 + 3 * soxx_buy_pct)
                        
                        soxx_sell_target = last_soxx_close + (RSI_SELL / (100 - RSI_SELL)) * last_ema_down - last_ema_up
                        soxx_sell_pct = (soxx_sell_target - last_soxx_close) / last_soxx_close
                        soxl_rsi_sell_price = last_soxl_close * (1 + 3 * soxx_sell_pct)
                        
                        last_rsi = float(df['SOXX_RSI'].iloc[-1])
                        
                        main_avg_disp = f"${float(last_row['Main 평단']):.2f}" if last_row['Main 평단'] != "" else "$0.00"
                        
                        st.markdown(f"**기준일(마지막 장 마감):** {last_row['거래일']} | **전일 SOXL 종가:** ${last_soxl_close:.2f} | **SOXX RSI:** {last_rsi:.2f}")
                        
                        col_acc1, col_acc2, col_acc3 = st.columns(3)
                        col_acc1.metric("최종 매수가 (평단)", main_avg_disp)
                        col_acc2.metric("보유 수량", f"{last_row['Main 수량']} 주")
                        col_acc3.metric(f"진행 일수 (MOC {MOC}일)", f"{last_row['진행일']} 일")

                        order_list = []
                        buy_summary = []
                        sell_summary = []
                        
                        if main_shares > 0:
                            if main_add_buy_count >= C_LIMIT:
                                sell_price = last_soxl_close * (1 + EXH_TP)
                            else:
                                sell_price = main_last_buy_close * (1 + TP_RATE)
                            
                            order_list.append({
                                '구분 (매수/매도)': '매도 (Main)', '거래방법': 'LOC', 
                                '가격 ($)': round(sell_price, 2), '수량 (주)': main_shares
                            })
                            sell_summary.append((round(sell_price, 2), main_shares))
                        
                        if main_shares == 0:
                            buy_price = last_soxl_close * (1 + BUY0_MARGIN)
                            if buy_price > 0:
                                buy_qty = round(disp_init / buy_price)
                                if buy_qty * buy_price > current_cash: 
                                    buy_qty = math.floor(current_cash / buy_price)
                                
                                if buy_qty > 0:
                                    order_list.append({
                                        '구분 (매수/매도)': '매수 (Main 신규)', '거래방법': 'LOC', 
                                        '가격 ($)': round(buy_price, 2), '수량 (주)': buy_qty
                                    })
                                    buy_summary.append((round(buy_price, 2), buy_qty))
                        else:
                            if main_add_buy_count < C_LIMIT:
                                buy_price_1 = last_soxl_close * (1 + BUY1_MARGIN)
                                buy_price_2 = last_soxl_close * (1 + BUY2_MARGIN)
                                tgt_amt = main_cycle_invested * K_FRAC
                                
                                qty_1 = 0
                                if buy_price_1 > 0:
                                    qty_1 = round(tgt_amt / buy_price_1)
                                    if qty_1 * buy_price_1 > current_cash: 
                                        qty_1 = math.floor(current_cash / buy_price_1)
                                        
                                qty_2 = 0
                                if buy_price_2 > 0:
                                    qty_2 = round(tgt_amt / buy_price_2)
                                    if qty_2 * buy_price_2 > current_cash:
                                        qty_2 = math.floor(current_cash / buy_price_2)
                                
                                if qty_1 > 0:
                                    order_list.append({
                                        '구분 (매수/매도)': '매수 (Main 1차)', '거래방법': 'LOC', 
                                        '가격 ($)': round(buy_price_1, 2), '수량 (주)': qty_1
                                    })
                                    buy_summary.append((round(buy_price_1, 2), qty_1))
                                if qty_2 > 0:
                                    order_list.append({
                                        '구분 (매수/매도)': '매수 (Main 2차)', '거래방법': 'LOC', 
                                        '가격 ($)': round(buy_price_2, 2), '수량 (주)': qty_2
                                    })
                                    buy_summary.append((round(buy_price_2, 2), qty_2))

                        if rsi_shares > 0:
                            order_list.append({
                                '구분 (매수/매도)': '매도 (RSI 익절)', '거래방법': 'LOC', 
                                '가격 ($)': round(soxl_rsi_sell_price, 2), '수량 (주)': rsi_shares
                            })
                            sell_summary.append((round(soxl_rsi_sell_price, 2), rsi_shares))
                            
                        elif rsi_shares == 0 and rsi_buy_count < RSI_SPLIT:
                            if main_shares == 0:
                                current_rsi_budget = last_total_equity * RSI_FRAC
                            else:
                                current_rsi_budget = latest_rsi_budget
                            
                            rsi_target_amt = current_rsi_budget / RSI_SPLIT if RSI_SPLIT > 0 else 0
                            
                            if soxl_rsi_buy_price > 0:
                                rsi_qty = round(rsi_target_amt / soxl_rsi_buy_price)
                                if rsi_qty * soxl_rsi_buy_price > current_cash:
                                    rsi_qty = math.floor(current_cash / soxl_rsi_buy_price)
                                    
                                if rsi_qty > 0:
                                    order_list.append({
                                        '구분 (매수/매도)': '매수 (RSI 신규)', '거래방법': 'LOC', 
                                        '가격 ($)': round(soxl_rsi_buy_price, 2), '수량 (주)': rsi_qty
                                    })
                                    buy_summary.append((round(soxl_rsi_buy_price, 2), rsi_qty))

                        st.markdown("---")
                        col_table, col_summary = st.columns([1.5, 1])
                        
                        with col_table:
                            st.markdown("##### 📝 통합 주문 상세 표")
                            if order_list:
                                df_orders = pd.DataFrame(order_list)
                                styled_orders = df_orders.style\
                                    .apply(style_order_table, axis=1)\
                                    .format({'가격 ($)': "{:.2f}"})
                                
                                st.dataframe(styled_orders, use_container_width=True, hide_index=True)
                            else:
                                st.info("오늘 밤은 대기(관망) 상태입니다. 예약할 주문이 없습니다.")

                        with col_summary:
                            st.markdown("##### 🎯 증권사 입력용 최종 요약")
                            
                            st.markdown("**[ 원 매수 주문 ]**")
                            if buy_summary:
                                for p, q in buy_summary:
                                    st.write(f"💵 **${p:.2f}** | 🛒 **{q} 주**")
                            else:
                                st.write("- 매수 주문 없음")
                                
                            st.markdown("**[ 원 매도 주문 ]**")
                            if sell_summary:
                                for p, q in sell_summary:
                                    st.write(f"💵 **${p:.2f}** | 🛒 **{q} 주**")
                            else:
                                st.write("- 매도 주문 없음")

                    # ----------------------------------------
                    # [Tab 3] 연도별/월별 상세 성과 (매트릭스 탭)
                    # ----------------------------------------
                    with tab3:
                        st.subheader("📅 연도별/월별 상세 성과 매트릭스")
                        
                        # 데이터 전처리
                        df_t3 = df_records.copy()
                        df_t3['거래일'] = pd.to_datetime(df_t3['거래일'])
                        df_t3['Year'] = df_t3['거래일'].dt.year
                        df_t3['Month'] = df_t3['거래일'].dt.month
                        
                        # 월간 및 연간 수익률 도출을 위한 Series 생성
                        daily_equity_series = df_t3.set_index('거래일')['총 자산(Equity)']
                        
                        # 월간 시계열 데이터
                        monthly_end = daily_equity_series.resample('ME').last()
                        # 초기자금을 첫달 이전으로 간주하여 병합
                        first_day_idx = df_t3['거래일'].iloc[0] - pd.Timedelta(days=1)
                        monthly_equity = pd.concat([pd.Series({first_day_idx: INIT_CASH}), monthly_end])
                        monthly_ret = monthly_equity.pct_change().dropna() * 100
                        
                        monthly_df = pd.DataFrame({'Return': monthly_ret})
                        monthly_df['Year'] = monthly_df.index.year
                        monthly_df['Month'] = monthly_df.index.month
                        
                        # 피벗 테이블 생성 (4구역용)
                        pivot_ret = monthly_df.pivot(index='Year', columns='Month', values='Return')
                        for m in range(1, 13):
                            if m not in pivot_ret.columns: pivot_ret[m] = np.nan
                        pivot_ret = pivot_ret[list(range(1, 13))]
                        
                        # 연간 통계 산출 (2구역용)
                        yearly_end = daily_equity_series.resample('YE').last()
                        yearly_equity = pd.concat([pd.Series({first_day_idx: INIT_CASH}), yearly_end])
                        yearly_ret = yearly_equity.pct_change().dropna() * 100
                        
                        yearly_stats = []
                        for y in df_t3['Year'].unique():
                            y_df = df_t3[df_t3['Year'] == y]
                            y_mdd = y_df['DD (%)'].min()
                            y_avg_dd = y_df['DD (%)'].mean()
                            y_avg_cash = y_df['현금 비중 (%)'].mean()
                            y_asset = y_df['총 자산(Equity)'].iloc[-1]
                            y_r = yearly_ret[yearly_ret.index.year == y].iloc[0] if y in yearly_ret.index.year else 0
                            yearly_stats.append({
                                '연도': y, '자산': y_asset, '수익률': y_r, 
                                'MDD': y_mdd, 'avg DD': y_avg_dd, 'avg Cash': y_avg_cash
                            })
                        df_yearly = pd.DataFrame(yearly_stats).set_index('연도')
                        
                        # 전체 통계 연산 (1구역용)
                        ov_mdd_day = df_t3.loc[df_t3['DD (%)'].idxmin(), '거래일'].strftime('%y.%m.%d') if not df_t3.empty else ""
                        ov_avg_mdd = df_yearly['MDD'].mean() if not df_yearly.empty else 0
                        ov_avg_dd = df_t3['DD (%)'].mean()
                        ov_avg_cash = df_t3['현금 비중 (%)'].mean()
                        ov_min_cash = df_t3['현금 비중 (%)'].min()
                        ov_calmar = (cagr / abs(mdd)) if mdd < 0 else 0
                        
                        # 월간 및 전략 통계 연산 (3구역용)
                        up_months = monthly_ret[monthly_ret > 0]
                        down_months = monthly_ret[monthly_ret < 0]
                        avg_up = up_months.mean() if not up_months.empty else 0
                        avg_down = down_months.mean() if not down_months.empty else 0
                        max_up = monthly_ret.max() if not monthly_ret.empty else 0
                        max_down = monthly_ret.min() if not monthly_ret.empty else 0
                        
                        m_win_rate = (main_win_count / (main_win_count + main_loss_count) * 100) if (main_win_count + main_loss_count) > 0 else 0
                        r_win_rate = (rsi_win_count / (rsi_win_count + rsi_loss_count) * 100) if (rsi_win_count + rsi_loss_count) > 0 else 0
                        
                        dd_10 = (df_t3['DD (%)'] <= -10.0).mean() * 100
                        dd_20 = (df_t3['DD (%)'] <= -20.0).mean() * 100
                        dd_30 = (df_t3['DD (%)'] <= -30.0).mean() * 100
                        dd_40 = (df_t3['DD (%)'] <= -40.0).mean() * 100

                        # 화면 4분할 레이아웃 배치
                        c_ov, c_yr, c_st, c_mx = st.columns([1, 2, 1.2, 5])
                        
                        # 1구역: 전체 요약
                        with c_ov:
                            summary_data = {
                                "구분": ["시작일", "종료일", "Calmar", "CAGR", "MDD", "MDD Day", "avg MDD", "avg DD", "avg Cash", "min Cash"],
                                "수치": [
                                    start_date.strftime('%y.%m.%d'), end_date.strftime('%y.%m.%d'),
                                    f"{ov_calmar:.2f}", f"{cagr:.2f}%", f"{mdd:.2f}%", ov_mdd_day,
                                    f"{ov_avg_mdd:.2f}%", f"{ov_avg_dd:.2f}%", f"{ov_avg_cash:.2f}%", f"{ov_min_cash:.2f}%"
                                ]
                            }
                            st.dataframe(pd.DataFrame(summary_data), hide_index=True)
                            
                        # 2구역: 연도별 요약
                        with c_yr:
                            st.dataframe(df_yearly.style.format({
                                '자산': "${:,.0f}", '수익률': "{:.2f}%", 'MDD': "{:.2f}%", 
                                'avg DD': "{:.2f}%", 'avg Cash': "{:.2f}%"
                            }).map(color_profit, subset=['수익률']), use_container_width=True)
                            
                        # 3구역: 월간 기준 & 전략 승률 (엑셀 블록 디자인 모방)
                        with c_st:
                            df_m_stat = pd.DataFrame({
                                "월간": ["상승 평균", "하락 평균", "최대 상승", "최대 하락"],
                                "결과": [f"{avg_up:.2f}%", f"{avg_down:.2f}%", f"{max_up:.2f}%", f"{max_down:.2f}%"]
                            })
                            st.dataframe(df_m_stat.style.map(color_profit, subset=['결과']), hide_index=True, use_container_width=True)
                            
                            df_win_stat = pd.DataFrame({
                                "전략": [f"Main 승률", "└ 익절", "└ 손절", f"RSI 승률", "└ 익절", "└ 손절"],
                                "결과": [f"{m_win_rate:.2f}%", main_win_count, main_loss_count, f"{r_win_rate:.2f}%", rsi_win_count, rsi_loss_count]
                            })
                            st.dataframe(df_win_stat, hide_index=True, use_container_width=True)
                            
                            df_dd_stat = pd.DataFrame({
                                "DD 분포": ["-10% 이하", "-20% 이하", "-30% 이하", "-40% 이하"],
                                "비율": [f"{dd_10:.2f}%", f"{dd_20:.2f}%", f"{dd_30:.2f}%", f"{dd_40:.2f}%"]
                            })
                            st.dataframe(df_dd_stat, hide_index=True, use_container_width=True)

                        # 4구역: 월별 수익률 매트릭스
                        with c_mx:
                            st.dataframe(pivot_ret.style.format("{:.2f}%", na_rep="")
                                         .map(color_profit), use_container_width=True)
