# chat_history_viewer.py
import streamlit as st
import json
import os
import firebase_admin
from firebase_admin import credentials, firestore, initialize_app
from datetime import datetime
import pytz
from dotenv import load_dotenv
load_dotenv()

# Streamlitの設定
st.set_page_config(page_title="Chat History Viewer", layout="wide")

# グローバル変数
db = None

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

def convert_to_jst(timestamp):
    """FirestoreのタイムスタンプをJST日時に変換"""
    if timestamp is None:
        return None
    # UTCとして取得したタイムスタンプをJSTに変換
    jst = pytz.timezone('Asia/Tokyo')
    return timestamp.astimezone(jst)

def get_chat_history():
    db = get_firestore_client()
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
            title = first_msg_data.get('content', '')[:20] + ('...' if len(first_msg_data.get('content', '')) > 20 else '')
        
        # タイムスタンプをJSTに変換
        timestamp = chat_data.get('timestamp')
        if timestamp:
            timestamp = convert_to_jst(timestamp)
        
        chat_list.append({
            'id': chat.id,
            'timestamp': timestamp,
            'model': chat_data.get('model', 'Unknown'),
            'title': title
        })
    return chat_list

def main():
    st.title("チャット履歴ビューア")
    
    # サイドバーにチャット一覧を表示
    st.sidebar.header("チャット履歴")
    chat_list = get_chat_history()

    if not chat_list:
        st.info("チャット履歴がありません。")
        return

    # チャット選択
    selected_chat = st.sidebar.selectbox(
        "チャットを選択",
        options=chat_list,
        format_func=lambda x: f"{x['title']} ({x['timestamp'].strftime('%m/%d %H:%M')})"
    )

    if selected_chat:
        # チャット情報の表示
        st.subheader(f"{selected_chat['title']}")
        st.caption(f"作成日時: {selected_chat['timestamp'].strftime('%Y/%m/%d %H:%M:%S')} (JST) | モデル: {selected_chat['model']}")
        st.divider()
        
        try:
            # メッセージ一覧の取得と表示
            db = get_firestore_client()
            messages_ref = db.collection('chat_sessions').document(selected_chat['id']).collection('messages')
            messages = messages_ref.order_by('timestamp').stream()

            # メッセージの表示
            for msg in messages:
                msg_data = msg.to_dict()
                is_user = msg_data.get('role') == 'human'
                timestamp = convert_to_jst(msg_data.get('timestamp'))
                
                # メッセージの表示スタイルを設定
                with st.chat_message("user" if is_user else "assistant"):
                    st.markdown(msg_data.get('content', ''))
                if timestamp:
                    st.caption(f"送信時刻: {timestamp.strftime('%Y/%m/%d %H:%M:%S')} (JST)")
        except Exception as e:
            st.error(f"メッセージの読み込み中にエラーが発生しました: {str(e)}")
            st.error(f"選択されたチャットID: {selected_chat['id']}")
            st.error("データベースの接続を確認してください。")

if __name__ == "__main__":
    main()