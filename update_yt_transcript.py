import pytube
import re
from flask import Flask, request, jsonify
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
from flask_cors import CORS
from pytube import YouTube
import sqlite3
import logging
# Configure logging
logging.basicConfig(filename='app.log', level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
# from google.cloud import speech_v1p1beta1 as speech
app = Flask(__name__)
CORS(app)

# SQLite setup
def get_db_connection():
    conn = sqlite3.connect('youtube_urls.db')
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def drop_tables():
    conn = get_db_connection()
    conn.execute('DROP TABLE IF EXISTS video_info')
    conn.execute('DROP TABLE IF EXISTS urls')
    conn.commit()
    conn.close()
def init_db():
    # drop_tables()  # Drop tables before creating them to ensure a clean state
    conn = get_db_connection()
    conn.execute('''CREATE TABLE IF NOT EXISTS urls
                    (id INTEGER PRIMARY KEY AUTOINCREMENT,
                     url TEXT UNIQUE NOT NULL)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS video_info
                    (id INTEGER PRIMARY KEY AUTOINCREMENT,
                     url TEXT UNIQUE NOT NULL,
                     title TEXT,
                     thumbnail_url TEXT,
                     duration INT,
                     url_id INTEGER,
                     FOREIGN KEY (url_id) REFERENCES urls(id) ON DELETE CASCADE)''')
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
    
def get_transcript(video_id):
    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=['en'])
        return transcript
    except NoTranscriptFound:
        transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=['hi'])
        try:
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
            for transcript in transcript_list:
                if transcript.is_generated:
                    return transcript.translate('en').fetch()
        except (TranscriptsDisabled, NoTranscriptFound):
            return None
    except Exception as e:
        print(f"Error fetching transcript for video {video_id}: {e}")
        return None

def find_timestamps(transcript, search_term):
    timestamps = []
    pattern = re.compile(rf'\b{re.escape(search_term)}\b', re.IGNORECASE)
    for entry in transcript:
        if pattern.search(entry['text']):
            timestamps.append(int(entry['start']))
    return timestamps

def format_results(url, timestamps):
    # return [f"{url}&t={ts}s" for ts in timestamps]
    return [ts for ts in timestamps]
    
        

def process_videos(url, search_term):
    results = []
    # for url in urls:
    video_id = extract_video_id(url)
        
    if video_id:
        transcript = get_transcript(video_id)
        if transcript:
            timestamps = find_timestamps(transcript, search_term)
            
            return format_results(url, timestamps)

        else:
           return ["Failed to fetch transcript"]
    else:
        return [f"Invalid YouTube URL: {url}"] 




@app.route('/add_url', methods=['POST'])
def add_urls():
    data = request.get_json()
    new_url = data.get('url')
    logging.info(f"Received request to add URL: {new_url}")
    if not new_url:
        logging.error("No URL provided")
        return jsonify({"response":"Please Provide the URL"}), 400
    
    # Extract the base video URL
    video_id = extract_video_id(new_url)
    if not video_id:
        logging.error(f"Invalid YouTube URL: {new_url}")
        return jsonify({"response":"Invalid YouTube URL"}), 400
    
    # Construct the base URL
    if 'shorts' in new_url:
        base_url = f"https://www.youtube.com/shorts/{video_id}"
    else:
        base_url = f"https://www.youtube.com/watch?v={video_id}"

    # Validate if the URL is a valid YouTube video
    try:
        yt = YouTube(base_url)
    except pytube.exceptions.RegexMatchError:
        logging.error(f"Invalid YouTube URL: {base_url}")
        return jsonify({"response":"Invalid YouTube URL"}), 400
    except pytube.exceptions.VideoUnavailable:
        logging.error(f"YouTube video is unavailable: {base_url}")
        return jsonify({"response" : "YouTube video is unavailable"}), 404
    except pytube.exceptions.PytubeError as e:
        logging.error(f"Error with pytube: {str(e)}")
        return jsonify({"response" : f"Error with pytube: {str(e)}"}), 500
    except Exception as e:
        logging.error(f"Unknown error validating URL: {str(e)}")
        return jsonify({"response" : f"Unknown error validating URL: {str(e)}"}), 500
    
    conn = get_db_connection()
    try:
        cursor  = conn.execute('INSERT INTO urls (url) VALUES (?)', (base_url,))
        conn.commit()
        url_id = cursor.lastrowid
        
        # Fetch and store video info
        # video_id = extract_video_id(video_id)
        if video_id:
            yt = YouTube(base_url)
            title = yt.title
            thumbnail_url = yt.thumbnail_url
            # duration = convert_duration(yt.length)
            duration = yt.length
            
            conn.execute('INSERT INTO video_info (url, title, thumbnail_url, duration,url_id) VALUES (?, ?, ?, ?,?)',
                         (base_url, title, thumbnail_url, duration,url_id))
            conn.commit()
            logging.info(f"Added video info: {title}")
    except sqlite3.IntegrityError:
        conn.close()
        logging.warning(f"URL already exists: {base_url}")
        return jsonify({"response" : "URL already exists"}), 400
    except Exception as e:
        conn.close()
        logging.error(f"Error adding URL: {str(e)}")
        return jsonify({"response" : f"Error adding URL: {str(e)}"}), 500
    
    urls = [row['url'] for row in conn.execute('SELECT url FROM urls').fetchall()]
    conn.close()
    logging.info("URL added successfully")
    return jsonify({"response": urls})

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
    video_info = conn.execute("""SELECT id,
                                        url, 
                                        title, 
                                        thumbnail_url,
                                        duration 
                            FROM video_info""").fetchall()
    conn.close()

    results = []
    for info in video_info:
        format_info =  {
                'id' : info['id'],
                'url' : info['url'],
                'title': info['title'],
                'thumbnail_url': info['thumbnail_url'],
                'duration': info['duration'],
            
        }
        results.append(format_info)

    return jsonify({"response" : results})

@app.route('/search', methods=['POST'])
def search():
    data = request.get_json()
    search_term = data.get('search_term')
    if not search_term :
        logging.warning("No search term provided")
        return jsonify({"response":"Please Provide me the search word"})
    
    logging.info(f"Search term received: {search_term}")
    conn = get_db_connection()
    # urls = [row['url'] for row in conn.execute('SELECT url FROM urls').fetchall()]
    video_info = conn.execute("""SELECT id,
                                        url, 
                                        title, 
                                        thumbnail_url,
                                        duration 
                            FROM video_info""").fetchall()
    conn.close()
    
    if not search_term:
        return jsonify({"response": "Provide me the search term"}), 400
    
    results = []
    for info in video_info:
        try:
            time_stamps = process_videos(info['url'], search_term)
            if time_stamps:
                format_info_2 = {
                    'id': info['id'],
                    'url': info['url'],
                    'title': info['title'],
                    'thumbnail_url': info['thumbnail_url'],
                    'duration': info['duration'],
                    'time_stamps': time_stamps
                }
                results.append(format_info_2)
                logging.info(f"Found timestamps for video {info['id']}")
        except Exception as e:
            logging.error(f"Error processing video {info['url']}: {str(e)}")

    if not results:
        logging.info("No results found for the search term")
    else:
        logging.info(f"Search results returned: {len(results)} videos found")

    return jsonify({"response": results})


@app.route('/rm_url/<int:id>', methods=["DELETE"])
def rm_url(id):  
    try:  
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('DELETE FROM urls WHERE id = ?', (id,))
        
        
        conn.commit()
        if cursor.rowcount == 0:
            conn.close()
            logging.warning(f"Video not found in database: {id}")
            return jsonify({"response":"Video is not in the database"}), 404
        
        conn.commit()
        conn.close()
        logging.info(f"Removed video successfully: {id}")
        return jsonify({"response":"Removed video successfully"})
    except Exception as e:
        logging.error(f"Error removing video: {str(e)}")
        return jsonify({"error": e})    
# @app.route('/rm_url/<int:id>', methods=["DELETE"])
# def rm_url(id):  
#     try:  
#         conn = get_db_connection()
#         cursor = conn.cursor()

#         # Delete from the urls table
#         cursor.execute('DELETE FROM urls WHERE id = ?', (id,))
        
#         if cursor.rowcount == 0:
#             conn.close()
#             logging.warning(f"Video not found in database: {id}")
#             return jsonify({"response":"Video is not in the database"}), 404
        
#         conn.commit()
#         conn.close()
#         logging.info(f"Removed video successfully: {id}")
#         return jsonify({"response":"Removed video successfully"})
#     except Exception as e:
#         logging.error(f"Error removing video: {str(e)}")
#         return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000, host='0.0.0.0')