import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import math
from datetime import date, timedelta

# --- 페이지 기본 설정 (모바일 최적화) ---
st.set_page_config(page_title="Solid Quant Dashboard", layout="wide", initial_sidebar_state="collapsed")
st.title("🛒 실전 매매 대시보드")

# --- 세션 상태 초기화 (자본 출입 기록용) ---
if 'capital_flows' not in st.session_state:
    st.session_state['capital_flows'] = []

# --- 구역 A: 사용자 입력부 ---
with st.expander("📝 1. 기본 설정 및 입출금 기록 (터치하여 열기)", expanded=True):
    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("백테스트 시작일", date(2015, 1, 1))
        INIT_CASH = st.number_input("초기 자본 ($)", min_value=1000.0, value=100000.0, step=1000.0)
    with col2:
        end_date = st.date_input("오늘(종료일)", date.today())
    
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
            st.success(f"{f_date} 일자에 ${f_amt:,.0f} 기록 완료!")

    # 입력된 입출금 리스트 보여주기 및 삭제 (간이 구현)
    if st.session_state['capital_flows']:
        flow_df = pd.DataFrame(st.session_state['capital_flows'])
        st.dataframe(flow_df, use_container_width=True)
        if st.button("내역 전체 초기화"):
            st.session_state['capital_flows'] = []
            st.rerun()

run_button = st.button("🚀 매매표 생성 및 백테스트 실행", type="primary", use_container_width=True)

# --- 보조지표 계산 함수 ---
def calculate_rsi(series, period=2):
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ema_up = up.ewm(com=period-1, adjust=False).mean()
    ema_down = down.ewm(com=period-1, adjust=False).mean()
    rs = ema_up / ema_down
    return 100 - (100 / (1 + rs))

# --- 데이터 로드 함수 ---
@st.cache_data(show_spinner=False)
def load_market_data(start, end):
    data_start = start - timedelta(days=60)
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

# --- 메인 실행 로직 ---
if run_button:
    if start_date >= end_date:
        st.error("종료일이 시작일보다 빠를 수 없습니다.")
    else:
        with st.spinner("시장 데이터 동기화 및 기록장 작성 중..."):
            df = load_market_data(start_date, end_date)
            trade_start_idx = df.index.searchsorted(pd.to_datetime(start_date))
            
            # --- 내부 고정 파라미터 ---
            X_FRAC = 0.35      # 35%
            K_FRAC = 0.125     # 12.5%
            C_LIMIT = 7        # 7회
            TP_RATE = 0.06     # 6%
            EXH_TP = 0.03      # 3%
            SLIPPAGE = 0.0     # 0%
            RSI_FRAC = 0.30    # 30%
            MAX_HOLD_DAYS = 24
            DROP_BUY_RATE_1 = 0.010
            DROP_BUY_RATE_2 = 0.100
            
            # 자본 흐름 딕셔너리 매핑
            flows_dict = {}
            for f in st.session_state['capital_flows']:
                d_str = f['Date'].strftime('%Y-%m-%d')
                flows_dict[d_str] = flows_dict.get(d_str, 0.0) + f['Amount']
            
            cash = INIT_CASH
            total_net_investment = INIT_CASH
            
            main_shares, main_cycle_invested, main_last_buy_close = 0, 0.0, 0.0
            main_holding_days, main_add_buy_count = 0, 0
            
            rsi_shares, rsi_invested, rsi_buy_count, rsi_holding_days = 0, 0.0, 0, 0
            latest_rsi_budget, active_rsi_budget = 0.0, 0.0
            
            trade_count_main, win_count_main, trade_count_rsi = 0, 0, 0
            
            # 기록 저장용 리스트
            daily_records = []
            max_equity = INIT_CASH

            # 시뮬레이션 루프
            for i in range(trade_start_idx, len(df)):
                current_date = df.index[i].date()
                date_str = current_date.strftime('%Y-%m-%d')
                
                # 당일 자본 입출금 적용
                flow_today = flows_dict.get(date_str, 0.0)
                if flow_today != 0:
                    cash += flow_today
                    total_net_investment += flow_today

                curr_soxl = float(df['SOXL_Close'].iloc[i])
                prev_soxl = float(df['SOXL_Close'].iloc[i-1]) if i > 0 else curr_soxl
                curr_soxx_rsi = float(df['SOXX_RSI'].iloc[i])
                
                total_equity = cash + (main_shares + rsi_shares) * curr_soxl
                if total_equity > max_equity: max_equity = total_equity
                current_dd = ((total_equity / max_equity) - 1) * 100

                sell_main, sell_rsi = False, False

                # [A] 매도 판별
                if main_shares > 0:
                    main_holding_days += 1
                    if main_add_buy_count >= C_LIMIT:
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

                # [B] 매수 판별 및 실행
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
                        if main_add_buy_count < C_LIMIT:
                            b_lim_1 = prev_soxl * (1 - DROP_BUY_RATE_1)
                            b_lim_2 = prev_soxl * (1 - DROP_BUY_RATE_2)
                            tgt = main_cycle_invested * K_FRAC

                            for lim in [b_lim_1, b_lim_2]:
                                if curr_soxl <= lim and main_add_buy_count < C_LIMIT:
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

                # 당일 마감 기록
                final_equity = cash + (main_shares + rsi_shares) * curr_soxl
                main_avg_price = (main_cycle_invested / main_shares) if main_shares > 0 else 0
                rsi_avg_price = (rsi_invested / rsi_shares) if rsi_shares > 0 else 0
                
                daily_records.append({
                    "거래일": date_str,
                    "SOXL 종가": round(curr_soxl, 2),
                    "입출금": round(flow_today, 0) if flow_today != 0 else "",
                    "예수금(Cash)": round(cash, 2),
                    "총 자산(Equity)": round(final_equity, 2),
                    "Main 수량": main_shares,
                    "Main 평단": round(main_avg_price, 2) if main_avg_price > 0 else "",
                    "RSI 수량": rsi_shares,
                    "RSI 평단": round(rsi_avg_price, 2) if rsi_avg_price > 0 else "",
                    "진행도(C)": f"{main_add_buy_count} / {C_LIMIT}",
                    "현재 DD (%)": round(current_dd, 2)
                })

            # --- 구역 B: 핵심 요약 보드 ---
            df_records = pd.DataFrame(daily_records)
            
            final_asset = df_records.iloc[-1]['총 자산(Equity)']
            final_cash = df_records.iloc[-1]['예수금(Cash)']
            years = len(df_records) / 252
            
            # 입출금을 고려한 추정 CAGR 계산 (단순화)
            cagr = ((final_asset / total_net_investment) ** (1/years) - 1) * 100 if years > 0 and total_net_investment > 0 else 0
            mdd = df_records['현재 DD (%)'].min()
            win_rate = (win_count_main / trade_count_main * 100) if trade_count_main > 0 else 0
            
            st.success("✅ 실전 매매 기록장 업데이트 완료!")
            
            st.subheader("📊 2. 현재 계좌 요약 (핵심 보드)")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("최종 총 자산", f"${final_asset:,.0f}")
            c2.metric("보유 예수금 (현금)", f"${final_cash:,.0f}")
            c3.metric("순 투자 원금", f"${total_net_investment:,.0f}")
            c4.metric("Main 승률", f"{win_rate:.1f}%")
            
            c5, c6, c7, c8 = st.columns(4)
            c5.metric("추정 CAGR", f"{cagr:.2f}%")
            c6.metric("최대 낙폭 (MDD)", f"{mdd:.2f}%")
            c7.metric("현재 위치 (DD)", f"{df_records.iloc[-1]['현재 DD (%)']:.2f}%")
            c8.metric("총 매매 횟수", f"{trade_count_main + trade_count_rsi}회")

            # --- 구역 C: 상세 매매 일지 (스프레드시트 뷰) ---
            st.subheader("📋 3. 일자별 상세 매매 일지 (최신순)")
            # 보기 편하도록 최근 날짜가 위로 오게 역순 정렬
            df_records_reversed = df_records.sort_values(by="거래일", ascending=False).reset_index(drop=True)
            
            # 데이터프레임 스타일링 (모바일 화면 대응)
            st.dataframe(
                df_records_reversed,
                use_container_width=True,
                height=500
            )
