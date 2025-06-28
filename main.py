
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

# 環境変数から取得
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
openai.api_key = OPENAI_API_KEY

# ユーザーごとのジャンル記憶
user_selected_genre = {}

# ジャンル（13件：LINE QuickReply上限）
genre_labels = [
    "トイレ", "駐車場", "ラーメン", "和食", "中華", "焼肉", "ファミレス",
    "カフェ", "ホテル", "観光地", "温泉", "遊び場", "コンビニ"
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
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"📍「{text}」を探します！\n現在地を送信してください。")
        )
    else:
        quick_reply = QuickReply(
            items=[
                QuickReplyButton(action=MessageAction(label=label, text=label))
                for label in genre_labels
            ]
        )
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(
                text="👇 探したいジャンルを選んでください",
                quick_reply=quick_reply
            )
        )

@handler.add(MessageEvent, message=LocationMessage)
def handle_location(event):
    user_id = event.source.user_id
    genre = user_selected_genre.pop(user_id, None)

    if not genre:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="先にジャンルを選んでください。")
        )
        return

    lat = event.message.latitude
    lng = event.message.longitude

    # Google Maps APIリクエスト
    maps_url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    params = {
        "location": f"{lat},{lng}",
        "radius": 10000,
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

    messages = []
    for spot in results[:10]:  # 最大10件
        name = spot.get("name", "名称不明")
        address = spot.get("vicinity", "住所不明")
        place_lat = spot["geometry"]["location"]["lat"]
        place_lng = spot["geometry"]["location"]["lng"]
        map_link = f"https://www.google.com/maps/search/?api=1&query={place_lat},{place_lng}"

        # ChatGPT案内文
        prompt = f"""あなたは観光案内人です。以下のスポットを観光客におすすめするとしたら、どう紹介しますか？

名称：{name}
ジャンル：{genre}

場所の特徴や雰囲気、旅行者が嬉しいポイントを含めて、100文字以内でやさしい案内文をお願いします。
"""
        try:
            completion = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}]
            )
            gpt_message = completion.choices[0].message["content"].strip()
        except Exception as e:
            gpt_message = "旅行者におすすめのスポットです！"

        message_text = f"🏞️ {name}\n📍 {address}\n\n{gpt_message}\n\n👉 [Googleマップで見る]({map_link})"
        messages.append(TextSendMessage(text=message_text))

    # 返信 + 分割Push送信
    try:
        line_bot_api.reply_message(event.reply_token, messages[:5])
    except Exception as e:
        print("Replyエラー:", e)

    for msg in messages[5:]:
        try:
            line_bot_api.push_message(user_id, msg)
        except Exception as e:
            print("Pushエラー:", e)

# Render起動処理（固定）
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
