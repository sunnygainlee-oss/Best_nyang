import os
import FinanceDataReader as fdr
import pandas as pd
import requests
import time
from bs4 import BeautifulSoup # Add BeautifulSoup for web scraping

# --- [설정: 여기만 수정하세요] ---
TELEGRAM_TOKEN = "8794261749:AAEloyQQJaAf90DRIJkDT3vYhOOSRbpTVdc" # 여기에 실제 텔레그램 봇 토큰을 입력하세요
CHAT_ID = "905949452"             # 여기에 실제 채팅 ID 또는 채널명을 입력하세요 (예: -1234567890 또는 @YourChannelName)
SLOPE_LIMIT = -0.0002  # 150일선 기울기 기준
VOL_MULT = 1.5         # 거래량 돌파 기준 (기존 50일선 기준)
VOL_20_DAY_MULT = 3.0  # 20일 거래량 평균 대비 300% 이상 조건
SQZ_THRESH = 0.15      # 압축 강도
# ------------------------------

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    params = {"chat_id": CHAT_ID, "text": message}
    print(f"Attempting to send Telegram message to URL: {url} with params: {params}") # Debugging line added
    response = requests.get(url, params=params)
    print(f"Telegram API response: {response.json()}") # Print response for debugging

def get_naver_news(query):
    search_url = f"https://search.naver.com/search.naver?where=news&sm=tab_jum&query={query}"
    headers = {'User-Agent': 'Mozilla/5.0'}
    news_list = []
    try:
        response = requests.get(search_url, headers=headers)
        soup = BeautifulSoup(response.text, 'html.parser')
        # Find news titles and links
        news_elements = soup.select('div.news_area > a.news_title')
        for news in news_elements[:3]: # Get top 3 news articles
            news_list.append(f"- {news.get_text().strip()}: {news['href']}")
    except Exception as e:
        print(f"Error fetching Naver news for {query}: {e}")
    return "\n".join(news_list) if news_list else "(관련 뉴스 없음)"

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

    # 코스피, 코스닥 종목 리스트 가져오기
    df_krx = fdr.StockListing('KRX')

    # '스팩' 종목 제외
    df_krx = df_krx[~df_krx['Name'].str.contains('스팩', na=False)]

    count = 0

    for index, row in df_krx.iterrows():
        code = row['Code']
        name = row['Name']
        marcap = row['Marcap'] # 시가총액 정보 가져오기

        try:
            # 최근 200일치 데이터 가져오기
            df = fdr.DataReader(code)
            if len(df) < 160: continue # 상장한 지 얼마 안 된 종목 제외

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

                # Get Naver News
                news_articles = get_naver_news(name)

                # 시가총액 정보를 메시지에 추가
                formatted_marcap = format_marcap(marcap)
                msg = f"✅ [{type_msg}] 신호 발생!\n종목: {name} ({code})\n현재가: {df['Close'].iloc[-1]:,.0f}원\n시가총액: {formatted_marcap}\n기울기: {slope:.5f}\n\n[네이버 뉴스]\n{news_articles}"
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
