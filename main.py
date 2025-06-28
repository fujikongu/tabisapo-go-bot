
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

app = Flask(__name__)

# 環境変数からトークン取得
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
openai.api_key = OPENAI_API_KEY

# ユーザーの選択ジャンルを一時保存
user_selected_genre = {}

# クイックリプライジャンル
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
        quick_reply_buttons = [
            QuickReplyButton(action=MessageAction(label=label, text=label))
            for label in genre_labels
        ]
        reply = TextSendMessage(
            text="👇 探したいジャンルを選んでください",
            quick_reply=QuickReply(items=quick_reply_buttons)
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

    # Google Maps APIでスポット検索
    maps_url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    params = {
        "location": f"{lat},{lng}",
        "radius": 3000,
        "keyword": genre,
        "language": "ja",
        "key": GOOGLE_API_KEY
    }
    res = requests.get(maps_url, params=params).json()
    results = res.get("results", [])

    if not results:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"{genre}が近くに見つかりませんでした。")
        )
        return

    # 最初のスポットだけ使う
    spot = results[0]
    name = spot.get("name")
    address = spot.get("vicinity", "")
    place_lat = spot["geometry"]["location"]["lat"]
    place_lng = spot["geometry"]["location"]["lng"]
    map_link = f"https://www.google.com/maps/search/?api=1&query={place_lat},{place_lng}"

    # ChatGPTで自然文生成
    prompt = f"{genre}のジャンルでおすすめスポット「{name}」について、旅行者向けにやさしいトーンでおすすめ理由と雰囲気を短く案内してください。"
    try:
        completion = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}]
        )
        gpt_message = completion.choices[0].message["content"]
    except Exception:
        gpt_message = "このスポットは旅行者におすすめの場所です！"

    reply_text = f"🏞️ {name}\n📍 {address}\n\n{gpt_message}\n\n👉 [Googleマップで見る]({map_link})"
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

if __name__ == "__main__":
    app.run()
