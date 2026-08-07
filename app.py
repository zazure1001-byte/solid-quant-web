import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import math
import matplotlib.pyplot as plt
from datetime import date, timedelta

# --- 페이지 기본 설정 (모바일 최적화) ---
st.set_page_config(page_title="Solid Quant", layout="centered", initial_sidebar_state="collapsed")
st.title("📈 솔리드 하이브리드 백테스터")

# --- 파라미터 입력부 (아코디언 메뉴) ---
with st.expander("⚙️ 파라미터 설정 (터치하여 열기/닫기)", expanded=True):
    col1, col2 = st.columns(2)
    with col1:
        x_input = st.number_input("초기 진입 비중 (X) %", min_value=5.0, max_value=100.0, value=35.0, step=0.1)
        k_input = st.number_input("추가 매수 비율 (K) %", min_value=1.0, max_value=50.0, value=12.5, step=0.1)
        c_input = st.number_input("최대 매수 횟수 (C)", min_value=1, max_value=10, value=7, step=1)
        slippage_input = st.number_input("슬리피지 (%)", min_value=0.0, max_value=5.0, value=0.0, step=0.01)
    with col2:
        exh_tp_input = st.number_input("소진시 익절 목표 %", min_value=1.0, max_value=20.0, value=3.0, step=0.5)
        start_date = st.date_input("백테스트 시작일", date(2015, 1, 1))
        end_date = st.date_input("백테스트 종료일", date.today())
    
    run_button = st.button("🚀 백테스트 실행", use_container_width=True)

# --- 보조지표 계산 함수 ---
def calculate_rsi(series, period=2):
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ema_up = up.ewm(com=period-1, adjust=False).mean()
    ema_down = down.ewm(com=period-1, adjust=False).mean()
    rs = ema_up / ema_down
    return 100 - (100 / (1 + rs))

# --- 데이터 로드 함수 (캐싱 적용으로 재실행 속도 향상) ---
@st.cache_data(show_spinner=False)
def load_market_data(start, end):
    data_start = start - timedelta(days=60) # 지표 계산을 위한 여유 기간
    df_soxl = yf.download("SOXL", start=data_start, end=end, auto_adjust=True, progress=False)
    df_soxx = yf.download("SOXX", start=data_start, end=end, auto_adjust=True, progress=False)
    
    if isinstance(df_soxl.columns, pd.MultiIndex):
        df_soxl.columns = df_soxl.columns.get_level_values(0)
        df_soxx.columns = df_soxx.columns.get_level_values(0)
        
    df = pd.DataFrame({
        'SOXL_Close': df_soxl['Close'],
        'SOXX_Close': df_soxx['Close']
    }).dropna().sort_index()
    
    df['SOXX_RSI'] = calculate_rsi(df['SOXX_Close'], period=2)
    return df.dropna().copy()

# --- 메인 백테스트 로직 ---
if run_button:
    if start_date >= end_date:
        st.error("종료일이 시작일보다 빠를 수 없습니다.")
    else:
        with st.spinner("데이터 다운로드 및 백테스트 진행 중..."):
            df = load_market_data(start_date, end_date)
            trade_start_idx = df.index.searchsorted(pd.to_datetime(start_date))
            
            # 파라미터 셋업
            INIT_CASH = 100000.0
            TP_RATE = 0.060
            MAX_HOLD_DAYS = 24
            DROP_BUY_RATE_1 = 0.010
            DROP_BUY_RATE_2 = 0.100
            SLIPPAGE = slippage_input / 100.0  # 입력받은 슬리피지 적용
            RSI_FRAC = 0.30
            
            X_FRAC = x_input / 100.0
            K_FRAC = k_input / 100.0
            EXH_TP = exh_tp_input / 100.0
            
            cash = INIT_CASH
            main_shares, main_cycle_invested, main_last_buy_close = 0, 0.0, 0.0
            main_holding_days, main_add_buy_count = 0, 0
            
            rsi_shares, rsi_invested, rsi_buy_count, rsi_holding_days = 0, 0.0, 0, 0
            latest_rsi_budget = cash * RSI_FRAC
            active_rsi_budget = 0.0
            
            trade_count_main, win_count_main, trade_count_rsi = 0, 0, 0
            equity_curve = np.full(len(df), np.nan)

            # 시뮬레이션 루프
            for i in range(len(df)):
                if i < trade_start_idx:
                    equity_curve[i] = cash
                    continue

                curr_soxl = float(df['SOXL_Close'].iloc[i])
                prev_soxl = float(df['SOXL_Close'].iloc[i-1])
                curr_soxx_rsi = float(df['SOXX_RSI'].iloc[i])
                total_equity = cash + (main_shares + rsi_shares) * curr_soxl

                sell_main, sell_rsi = False, False

                # [A] 매도 판별
                if main_shares > 0:
                    main_holding_days += 1
                    if main_add_buy_count >= c_input:
                        sell_limit_tp = prev_soxl * (1 + EXH_TP)
                    else:
                        sell_limit_tp = main_last_buy_close * (1 + TP_RATE)
                        
                    if curr_soxl >= sell_limit_tp or main_holding_days >= MAX_HOLD_DAYS:
                        sell_main = True

                if rsi_shares > 0:
                    rsi_holding_days += 1
                    if curr_soxx_rsi >= 25 or rsi_holding_days >= 10:
                        sell_rsi = True

                # [A] 매도 실행
                if sell_main:
                    exec_price = curr_soxl * (1 - SLIPPAGE)
                    sell_amount = main_shares * exec_price
                    cash += sell_amount
                    trade_count_main += 1
                    if sell_amount > main_cycle_invested:
                        win_count_main += 1
                    main_shares, main_holding_days, main_cycle_invested = 0, 0, 0.0
                    main_last_buy_close, main_add_buy_count = 0.0, 0

                if sell_rsi:
                    exec_price = curr_soxl * (1 - SLIPPAGE)
                    sell_amount = rsi_shares * exec_price
                    cash += sell_amount
                    trade_count_rsi += 1
                    rsi_shares, rsi_invested, rsi_buy_count, rsi_holding_days = 0, 0.0, 0, 0

                # [B] 매수 - Main
                if not sell_main:
                    if main_shares == 0:
                        if curr_soxl <= prev_soxl * 1.05:
                            latest_rsi_budget = total_equity * RSI_FRAC
                            target_main_amt = total_equity * X_FRAC
                            ep = curr_soxl * (1 + SLIPPAGE)
                            buy_qty = round(target_main_amt / ep)
                            if buy_qty * ep > cash: buy_qty = math.floor(cash / ep)

                            if buy_qty > 0:
                                cost = buy_qty * ep
                                main_shares += buy_qty
                                cash -= cost
                                main_cycle_invested = cost
                                main_last_buy_close = curr_soxl
                                main_holding_days, main_add_buy_count = 0, 0
                    else:
                        if main_add_buy_count < c_input:
                            b_lim_1 = prev_soxl * (1 - DROP_BUY_RATE_1)
                            b_lim_2 = prev_soxl * (1 - DROP_BUY_RATE_2)
                            tgt = main_cycle_invested * K_FRAC

                            for lim in [b_lim_1, b_lim_2]:
                                if curr_soxl <= lim and main_add_buy_count < c_input:
                                    ep = curr_soxl * (1 + SLIPPAGE)
                                    qty = max(0, round(tgt / ep))
                                    if qty * ep > cash: qty = math.floor(cash / ep)
                                    if qty > 0:
                                        cost = qty * ep
                                        main_shares += qty
                                        cash -= cost
                                        main_cycle_invested += cost
                                        main_last_buy_close = curr_soxl
                                        main_add_buy_count += 1

                # [C] 매수 - RSI
                if not sell_rsi:
                    if curr_soxx_rsi <= 22 and rsi_buy_count < 2:
                        if rsi_buy_count == 0: active_rsi_budget = latest_rsi_budget
                        target_rsi_amt = active_rsi_budget / 2
                        ep = curr_soxl * (1 + SLIPPAGE)
                        buy_qty = round(target_rsi_amt / ep)
                        if buy_qty * ep > cash: buy_qty = math.floor(cash / ep)

                        if buy_qty > 0:
                            cost = buy_qty * ep
                            rsi_shares += buy_qty
                            cash -= cost
                            rsi_invested += cost
                            rsi_buy_count += 1
                            if rsi_buy_count == 1: rsi_holding_days = 0

                equity_curve[i] = cash + (main_shares + rsi_shares) * curr_soxl

            # --- 결과 산출 ---
            df['Equity'] = equity_curve
            df_trade = df.iloc[trade_start_idx:].copy()
            
            final_equity = df_trade['Equity'].iloc[-1]
            years = len(df_trade) / 252
            cagr = ((final_equity / INIT_CASH) ** (1/years) - 1) * 100
            mdd = (((df_trade['Equity'] / df_trade['Equity'].cummax()) - 1).min()) * 100
            
            win_rate = (win_count_main / trade_count_main * 100) if trade_count_main > 0 else 0
            
            # --- UI 결과 출력 ---
            st.success("✅ 백테스트 완료!")
            
            st.subheader("📊 요약 리포트")
            col1, col2, col3 = st.columns(3)
            col1.metric("최종 자산", f"${final_equity:,.0f}")
            col2.metric("CAGR", f"{cagr:.2f}%")
            col3.metric("MDD", f"{mdd:.2f}%")
            
            col4, col5, col6 = st.columns(3)
            col4.metric("초기 자산", f"${INIT_CASH:,.0f}")
            col5.metric("Main 승률", f"{win_rate:.1f}%")
            col6.metric("총 매매횟수", f"{trade_count_main + trade_count_rsi}회")

            st.subheader("📈 자산 곡선 (Log Scale)")
            fig, ax = plt.subplots(figsize=(10, 5))
            ax.plot(df_trade.index, df_trade['Equity'], color='#2ca02c', linewidth=1.5)
            ax.set_yscale('log')
            ax.set_ylabel("Total Equity ($)")
            ax.grid(True, which="both", ls="--", alpha=0.5)
            st.pyplot(fig)
