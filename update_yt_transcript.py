import re
import json
from flask import Flask, request, jsonify
from youtube_transcript_api import YouTubeTranscriptApi
import cv2
import requests
import numpy as np
from skimage.metrics import structural_similarity as ssim
from flask_cors import CORS
from pytube import YouTube
import pytube.exceptions
import sqlite3

app = Flask(__name__)
CORS(app)

# SQLite setup
def get_db_connection():
    conn = sqlite3.connect('youtube_urls.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    conn.execute('''CREATE TABLE IF NOT EXISTS urls
                    (id INTEGER PRIMARY KEY AUTOINCREMENT,
                     url TEXT UNIQUE NOT NULL)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS video_info
                    (id INTEGER PRIMARY KEY AUTOINCREMENT,
                     url TEXT UNIQUE NOT NULL,
                     title TEXT,
                     thumbnail_url TEXT,
                     duration TEXT)''')
    conn.commit()
    conn.close()

init_db()

def extract_video_id(url):
    video_id_match = re.search(r"(?:v=|\/)([0-9A-Za-z_-]{11}).*", url)
    return video_id_match.group(1) if video_id_match else None

def get_transcript(video_id):
    try:
        return YouTubeTranscriptApi.get_transcript(video_id)
    except Exception as e:
        print(f"Error fetching transcript for video {video_id}: {e}")
        return None

def find_timestamps(transcript, search_term):
    timestamps = []
    for entry in transcript:
        if search_term.lower() in entry['text'].lower():
            timestamps.append(int(entry['start']))
    return timestamps

def format_results(url, timestamps):
    video_id = extract_video_id(url)
    return {f"{url}": [f"{url}&t={ts}s" for ts in timestamps]}

def process_videos(urls, search_term):
    results = {}
    for url in urls:
        video_id = extract_video_id(url)
        
        if video_id:
            transcript = get_transcript(video_id)
            if transcript:
                timestamps = find_timestamps(transcript, search_term)
                results.update(format_results(url, timestamps))
            else:
                results[f"{url}"] = "Failed to fetch transcript"
        else:
            results[f"{url}"] = "Invalid YouTube URL"
    return results

@app.route('/add_url', methods=['POST'])
def add_urls():
    data = request.get_json()
    new_url = data.get('url')
    
    conn = get_db_connection()
    try:
        conn.execute('INSERT INTO urls (url) VALUES (?)', (new_url,))
        conn.commit()
        
        # Fetch and store video info
        video_id = extract_video_id(new_url)
        if video_id:
            yt = YouTube(new_url)
            title = yt.title
            thumbnail_url = yt.thumbnail_url
            duration = convert_duration(yt.length)
            
            conn.execute('INSERT INTO video_info (url, title, thumbnail_url, duration) VALUES (?, ?, ?, ?)',
                         (new_url, title, thumbnail_url, duration))
            conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify("URL already exists"), 400
    except Exception as e:
        conn.close()
        return jsonify(f"Error adding URL: {str(e)}"), 500
    
    urls = [row['url'] for row in conn.execute('SELECT url FROM urls').fetchall()]
    conn.close()
    return jsonify(urls)

def convert_duration(seconds):
    hours = seconds // 3600
    seconds %= 3600
    minutes = seconds // 60
    seconds %= 60
    duration = ""
    if hours > 0:
        duration += f"{hours} hrs "
    if minutes > 0:
        duration += f"{minutes} mins "
    duration += f"{seconds} secs"
    return duration

@app.route('/fetch_video_info', methods=['GET'])
def fetch_video_info():
    conn = get_db_connection()
    video_info = conn.execute('SELECT url, title, thumbnail_url, duration FROM video_info').fetchall()
    conn.close()

    results = []
    for info in video_info:
        format_info = {
            info['url']: {
                'title': info['title'],
                'thumbnail_url': info['thumbnail_url'],
                'duration': info['duration'],
            }
        }
        results.append(format_info)

    return jsonify(results)

@app.route('/search', methods=['POST'])
def search():
    data = request.get_json()
    search_term = data.get('search_term')

    conn = get_db_connection()
    urls = [row['url'] for row in conn.execute('SELECT url FROM urls').fetchall()]
    conn.close()

    if not search_term or not urls:
        return jsonify({"error": "search_term or no URLs found"}), 400

    results = process_videos(urls, search_term)
    return jsonify(results)

@app.route('/rm_url', methods=["DELETE"])
def rm_url():
    data = request.get_json()
    delete_url = data.get('url')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM urls WHERE url = ?', (delete_url,))
    cursor.execute('DELETE FROM video_info WHERE url = ?', (delete_url,))
    
    if cursor.rowcount == 0:
        conn.close()
        return jsonify("Video is not in the database"), 404
    
    conn.commit()
    conn.close()
    return jsonify("Removed video successfully")

if __name__ == '__main__':
    app.run(debug=True,port='5000')