import os
import re
import base64
import tkinter as tk
from tkinter import filedialog
from dotenv import load_dotenv
import anthropic
import speech_recognition as sr
import pyttsx3
from prompt_toolkit import prompt as pt_prompt

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

engine = pyttsx3.init()
engine.setProperty('rate', 175)

recognizer = sr.Recognizer()

last_reply = ""

def speak(text):
    global engine
    clean_text = re.sub(r'[^\x00-\x7F]+', '', text)
    try:
        engine.say(clean_text)
        engine.runAndWait()
    except Exception:
        engine = pyttsx3.init()
        engine.setProperty('rate', 175)
        engine.say(clean_text)
        engine.runAndWait()

def listen():
    with sr.Microphone() as source:
        print("Listening... speak now")
        recognizer.adjust_for_ambient_noise(source, duration=1)
        try:
            audio = recognizer.listen(source, timeout=5)
            text = recognizer.recognize_google(audio)
            print(f"You said: {text}")
            return text
        except sr.WaitTimeoutError:
            print("No speech detected, try again.")
            return None
        except sr.UnknownValueError:
            print("Could not understand, try again.")
            return None

def pick_image():
    root = tk.Tk()
    root.withdraw()
    root.wm_attributes('-topmost', True)
    file_path = filedialog.askopenfilename(
        title="Select an image",
        filetypes=[("Image files", "*.jpg *.jpeg *.png *.gif *.webp")]
    )
    root.destroy()
    return file_path

def load_image(image_path):
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

def chat_with_image(image_path, question):
    print(f"Looking at image: {image_path}")
    try:
        image_data, media_type = load_image(image_path)
        message = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=1024,
            system="You are a personal AI assistant named Bee. You are sweet, friendly, smart and always helpful.",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_data,
                            },
                        },
                        {
                            "type": "text",
                            "text": question
                        }
                    ],
                }
            ],
        )
        return message.content[0].text
    except FileNotFoundError:
        return f"Sorry, I could not find the image at: {image_path}"
    except Exception as e:
        return f"Sorry, I had trouble reading that image: {str(e)}"

print("Bee is ready to help you!")
print("Press ENTER to use voice, or type your message.")
print("Type 'upload' to pick an image from your Mac.")
print("Type 'speak' to hear the last reply.")
print("Type 'quit' to exit.")
print("-" * 40)

conversation_history = []
speak_keywords = ["read it", "say it", "speak", "read that", "say that", "say out loud", "read out"]

while True:
    user_input = pt_prompt("You (press ENTER for voice): ").strip()

    if user_input == "":
        user_input = listen()
        if user_input is None:
            continue

    if not user_input:
        continue

    if user_input.lower() == "quit":
        print("Goodbye!")
        speak("Goodbye!")
        break

    # Speak last reply
    if any(word in user_input.lower() for word in speak_keywords):
        if last_reply:
            print("Speaking last reply...")
            speak(last_reply)
        else:
            print("Nothing to speak yet!")
        continue

    # Upload image using file picker
    if user_input.lower() == "upload":
        print("Opening file picker...")
        image_path = pick_image()
        if not image_path:
            print("No image selected.")
            continue
        print(f"Image selected: {image_path}")
        question = pt_prompt("What do you want to know about this image? ").strip()
        if not question:
            question = "What do you see in this image?"
        ai_reply = chat_with_image(image_path, question)
        last_reply = ai_reply
        print(f"Bee: {ai_reply}")
        print("-" * 40)
        print("(type 'speak' to hear this out loud)")
        continue

    # Image via path
    if user_input.lower().startswith("image:"):
        parts = user_input[6:].strip().split(" ", 1)
        image_path = parts[0].strip()
        question = parts[1].strip() if len(parts) > 1 else "What do you see in this image?"
        ai_reply = chat_with_image(image_path, question)
        last_reply = ai_reply
        print(f"Bee: {ai_reply}")
        print("-" * 40)
        print("(type 'speak' to hear this out loud)")
        continue

    # Regular chat
    conversation_history.append({
        "role": "user",
        "content": user_input
    })

    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=1024,
        system="You are a personal AI assistant named Bee. You are sweet, friendly, smart and always helpful. Remember everything the user tells you. Always introduce yourself as Bee when asked.",
        messages=conversation_history
    )

    ai_reply = message.content[0].text
    last_reply = ai_reply

    conversation_history.append({
        "role": "assistant",
        "content": ai_reply
    })

    print(f"Bee: {ai_reply}")
    print("-" * 40)
    print("(type 'speak' to hear this out loud)")