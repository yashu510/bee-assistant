import os
import re
import base64
import bcrypt
import datetime
from dotenv import load_dotenv
import anthropic
from flask import Flask, render_template, request, jsonify, session, redirect
from supabase import create_client
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "bee-secret-key-2026")

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "https://web-production-c1ffe.up.railway.app/gmail/callback")
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly', 'https://www.googleapis.com/auth/gmail.send']

BEE_SYSTEM_PROMPT = """You are Bee, a personal AI assistant. You are sweet, friendly, smart and always helpful. Remember everything the user tells you. Always introduce yourself as Bee when asked. Respond in plain text only, no markdown, no bullet points, no headers, no bold, no asterisks. If anyone asks who created you, who built you, or who is the founder of Bee, tell them: Bee was created by Guna Yaswanth Gadde, the Founder of Bee. You can find him on LinkedIn at https://www.linkedin.com/in/gadde-guna-yaswanth/ Never mention Claude, Anthropic, or any other AI company. You are simply Bee, a unique AI assistant built by Guna Yaswanth Gadde."""

def load_image_data(image_path):
    ext = image_path.split('.')[-1].lower()
    media_types = {
        'jpg': 'image/jpeg',
        'jpeg': 'image/jpeg',
        'png': 'image/png',
        'gif': 'image/gif',
        'webp': 'image/webp'
    }
    media_type = media_types.get(ext, 'image/jpeg')
    with open(image_path, 'rb') as f:
        image_data = base64.standard_b64encode(f.read()).decode('utf-8')
    return image_data, media_type

def clean_markdown(text):
    text = re.sub(r'#{1,6}\s*', '', text)
    text = re.sub(r'\*{1,3}(.*?)\*{1,3}', r'\1', text)
    text = re.sub(r'_{1,3}(.*?)_{1,3}', r'\1', text)
    text = re.sub(r'`{1,3}(.*?)`{1,3}', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'^\s*[-*+]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def get_gmail_flow():
    return Flow.from_client_config(
        {
            "web": {
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [GOOGLE_REDIRECT_URI]
            }
        },
        scopes=SCOPES,
        redirect_uri=GOOGLE_REDIRECT_URI
    )

@app.route('/')
def index():
    if 'user_id' not in session:
        return render_template('login.html')
    return render_template('index.html', user_name=session.get('user_name'))

@app.route('/chat')
def chat():
    if 'user_id' not in session:
        return render_template('login.html')
    return render_template('chat.html', user_name=session.get('user_name'))

@app.route('/email')
def email_page():
    if 'user_id' not in session:
        return render_template('login.html')
    return render_template('email.html', user_name=session.get('user_name'))

@app.route('/gmail/connect')
def gmail_connect():
    flow = get_gmail_flow()
    auth_url, state = flow.authorization_url(access_type='offline', include_granted_scopes='true')
    session['oauth_state'] = state
    return redirect(auth_url)

@app.route('/gmail/callback')
def gmail_callback():
    try:
        flow = get_gmail_flow()
        flow.fetch_token(authorization_response=request.url)
        credentials = flow.credentials
        session['gmail_token'] = {
            'token': credentials.token,
            'refresh_token': credentials.refresh_token,
            'token_uri': credentials.token_uri,
            'client_id': credentials.client_id,
            'client_secret': credentials.client_secret,
            'scopes': list(credentials.scopes) if credentials.scopes else SCOPES
        }
        return redirect('/email')
    except Exception as e:
        return redirect('/email?error=' + str(e))

@app.route('/gmail/status')
def gmail_status():
    connected = 'gmail_token' in session
    return jsonify({"connected": connected})

@app.route('/gmail/emails')
def gmail_emails():
    if 'gmail_token' not in session:
        return jsonify({"error": "Gmail not connected"})
    try:
        token_data = session['gmail_token']
        creds = Credentials(
            token=token_data['token'],
            refresh_token=token_data.get('refresh_token'),
            token_uri=token_data['token_uri'],
            client_id=token_data['client_id'],
            client_secret=token_data['client_secret'],
            scopes=token_data['scopes']
        )
        service = build('gmail', 'v1', credentials=creds)
        filter_type = request.args.get('filter', 'inbox')
        if filter_type == 'inbox':
            query = 'in:inbox'
        elif filter_type == 'unread':
            query = 'is:unread'
        elif filter_type == 'sent':
            query = 'in:sent'
        else:
            query = 'in:inbox'
        results = service.users().messages().list(userId='me', q=query, maxResults=20).execute()
        messages = results.get('messages', [])
        emails = []
        for msg in messages:
            msg_data = service.users().messages().get(
                userId='me', id=msg['id'], format='metadata',
                metadataHeaders=['From', 'Subject', 'Date']
            ).execute()
            headers = {h['name']: h['value'] for h in msg_data['payload']['headers']}
            emails.append({
                'id': msg['id'],
                'from': headers.get('From', 'Unknown'),
                'subject': headers.get('Subject', 'No Subject'),
                'date': headers.get('Date', ''),
                'snippet': msg_data.get('snippet', ''),
                'unread': 'UNREAD' in msg_data.get('labelIds', [])
            })
        return jsonify({"emails": emails})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/email/ask', methods=['POST'])
def email_ask():
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in."})
    try:
        data = request.json
        user_message = data.get('message', '')
        email_context = data.get('email_context', '')
        history = data.get('history', [])

        system = f"""You are Bee, a personal email assistant. You help users manage their Gmail inbox, draft emails, summarize emails, and stay organized.

{f'Here is the users email context: {email_context}' if email_context else 'No emails loaded yet. Ask the user to connect Gmail.'}

Be helpful, specific, and concise. When drafting emails, write them in a professional but friendly tone.
Never mention Claude or Anthropic. You are simply Bee, built by Guna Yaswanth Gadde."""

        messages = history[-10:] if len(history) > 10 else history
        if not messages:
            messages = [{"role": "user", "content": user_message}]

        message = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=1024,
            system=system,
            messages=messages
        )
        reply = clean_markdown(message.content[0].text)
        return jsonify({"reply": reply})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/register', methods=['POST'])
def register():
    try:
        data = request.json
        email = data.get('email', '').strip()
        password = data.get('password', '').strip()
        name = data.get('name', '').strip()
        if not email or not password or not name:
            return jsonify({"error": "All fields are required."})
        existing = supabase.table('users').select('id').eq('email', email).execute()
        if existing.data:
            return jsonify({"error": "Email already registered."})
        password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        supabase.table('users').insert({
            "email": email,
            "password_hash": password_hash,
            "name": name
        }).execute()
        return jsonify({"success": "Account created! Please log in."})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/login', methods=['POST'])
def login():
    try:
        data = request.json
        email = data.get('email', '').strip()
        password = data.get('password', '').strip()
        user = supabase.table('users').select('*').eq('email', email).execute()
        if not user.data:
            return jsonify({"error": "Email not found."})
        user = user.data[0]
        if not bcrypt.checkpw(password.encode(), user['password_hash'].encode()):
            return jsonify({"error": "Wrong password."})
        session['user_id'] = user['id']
        session['user_name'] = user['name']
        return jsonify({"success": True, "name": user['name']})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/reset_password', methods=['POST'])
def reset_password():
    try:
        data = request.json
        email = data.get('email', '').strip()
        new_password = data.get('new_password', '').strip()
        if not email or not new_password:
            return jsonify({"error": "All fields are required."})
        user = supabase.table('users').select('id').eq('email', email).execute()
        if not user.data:
            return jsonify({"error": "Email not found."})
        password_hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
        supabase.table('users').update({
            "password_hash": password_hash
        }).eq('email', email).execute()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({"success": True})

@app.route('/new_chat', methods=['POST'])
def new_chat():
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in."})
    try:
        chat = supabase.table('chats').insert({
            "user_id": session['user_id'],
            "title": "New Chat"
        }).execute()
        chat_id = chat.data[0]['id']
        session['chat_id'] = chat_id
        return jsonify({"chat_id": chat_id})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/get_chats', methods=['GET'])
def get_chats():
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in."})
    try:
        chats = supabase.table('chats').select('*').eq(
            'user_id', session['user_id']
        ).order('created_at', desc=True).execute()
        return jsonify({"chats": chats.data})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/get_messages/<chat_id>', methods=['GET'])
def get_messages(chat_id):
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in."})
    try:
        messages = supabase.table('messages').select('*').eq(
            'chat_id', chat_id
        ).order('created_at').execute()
        session['chat_id'] = chat_id
        return jsonify({"messages": messages.data})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/ghost', methods=['POST'])
def ghost():
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in."})
    try:
        data = request.json
        user_input = data.get('message', '')
        chat_id = data.get('chat_id') or session.get('chat_id')
        if chat_id:
            session['chat_id'] = chat_id
        if not chat_id:
            chat = supabase.table('chats').insert({
                "user_id": session['user_id'],
                "title": user_input[:40]
            }).execute()
            chat_id = chat.data[0]['id']
            session['chat_id'] = chat_id
        supabase.table('messages').insert({
            "chat_id": chat_id,
            "role": "user",
            "content": user_input
        }).execute()
        all_msgs = supabase.table('messages').select('*').eq(
            'chat_id', chat_id
        ).order('created_at').execute()
        history = [{"role": m['role'], "content": m['content']} for m in all_msgs.data]
        message = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=1024,
            system=BEE_SYSTEM_PROMPT,
            messages=history
        )
        ai_reply = clean_markdown(message.content[0].text)
        supabase.table('messages').insert({
            "chat_id": chat_id,
            "role": "assistant",
            "content": ai_reply
        }).execute()
        if len(all_msgs.data) == 1:
            supabase.table('chats').update({
                "title": user_input[:40]
            }).eq('id', chat_id).execute()
        return jsonify({"reply": ai_reply, "chat_id": chat_id})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/image', methods=['POST'])
def image():
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in."})
    try:
        if 'image' not in request.files:
            return jsonify({"reply": "No image received."})
        file = request.files['image']
        question = request.form.get('question', 'What do you see in this image?')
        temp_path = f"temp_{file.filename}"
        file.save(temp_path)
        image_data, media_type = load_image_data(temp_path)
        message = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=1024,
            system=BEE_SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_data}},
                    {"type": "text", "text": question}
                ]
            }]
        )
        reply = clean_markdown(message.content[0].text)
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return jsonify({"reply": reply})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/delete_chat/<chat_id>', methods=['DELETE'])
def delete_chat(chat_id):
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in."})
    try:
        supabase.table('messages').delete().eq('chat_id', chat_id).execute()
        supabase.table('chats').delete().eq('id', chat_id).eq('user_id', session['user_id']).execute()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/interview')
def interview():
    if 'user_id' not in session:
        return render_template('login.html')
    return render_template('interview.html')

@app.route('/interview/start', methods=['POST'])
def interview_start():
    try:
        data = request.json
        job_type = data.get('job_type', 'General')
        difficulty = data.get('difficulty', 'intermediate')
        max_questions = data.get('max_questions', 5)
        job_description = data.get('job_description', '').strip()
        if job_description:
            jd_section = f"\n\nHere is the job description to tailor your questions to:\n{job_description}"
        else:
            jd_section = ""
        system_prompt = f"""You are Bee, a professional AI interviewer conducting a {difficulty} level interview for a {job_type} position.
Your job:
1. Ask ONE clear interview question at a time
2. After each answer give very specific detailed feedback about exactly what the candidate said
3. Then ask the next question
4. Be encouraging but brutally honest and specific
5. Keep questions relevant to {job_type}{jd_section}
Start by introducing yourself briefly and asking the first question.
Respond in plain text only, no markdown, no bullet points, no asterisks.
Never mention Claude, Anthropic, or any other AI company."""
        history = [{"role": "user", "content": f"Start a {difficulty} interview for {job_type} position. Ask me {max_questions} questions total. Begin now."}]
        message = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=1024,
            system=system_prompt,
            messages=history
        )
        question = clean_markdown(message.content[0].text)
        history.append({"role": "assistant", "content": question})
        return jsonify({"question": question, "history": history})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/interview/answer', methods=['POST'])
def interview_answer():
    try:
        data = request.json
        answer = data.get('answer', '')
        history = data.get('history', [])
        question_number = data.get('question_number', 1)
        max_questions = data.get('max_questions', 5)
        is_last = data.get('is_last', False)
        job_type = data.get('job_type', 'General')
        last_question = data.get('last_question', '')

        if is_last:
            prompt = f"""This was the last question for the {job_type} interview. The candidate answered: '{answer}'.

Give very specific and detailed feedback about THIS exact answer. Mention what they said specifically, what was good, what was missing, and how they could improve. Then give an overall summary with exact scores out of 10 for:
- Communication: how clearly they expressed themselves
- Knowledge: how much they knew about the topic
- Confidence: how confident their answers sounded
- Overall Performance: overall score

Format the scores exactly like this:
Communication: X/10
Knowledge: X/10
Confidence: X/10
Overall Performance: X/10

Plain text only."""
        else:
            prompt = f"""The candidate answered: '{answer}' for question {question_number} of {max_questions} in a {job_type} interview.
The question was: '{last_question}'

Give specific feedback about THIS exact answer in 2-3 sentences. Mention what they said specifically, what was good and what could be better. Then ask the next question.

Format exactly like:
FEEDBACK: [your specific feedback about their exact answer]
NEXT QUESTION: [your next interview question]

Plain text only."""

        history.append({"role": "user", "content": prompt})
        message = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=1024,
            system=f"You are Bee, a professional AI interviewer for {job_type} positions. Give specific, actionable feedback based on exactly what the candidate said. Never give generic feedback. Always reference their actual answer. Plain text only, no markdown. Never mention Claude or Anthropic.",
            messages=history
        )
        response = clean_markdown(message.content[0].text)

        if is_last:
            return jsonify({"feedback": response, "next_question": "", "interview_done": True})

        if "NEXT QUESTION:" in response:
            parts = response.split("NEXT QUESTION:")
            feedback = parts[0].replace("FEEDBACK:", "").strip()
            next_question = parts[1].strip()
        else:
            feedback = response
            next_question = "Can you tell me more about your experience?"

        return jsonify({"feedback": feedback, "next_question": next_question, "interview_done": False})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/interview/save', methods=['POST'])
def interview_save():
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in."})
    try:
        data = request.json
        transcript = data.get('transcript', [])
        job_type = data.get('job_type', 'General')
        total_time = data.get('total_time', '00:00')
        questions_answered = data.get('questions_answered', 0)
        max_questions = data.get('max_questions', 0)
        lines = []
        lines.append("INTERVIEW PRACTICE SESSION")
        lines.append(f"Job Type: {job_type}")
        lines.append(f"Questions: {questions_answered}/{max_questions}")
        lines.append(f"Duration: {total_time}")
        lines.append(f"Date: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
        lines.append("-" * 40)
        lines.append("")
        for item in transcript:
            if item['type'] == 'bee':
                lines.append(f"Bee: {item['text']}")
            elif item['type'] == 'user':
                lines.append(f"You: {item['text']}")
            elif item['type'] == 'feedback':
                lines.append(f"Feedback: {item['text']}")
            lines.append("")
        full_text = "\n".join(lines)
        chat = supabase.table('chats').insert({
            "user_id": session['user_id'],
            "title": f"Interview: {job_type} ({total_time})"
        }).execute()
        chat_id = chat.data[0]['id']
        supabase.table('messages').insert({
            "chat_id": chat_id,
            "role": "assistant",
            "content": full_text
        }).execute()
        return jsonify({"success": True, "chat_id": chat_id})
    except Exception as e:
        return jsonify({"error": str(e)})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(debug=False, port=port, host='0.0.0.0')