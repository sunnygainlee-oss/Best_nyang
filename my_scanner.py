import FinanceDataReader as fdr
import pandas as pd
import requests
import time
from bs4 import BeautifulSoup # Add BeautifulSoup for web scraping
import datetime # Added for today's date

# --- [설정: 여기만 수정하세요] ---
TELEGRAM_TOKEN = "8794261749:AAEloyQQJaAf90DRIJkDT3vYhOOSRbpTVdc" # 여기에 실제 텔레그램 봇 토큰을 입력하세요
CHAT_ID = "905949452"             # 여기에 실제 채팅 ID 또는 채널명을 입력하세요 (예: -1234567890 또는 @YourChannelName)
SLOPE_LIMIT = -0.0002  # 150일선 기울기 기준
VOL_MULT = 1.5         # 거래량 돌파 기준 (기존 50일선 기준)
VOL_20_DAY_MULT = 3.0  # 20일 거래량 평균 대비 300% 이상 조건
SQZ_THRESH = 0.15      # 압축 강도

# 상대강도 계산에 사용할 기간들 (거래일 기준)
RS_LOOKBACK_PERIODS = [1, 20, 60] # 변경: 당일(1일), 20일, 60일
# ------------------------------

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    params = {"chat_id": CHAT_ID, "text": message}
    print(f"Attempting to send Telegram message to URL: {url} with params: {params}") # Debugging line added
    response = requests.get(url, params=params)
    print(f"Telegram API response: {response.json()}") # Print response for debugging

def format_marcap(marcap_value):
    if marcap_value is None:
        return "N/A"
    if marcap_value >= 1_000_000_000_000:
        trillions = marcap_value // 1_000_000_000_000
        billions = round((marcap_value % 1_000_000_000_000) / 10_000_000_000) # 100억 단위 반올림
        if billions >= 100:
            trillions += 1
            billions = 0
        return f"{trillions:,.0f}조 {billions:,.0f}억"
    elif marcap_value >= 100_000_000:
        billions = round(marcap_value / 100_000_000)
        return f"{billions:,.0f}억"
    else:
        return f"{marcap_value:,.0f}원"

def check_strategy():
    print("🚀 전 종목 스캔을 시작합니다... (시간이 다소 소요될 수 있습니다)")

    today = datetime.date.today()
    initial_message = f"🗓️ {today.strftime('%Y년 %m월 %d일')} 주식 스캔 시작!\n\n"

    # Fetch KOSPI and KOSDAQ index data once for Relative Strength (RS) calculation and initial message
    df_kospi = None
    df_kosdaq = None
    try:
        df_kospi = fdr.DataReader('KS11') # KOSPI index symbol
        print("KOSPI data fetched successfully for RS calculation.")
        if len(df_kospi) >= 2:
            kospi_current = df_kospi['Close'].iloc[-1]
            kospi_prev = df_kospi['Close'].iloc[-2]
            kospi_change_rate = (kospi_current - kospi_prev) / kospi_prev * 100
            initial_message += f"📈 코스피: {kospi_current:,.2f} ({kospi_change_rate:+.2f}%)\n"
        else:
            initial_message += "📈 코스피: 데이터 부족\n"
    except Exception as e:
        print(f"Error fetching KOSPI data for RS calculation: {e}")
        initial_message += "📈 코스피: 정보 조회 오류\n"

    try:
        df_kosdaq = fdr.DataReader('KQ11') # KOSDAQ index symbol
        print("KOSDAQ data fetched successfully for RS calculation.")
        if len(df_kosdaq) >= 2:
            kosdaq_current = df_kosdaq['Close'].iloc[-1]
            kosdaq_prev = df_kosdaq['Close'].iloc[-2]
            kosdaq_change_rate = (kosdaq_current - kosdaq_prev) / kosdaq_prev * 100
            initial_message += f"📊 코스닥: {kosdaq_current:,.2f} ({kosdaq_change_rate:+.2f}%)\n\n"
        else:
            initial_message += "📊 코스닥: 데이터 부족\n\n"
    except Exception as e:
        print(f"Error fetching KOSDAQ data for RS calculation: {e}")
        initial_message += "📊 코스닥: 정보 조회 오류\n\n"

    send_telegram(initial_message) # Send initial status message

    # 코스피, 코스닥 종목 리스트 가져오기
    df_krx = fdr.StockListing('KRX')

    # '스팩' 종목 제외
    df_krx = df_krx[~df_krx['Name'].str.contains('스팩', na=False)]

    count = 0

    for index, row in df_krx.iterrows():
        code = row['Code']
        name = row['Name']
        marcap = row['Marcap'] # 시가총액 정보 가져오기
        market = row['Market'] # 시장 정보 가져오기 (KOSPI 또는 KOSDAQ)

        # 시총 2천억원 이하 제외
        if marcap is None or marcap < 200_000_000_000:
            continue

        try:
            # 최근 200일치 데이터 가져오기 (가장 긴 RS 기간 60일 + 여유분)
            df = fdr.DataReader(code)
            if len(df) < max(RS_LOOKBACK_PERIODS) + 10: continue # 상장한 지 얼마 안 된 종목 제외

            # 1. 이동평균선 및 기울기 계산
            df['ma150'] = df['Close'].rolling(window=150).mean()
            df['ma50'] = df['Close'].rolling(window=50).mean()
            slope = (df['ma150'].iloc[-1] - df['ma150'].iloc[-2]) / df['ma150'].iloc[-2]

            # 2. 볼린저 밴드 및 압축 계산
            std = df['Close'].rolling(window=20).std()
            upper = df['Close'].rolling(window=20).mean() + (std * 2)
            lower = df['Close'].rolling(window=20).mean() - (std * 2)
            bandwidth = (upper - lower) / df['ma150']
            is_squeeze = bandwidth.iloc[-1] < SQZ_THRESH

            # 3. 거래량 및 돌파 조건
            vol_sma50 = df['Volume'].rolling(window=50).mean()
            vol_surge_50 = df['Volume'].iloc[-1] > vol_sma50.iloc[-1] * VOL_MULT

            vol_sma20 = df['Volume'].rolling(window=20).mean()
            vol_surge_20_day_300_percent = df['Volume'].iloc[-1] > vol_sma20.iloc[-1] * VOL_20_DAY_MULT

            breakout = df['Close'].iloc[-1] > df['High'].iloc[-11:-1].max() # 10일 신고가 돌파

            # --- [매수 논리 판독] ---
            is_downtrend = slope < SLOPE_LIMIT

            # A. ON 스타일 (Turn)
            signal_turn = (not is_downtrend) and (df['Close'].iloc[-2] < df['ma150'].iloc[-2]) and (df['Close'].iloc[-1] > df['ma150'].iloc[-1])

            # B. NVTS 스타일 (VCP)
            is_uptrend = df['Close'].iloc[-1] > df['ma50'].iloc[-1]
            # 최근 10일 이내에 스퀴즈가 있었는지 확인
            recent_squeeze = bandwidth.iloc[-10:].min() < SQZ_THRESH
            signal_vcp = (not is_downtrend) and is_uptrend and recent_squeeze and vol_surge_50 and vol_surge_20_day_300_percent and breakout

            if signal_turn or signal_vcp:
                type_msg = "BUY(Turn)" if signal_turn else "BUY(VCP)"

                # 시가총액 정보를 메시지에 추가
                formatted_marcap = format_marcap(marcap)

                # Determine market index for RS calculation
                rs_market_name = "N/A"
                # df_market_index는 이미 위에서 가져왔으므로 재사용
                df_market_index = None
                if market == 'KOSPI':
                    df_market_index = df_kospi
                    rs_market_name = "KOSPI"
                elif market == 'KOSDAQ':
                    df_market_index = df_kosdaq
                    rs_market_name = "KOSDAQ"

                rs_details = []
                if df_market_index is not None and len(df_market_index) >= max(RS_LOOKBACK_PERIODS) + 1: # Ensure enough data for longest period + current
                    for period in RS_LOOKBACK_PERIODS:
                        rs_value = "N/A"
                        # Ensure enough data points for the current period + current day
                        if len(df) >= period + 1 and len(df_market_index) >= period + 1:
                            try:
                                stock_start_price = df['Close'].iloc[-1 - period]
                                stock_current_price = df['Close'].iloc[-1]

                                market_start_price = df_market_index['Close'].iloc[-1 - period]
                                market_current_price = df_market_index['Close'].iloc[-1]

                                if stock_start_price != 0 and market_start_price != 0: # Avoid division by zero
                                    stock_performance_ratio = stock_current_price / stock_start_price
                                    market_performance_ratio = market_current_price / market_start_price
                                    if market_performance_ratio != 0: # Avoid division by zero
                                        rs_value = f"{(stock_performance_ratio / market_performance_ratio):.2f}"
                                    else:
                                        rs_value = "N/A (시장 수익률 0)"
                                else:
                                    rs_value = "N/A (데이터 부족: 시작 가격 0)"
                            except Exception as rs_e:
                                print(f"Error calculating RS for {name} ({code}) over {period} days: {rs_e}")
                        else:
                            rs_value = "N/A (데이터 부족)" # Or less than period + 1 data points

                        rs_display_text_for_period = rs_value
                        if rs_value != "N/A" and "데이터 부족" not in rs_value and "시장 수익률 0" not in rs_value:
                            try:
                                rs_float = float(rs_value)
                                if rs_float > 1.0:
                                    rs_display_text_for_period += " (시장 대비 강세)"
                                elif rs_float < 1.0:
                                    rs_display_text_for_period += " (시장 대비 약세)"
                                else:
                                    rs_display_text_for_period += " (시장과 유사)"
                            except ValueError:
                                pass # Keep as is if conversion fails for some reason
                        rs_details.append(f"  {period}일: {rs_display_text_for_period}")

                if rs_details:
                    rs_output = f"상대강도(vs {rs_market_name}):\n" + "\n".join(rs_details)
                else:
                    rs_output = f"상대강도(vs {rs_market_name}): N/A"

                msg = f"✅ [{type_msg}] 신호 발생!\n종목: {name} ({code})\n현재가: {df['Close'].iloc[-1]:,.0f}원\n시가총액: {formatted_marcap}\n{rs_output}"
                print(msg)
                send_telegram(msg)
                count += 1

            time.sleep(0.05) # 서버 부하 방지용 미세 지연

        except Exception as e:
            print(f"Error processing {name} ({code}): {e}") # More detailed error logging
            continue

    send_telegram(f"📢 스캔 완료! 총 {count}개의 종목을 찾았습니다.")

# 실행
check_strategy()
