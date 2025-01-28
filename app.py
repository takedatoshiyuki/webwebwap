import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore, initialize_app

#from langchain.chat_models import ChatOpenAI, BedrockChat, ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from langchain_aws import ChatBedrock
from langchain_google_genai import ChatGoogleGenerativeAI

from langchain.schema import HumanMessage, AIMessage
from langchain.callbacks import StreamlitCallbackHandler
from google.cloud.firestore import SERVER_TIMESTAMP
import json
import os
from datetime import datetime

# Firebase初期化
import json
from dotenv import load_dotenv
load_dotenv()

# グローバル変数
db = None
temperature = 0.7

def get_firestore_client():
    global db
    if db is not None:
        return db
        
    try:
        # Streamlit Cloudの場合はsecretsから、ローカルの場合は環境変数から取得
        if hasattr(st, "secrets"):
            cred_json = st.secrets["FIREBASE_CREDENTIALS"]
        else:
            cred_json = os.getenv('FIREBASE_CREDENTIALS')
            
        if not cred_json:
            st.error("Firebase認証情報が設定されていません。")
            st.stop()
            
        try:
            cred_dict = json.loads(cred_json)
        except json.JSONDecodeError as je:
            st.error("認証情報のJSONパースに失敗しました。")
            st.stop()
            
        if not firebase_admin._apps:
            cred = credentials.Certificate(cred_dict)
            initialize_app(cred)
        
        db = firestore.client()
        return db
    except Exception as e:
        st.error(f"Firebase初期化エラー: {str(e)}")
        st.stop()

db = get_firestore_client()

# Streamlitの設定
st.set_page_config(page_title="AI Chat Application", layout="wide")

# セッション状態の初期化
if "messages" not in st.session_state:
    st.session_state.messages = []
if "chat_id" not in st.session_state:
    st.session_state.chat_id = None

# サイドバー - AIモデル選択
model_options = {
    "GPT-4o Mini": "gpt-4o-mini",
    "GPT-4o": "gpt-4o",
    "Claude 3.5 Sonnet": "anthropic.claude-3-5-sonnet-20240620-v1:0",
    "Gemini 1.5 Flash": "gemini-1.5-flash",
}
selected_model = st.sidebar.selectbox("AIモデルを選択", list(model_options.keys()))

# サイドバー - 新規チャット
if st.sidebar.button("➕ 新規チャット", type="primary"):
    st.session_state.messages = []
    st.session_state.chat_id = None
    st.rerun()

st.sidebar.divider()

# サイドバー - チャット履歴
st.sidebar.header("チャット履歴")

chats_ref = db.collection('chat_sessions')
chats = chats_ref.order_by('timestamp', direction=firestore.Query.DESCENDING).stream()
chat_list = []
for chat in chats:
    chat_data = chat.to_dict()
    # チャットの最初のメッセージを取得
    first_message = chats_ref.document(chat.id).collection('messages').order_by('timestamp').limit(1).get()
    title = "新しいチャット"  # デフォルトタイトル
    if first_message:
        first_msg_data = first_message[0].to_dict()
        # 最初の20文字を取得（日本語の場合は約10文字程度）
        title = first_msg_data.get('content', '')[:20] + ('...' if len(first_msg_data.get('content', '')) > 20 else '')
    
    chat_list.append({
        'id': chat.id,
        'timestamp': chat_data['timestamp'],
        'model': chat_data['model'],
        'title': title
    })

if chat_list:
    selected_chat = st.sidebar.selectbox(
        "過去のチャットを選択",
        options=chat_list,
        format_func=lambda x: f"{x['title']} ({x['timestamp'].strftime('%m/%d %H:%M')})"
    )
    if st.sidebar.button("チャットを読み込む"):
        st.session_state.chat_id = selected_chat['id']
        # チャット履歴を読み込む
        messages_ref = chats_ref.document(selected_chat['id']).collection('messages')
        messages = messages_ref.order_by('timestamp').stream()
        st.session_state.messages = []
        for msg in messages:
            msg_data = msg.to_dict()
            if msg_data['role'] == 'human':
                st.session_state.messages.append(HumanMessage(content=msg_data['content']))
            else:
                st.session_state.messages.append(AIMessage(content=msg_data['content']))

# チャットインターフェース
st.title("AI Chat Application")

# メッセージ表示
for message in st.session_state.messages:
    if isinstance(message, HumanMessage):
        st.chat_message("user").write(message.content)
    else:
        st.chat_message("assistant").write(message.content)

# チャットモデルの初期化
def get_chat_model(model_name):
    global temperature
    if "gpt" in model_name.lower():
        return ChatOpenAI(
            model_name=model_options[model_name],
            streaming=True,
            temperature=temperature
        )
    elif "claude" in model_name.lower():
        return ChatBedrock(
            model_id=model_options[model_name],
            streaming=True,
            model_kwargs={"temperature": temperature}
        )
    else:  # Gemini models
        # Geminiのモデル初期化（具体的な実装はGemini APIの仕様に応じて調整）
        return ChatGoogleGenerativeAI(
            temperature=temperature,
            model=model_options[model_name]
        )

# ユーザー入力処理
if prompt := st.chat_input():
    # 新しいチャットの場合、チャットIDを生成
    if not st.session_state.chat_id:
        chat_ref = chats_ref.document()
        st.session_state.chat_id = chat_ref.id
        chat_ref.set({
            'timestamp': SERVER_TIMESTAMP,
            'model': selected_model
        })

    # メッセージをセッションとFirestoreに追加
    st.session_state.messages.append(HumanMessage(content=prompt))
    chats_ref.document(st.session_state.chat_id).collection('messages').add({
        'role': 'human',
        'content': prompt,
        'timestamp': SERVER_TIMESTAMP
    })

    # チャットメッセージを表示
    st.chat_message("user").write(prompt)

    # AIの応答を生成
    chat_model = get_chat_model(selected_model)
    with st.chat_message("assistant"):
        callback = StreamlitCallbackHandler(st.container())
        response = chat_model.generate([st.session_state.messages], callbacks=[callback])
        ai_message = response.generations[0][0].text
        st.write(ai_message)

    # AI応答をセッションとFirestoreに追加
    st.session_state.messages.append(AIMessage(content=ai_message))
    chats_ref.document(st.session_state.chat_id).collection('messages').add({
        'role': 'assistant',
        'content': ai_message,
        'timestamp': SERVER_TIMESTAMP
    })
