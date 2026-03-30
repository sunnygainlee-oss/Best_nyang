name: Stock Scanner Automation

on:
  schedule:
    # 한국 시간(KST) 평일(월~금) 20:00에 실행
    - cron: '0 11 * * 1-5'
  workflow_dispatch: # 수동 실행 버튼

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout code
        uses: actions/checkout@v3

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.10'

      - name: Install dependencies
        run: |
          pip install -r requirements.txt

      - name: Run Python Script
        env:
          TELEGRAM_TOKEN: ${{ secrets.TELEGRAM_TOKEN }}
          CHAT_ID: ${{ secrets.CHAT_ID }}
        run: python my_scanner.py
