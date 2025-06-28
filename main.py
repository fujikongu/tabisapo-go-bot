
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, LocationMessage,
    TextSendMessage, QuickReply, QuickReplyButton, MessageAction
)
import os
import openai
import requests
import time

app = Flask(__name__)

# 環境変数
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
openai.api_key = OPENAI_API_KEY

# ユーザーのジャンル選択保存
user_selected_genre = {}

# クイックリプライのジャンル候補
genre_labels = [
    "トイレ", "駐車場", "飲食店", "カフェ", "ホテル",
    "観光地", "温泉", "遊び場", "コンビニ", "駅"
]

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    user_id = event.source.user_id
    text = event.message.text

    if text in genre_labels:
        user_selected_genre[user_id] = text
        reply = TextSendMessage(text=f"📍「{text}」を探します！\n現在地を送信してください。")
    else:
        buttons = [
            QuickReplyButton(action=MessageAction(label=label, text=label))
            for label in genre_labels
        ]
        reply = TextSendMessage(
            text="👇 探したいジャンルを選んでください",
            quick_reply=QuickReply(items=buttons)
        )
    line_bot_api.reply_message(event.reply_token, reply)

@handler.add(MessageEvent, message=LocationMessage)
def handle_location(event):
    user_id = event.source.user_id
    genre = user_selected_genre.get(user_id)

    if not genre:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="先にジャンルを選んでください。")
        )
        return

    lat = event.message.latitude
    lng = event.message.longitude

    # API初回リクエスト
    maps_url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    all_results = []

    params = {
        "location": f"{lat},{lng}",
        "radius": 10000,
        "keyword": genre,
        "language": "ja",
        "key": GOOGLE_API_KEY
    }

    for _ in range(3):  # 最大3ページ分取得
        res = requests.get(maps_url, params=params).json()
        results = res.get("results", [])
        all_results.extend(results)

        next_page_token = res.get("next_page_token")
        if not next_page_token:
            break
        time.sleep(2)  # next_page_token が有効になるまで少し待機
        params = {
            "pagetoken": next_page_token,
            "key": GOOGLE_API_KEY
        }

    if not all_results:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"{genre}が近くに見つかりませんでした。")
        )
        return

    messages = []
    for spot in all_results[:10]:  # 表示件数は10件まで（LINE制限に配慮）
        name = spot.get("name", "名称不明")
        address = spot.get("vicinity", "住所不明")
        lat = spot["geometry"]["location"]["lat"]
        lng = spot["geometry"]["location"]["lng"]
        map_link = f"https://www.google.com/maps/search/?api=1&query={lat},{lng}"

        prompt = f"{genre}のジャンルでおすすめスポット「{name}」について、旅行者向けにやさしいトーンでおすすめ理由と雰囲気を短く案内してください。"
        try:
            completion = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}]
            )
            gpt_msg = completion.choices[0].message["content"]
        except:
            gpt_msg = "旅行者におすすめのスポットです！"

        message = f"🏞️ {name}\n📍 {address}\n\n{gpt_msg}\n\n👉 [Googleマップで見る]({map_link})"
        messages.append(TextSendMessage(text=message))

    for i in range(0, len(messages), 5):
        line_bot_api.reply_message(event.reply_token, messages[i:i+5])

# 🔽 決定事項：Render用起動処理
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
