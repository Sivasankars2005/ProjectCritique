# VERSION: 1.0.1 - RESTORED
# Trigger reload for new template
from flask import Flask, request, jsonify, render_template_string, send_from_directory, send_file
from flask_cors import CORS
import sqlite3
import uuid
import datetime
import logging
import os
import random
import string
from werkzeug.utils import secure_filename
import threading

try:
    import torch
    from sentence_transformers import SentenceTransformer, util
    model = SentenceTransformer('BAAI/bge-base-en-v1.5')
    SIMILARITY_ENABLED = True
    import PyPDF2
    import docx
except Exception as e:
    logging.warning(f"Similarity dependencies missing: {e}")
    SIMILARITY_ENABLED = False
    model = None
    util = None

app = Flask(__name__)
CORS(app)
DUPLICATE_THRESHOLD = 92.0
HIGH_SIMILARITY_THRESHOLD = 78.0
MEDIUM_SIMILARITY_THRESHOLD = 65.0
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "ProjectCritique.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'abstracts')
ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx'}
MAX_ABSTRACT_SIZE = 10 * 1024 * 1024  # 10 MB
app.config['MAX_CONTENT_LENGTH'] = MAX_ABSTRACT_SIZE
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@app.route('/api/rooms/select_guide', methods=['POST'])
def select_guide():
    try:
        data = request.get_json()
        room_id = data.get('room_id', '').strip()
        user_email = data.get('user_email', '').strip().lower()
        faculty_email = data.get('faculty_email', '').strip().lower()

        if not all([room_id, user_email, faculty_email]):
            return jsonify({'success': False, 'message': 'Missing required fields.'}), 400

        query = "UPDATE room_members SET selected_faculty_email = ? WHERE room_id = ? AND user_email = ?"
        success = execute_query(query, (faculty_email, room_id, user_email))

        if success:
            return jsonify({'success': True, 'message': 'Faculty guide selected successfully.'})
        return jsonify({'success': False, 'message': 'Failed to select faculty guide.'}), 500
    except Exception as e:
        logging.error(f"Select guide error: {e}")
        return jsonify({'success': False, 'message': 'Internal server error.'}), 500

# --- Approved Projects Endpoint ---
@app.route('/api/approved_projects', methods=['GET'])
def get_approved_projects():
    """Get all approved projects in the user's active room"""
    try:
        email = request.args.get('email', '').strip().lower()
        if not email:
            return jsonify([]), 400
        active_room = get_active_room_db(email)
        if not active_room:
            return jsonify([]), 200
        room_id = active_room['id']
        query = """
        SELECT p.title, p.description, p.submittedByName, p.domain
        FROM projects p
        WHERE p.room_id = ? AND p.status = 'approved'
        ORDER BY p.submittedOn DESC
        """
        projects = fetch_all(query, (room_id,))
        return jsonify(projects), 200
    except Exception as e:
        logging.error(f"Approved projects error: {e}")
        return jsonify([]), 500


@app.route('/api/debug_db', methods=['GET'])
def debug_db():
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        # List tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in cursor.fetchall()]
        # For each table, get columns and a few rows
        data = {}
        for table in tables:
            cursor.execute(f"PRAGMA table_info({table})")
            columns = [col[1] for col in cursor.fetchall()]
            cursor.execute(f"SELECT * FROM {table} LIMIT 5")
            rows = cursor.fetchall()
            data[table] = {'columns': columns, 'rows': rows}
        conn.close()
        return jsonify({'tables': tables, 'data': data})
    except Exception as e:
        return jsonify({'error': str(e)})


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL,
            is_admin INTEGER DEFAULT 0
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            domain TEXT,
            description TEXT,
            assignedFacultyEmail TEXT NOT NULL,
            assignedFacultyName TEXT NOT NULL,
            submittedBy TEXT NOT NULL,
            submittedByName TEXT NOT NULL,
            submittedOn TEXT,
            status TEXT,
            similarity_percentage REAL DEFAULT 0,
            similarity_flag TEXT DEFAULT 'UNIQUE',
            faculty_comment TEXT,
            updated_at TEXT,
            room_id TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS project_similarity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id_1 TEXT NOT NULL,
            project_id_2 TEXT NOT NULL,
            similarity REAL NOT NULL,
            UNIQUE(project_id_1, project_id_2)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS abstracts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT NOT NULL,
            stored_filename TEXT NOT NULL,
            original_filename TEXT NOT NULL,
            size INTEGER NOT NULL,
            uploaded_by TEXT NOT NULL,
            uploaded_on TEXT NOT NULL,
            UNIQUE(project_id)
        )
    ''')
    # New tables for room management
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS rooms (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            code TEXT UNIQUE NOT NULL,
            description TEXT,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (created_by) REFERENCES users(id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS room_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            user_email TEXT NOT NULL,
            role TEXT NOT NULL,
            joined_at TEXT NOT NULL,
            is_active INTEGER DEFAULT 0,
            selected_faculty_email TEXT,
            UNIQUE(room_id, user_id),
            FOREIGN KEY (room_id) REFERENCES rooms(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id TEXT NOT NULL,
            sender_email TEXT NOT NULL,
            sender_name TEXT NOT NULL,
            sender_role TEXT NOT NULL,
            recipient_email TEXT NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            is_read INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY (room_id) REFERENCES rooms(id)
        )
    ''')

    # Create indexes for better query performance
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_room_members_user ON room_members(user_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_room_members_room ON room_members(room_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_rooms_code ON rooms(code)')
    
    # Check if selected_faculty_email column exists and add it if not (Migration)
    cursor.execute("PRAGMA table_info(room_members)")
    columns = [col[1] for col in cursor.fetchall()]
    if 'selected_faculty_email' not in columns:
        cursor.execute("ALTER TABLE room_members ADD COLUMN selected_faculty_email TEXT")
    
    conn.commit()
    cursor.close()
    conn.close()

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def fetch_one(query, params=None):
    conn = get_db_connection()
    if conn:
        cursor = conn.cursor()
        try:
            cursor.execute(query, params or [])
            result = cursor.fetchone()
            return dict(result) if result else None
        except sqlite3.Error as err:
            logging.error(f"Error fetching one row: {err}")
            return None
        finally:
            cursor.close()
            conn.close()
    return None

def fetch_all(query, params=None):
    conn = get_db_connection()
    if conn:
        cursor = conn.cursor()
        try:
            cursor.execute(query, params or [])
            results = cursor.fetchall()
            return [dict(row) for row in results]
        except sqlite3.Error as err:
            logging.error(f"Error fetching all rows: {err}")
            return []
        finally:
            cursor.close()
            conn.close()
    return []

def execute_query(query, params=None):
    conn = get_db_connection()
    if conn:
        cursor = conn.cursor()
        try:
            cursor.execute(query, params or [])
            conn.commit()
            return True
        except sqlite3.Error as err:
            logging.error(f"Error executing query: {err}")
            conn.rollback()
            return False
        finally:
            cursor.close()
            conn.close()
    return False

def get_user_by_email_db(email):
    query = "SELECT id, name, email, password, role, is_admin FROM users WHERE email = ?"
    return fetch_one(query, (email.strip().lower(),))

def get_project_by_id_db(project_id):
    query = "SELECT * FROM projects WHERE id = ?"
    return fetch_one(query, (project_id,))


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def extract_text_from_pdf(filepath):
    text = ""
    try:
        with open(filepath, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                text += page.extract_text() + " "
    except Exception as e:
        logging.error(f"Error extracting text from PDF {filepath}: {e}")
    return text.strip()

def extract_text_from_docx(filepath):
    text = ""
    try:
        doc = docx.Document(filepath)
        for para in doc.paragraphs:
            text += para.text + " "
    except Exception as e:
        logging.error(f"Error extracting text from DOCX {filepath}: {e}")
    return text.strip()

def migrate_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        # Migrate abstracts table
        cursor.execute("PRAGMA table_info(abstracts)")
        columns = [col[1] for col in cursor.fetchall()]
        if 'extracted_text' not in columns:
            print("📦 Migrating database: Adding extracted_text column to abstracts table...")
            cursor.execute("ALTER TABLE abstracts ADD COLUMN extracted_text TEXT")
            conn.commit()
        
        # Migrate users table
        cursor.execute("PRAGMA table_info(users)")
        columns = [col[1] for col in cursor.fetchall()]
        if 'is_admin' not in columns:
            print("📦 Migrating database: Adding is_admin column to users table...")
            cursor.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0")
            conn.commit()
        
        # Migrate projects table
        cursor.execute("PRAGMA table_info(projects)")
        columns = [col[1] for col in cursor.fetchall()]
        if 'room_id' not in columns:
            print("📦 Migrating database: Adding room_id column to projects table...")
            cursor.execute("ALTER TABLE projects ADD COLUMN room_id TEXT")
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_projects_room ON projects(room_id)')
            conn.commit()

        # Migrate notifications table
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='notifications'")
        if not cursor.fetchone():
            print("📦 Migrating database: Creating notifications table...")
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    room_id TEXT NOT NULL,
                    sender_email TEXT NOT NULL,
                    sender_name TEXT NOT NULL,
                    sender_role TEXT NOT NULL,
                    recipient_email TEXT NOT NULL,
                    title TEXT NOT NULL,
                    message TEXT NOT NULL,
                    is_read INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (room_id) REFERENCES rooms(id)
                )
            ''')
            conn.commit()
            
    except Exception as e:
        logging.error(f"Migration error: {e}")
    finally:
        cursor.close()
        conn.close()


# ===================================
# ROOM MANAGEMENT HELPER FUNCTIONS
# ===================================

def generate_room_code():
    """Generate a unique 6-character room code"""
    while True:
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        # Check if code already exists
        existing = fetch_one("SELECT id FROM rooms WHERE code = ?", (code,))
        if not existing:
            return code

def get_room_by_code_db(code):
    """Get room by code (case-insensitive)"""
    query = "SELECT * FROM rooms WHERE UPPER(code) = UPPER(?)"
    return fetch_one(query, (code,))

def get_room_by_id_db(room_id):
    """Get room by ID"""
    query = "SELECT * FROM rooms WHERE id = ?"
    return fetch_one(query, (room_id,))

def get_user_rooms_db(user_email):
    """Get all rooms a user is a member of"""
    query = """
    SELECT r.*, rm.is_active, rm.joined_at
    FROM rooms r
    JOIN room_members rm ON r.id = rm.room_id
    WHERE rm.user_email = ?
    ORDER BY rm.is_active DESC, r.name ASC
    """
    return fetch_all(query, (user_email.lower(),))

def get_active_room_db(user_email):
    """Get user's currently active room"""
    query = """
    SELECT r.*
    FROM rooms r
    JOIN room_members rm ON r.id = rm.room_id
    WHERE rm.user_email = ? AND rm.is_active = 1
    """
    return fetch_one(query, (user_email.lower(),))

def get_room_members_db(room_id):
    """Get all members of a room"""
    query = """
    SELECT u.id, u.name, u.email, rm.role, rm.joined_at, rm.selected_faculty_email
    FROM users u
    JOIN room_members rm ON u.id = rm.user_id
    WHERE rm.room_id = ?
    ORDER BY rm.joined_at ASC
    """
    return fetch_all(query, (room_id,))

def is_user_in_room_db(room_id, user_email):
    """Check if user is a member of a room"""
    query = "SELECT id FROM room_members WHERE room_id = ? AND user_email = ?"
    result = fetch_one(query, (room_id, user_email.lower()))
    return result is not None



def get_abstract_by_project_id_db(project_id):
    query = "SELECT * FROM abstracts WHERE project_id = ?"
    return fetch_one(query, (project_id,))


def insert_abstract_db(project_id, stored_filename, original_filename, size, uploaded_by, extracted_text=""):
    query = "INSERT OR REPLACE INTO abstracts (project_id, stored_filename, original_filename, size, uploaded_by, uploaded_on, extracted_text) VALUES (?, ?, ?, ?, ?, ?, ?)"
    return execute_query(query, (project_id, stored_filename, original_filename, size, uploaded_by, datetime.datetime.now().isoformat(), extracted_text))

def get_all_faculty_db():
    query = "SELECT id, name, email, role FROM users WHERE role = 'faculty'"
    return fetch_all(query)

def get_room_faculty_db(room_id):
    """Get all faculty members assigned to a specific room"""
    query = """
    SELECT u.id, u.name, u.email, rm.role
    FROM users u
    JOIN room_members rm ON u.id = rm.user_id
    WHERE rm.room_id = ? AND rm.role = 'faculty'
    ORDER BY u.name ASC
    """
    return fetch_all(query, (room_id,))

def calculate_basic_similarity(new_description, existing_descriptions):
    if not existing_descriptions:
        return 0.0
    new_words = set(new_description.lower().split())
    max_similarity = 0.0
    for existing_desc in existing_descriptions:
        existing_words = set(existing_desc.lower().split())
        if len(new_words) == 0 or len(existing_words) == 0:
            continue
        intersection = new_words.intersection(existing_words)
        union = new_words.union(existing_words)
        similarity = (len(intersection) / len(union)) * 100 if len(union) > 0 else 0
        max_similarity = max(max_similarity, similarity)
    return max_similarity

def calculate_semantic_similarity(new_project, existing_projects):
    # Prepare new project text
    new_text = f"{new_project['title']} {new_project.get('description', '')}".strip()
    
    # Prepare existing projects text
    existing_texts = []
    valid_existing_projects = []
    
    for proj in existing_projects:
        # Combine title, description, and extracted text (if available)
        combined_text = f"{proj['title']} {proj.get('description', '')}".strip()
        if combined_text:
            existing_texts.append(combined_text)
            valid_existing_projects.append(proj)
    if not existing_texts:
        return 0.0, None
    if not SIMILARITY_ENABLED:
        return calculate_basic_similarity(new_text, existing_texts), None
    try:
        new_embedding = model.encode(new_text, convert_to_tensor=True)
        existing_embeddings = model.encode(existing_texts, convert_to_tensor=True)
        cosine_scores = util.pytorch_cos_sim(new_embedding, existing_embeddings)[0]
        max_score, max_idx = torch.max(cosine_scores, dim=0)
        max_score = max_score.item() * 100
        most_similar_proj = None
        if max_score > 0 and max_idx.item() < len(valid_existing_projects):
            most_similar_proj = valid_existing_projects[max_idx.item()]
        return max_score, most_similar_proj
    except Exception as e:
        logging.error(f"Error in semantic similarity calculation: {e}")
        return calculate_basic_similarity(new_text, existing_texts), None

def recalculate_project_score(project_id):
    try:
        project = get_project_by_id_db(project_id)
        if not project: return
        abstract = get_abstract_by_project_id_db(project_id)
        project['extracted_text'] = abstract['extracted_text'] if abstract and abstract.get('extracted_text') else ""
        query = "SELECT p.title, p.description FROM projects p WHERE p.submittedBy != ? AND p.room_id = ?"
        others = fetch_all(query, (project['submittedBy'], project['room_id']))
        sim, _ = calculate_semantic_similarity(project, others)
        if sim >= DUPLICATE_THRESHOLD: flag = 'DUPLICATE'
        elif sim >= HIGH_SIMILARITY_THRESHOLD: flag = 'HIGH_SIMILARITY'
        elif sim >= MEDIUM_SIMILARITY_THRESHOLD: flag = 'MEDIUM_SIMILARITY'
        else: flag = 'UNIQUE'
        execute_query("UPDATE projects SET similarity_percentage = ?, similarity_flag = ? WHERE id = ?", (sim, flag, project_id))
        logging.info(f"Recalculated score for {project_id}: {sim}% ({flag})")
    except Exception as e:
        logging.error(f"Recalculation error: {e}")

TEMPLATE_PATH = os.path.join(BASE_DIR, 'templates', 'index.html')
HTML_TEMPLATE = open(TEMPLATE_PATH, 'r', encoding='utf-8').read() if os.path.exists(TEMPLATE_PATH) else """
<!DOCTYPE html>
<html><head><title>ProjectCritique - Service Starting</title></head>
<body>
<h1>ProjectCritique Backend is Running</h1>
<p>Please ensure the frontend HTML file is properly loaded.</p>
<p>Database Status: Connected</p>
<p>AI Similarity: {}</p>
</body></html>
""".format("Enabled" if SIMILARITY_ENABLED else "Disabled - Using Basic Similarity")


@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/register', methods=['POST'])
def register():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No data received'}), 400
        name = data.get('name', '').strip()
        email = data.get('email', '').strip().lower()
        password = data.get('password', '')
        role = data.get('role', '')
        
        if not all([name, email, password, role]):
            return jsonify({'success': False, 'message': 'All fields are required.'}), 400
        if get_user_by_email_db(email):
            return jsonify({'success': False, 'message': 'Email already registered.'}), 409
        
        # Handle admin registration
        is_admin = 1 if role == 'admin' else 0
        if role not in ['student', 'faculty', 'admin']:
            return jsonify({'success': False, 'message': 'Invalid role specified.'}), 400
            
        user_id = str(uuid.uuid4())
        query = "INSERT INTO users (id, name, email, password, role, is_admin) VALUES (?, ?, ?, ?, ?, ?)"
        if execute_query(query, (user_id, name, email, password, role, is_admin)):
            return jsonify({'success': True, 'message': 'Registration successful!'}), 201
        else:
            return jsonify({'success': False, 'message': 'Registration failed - database error.'}), 500
    except Exception as e:
        logging.error(f"Registration error: {e}")
        return jsonify({'success': False, 'message': 'Registration failed - server error.'}), 500

@app.route('/api/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No data received'}), 400
        email = data.get('email', '').strip().lower()
        password = data.get('password', '')
        role = data.get('role', '')
        user = get_user_by_email_db(email)
        if not user or user['password'] != password or user['role'] != role:
            return jsonify({'success': False, 'message': 'Invalid credentials or role mismatch.'}), 401
        return jsonify({
            'success': True,
            'message': 'Login successful!',
            'user_id': user['id'],
            'name': user['name'],
            'email': user['email'],
            'role': user['role']
        })
    except Exception as e:
        logging.error(f"Login error: {e}")
        return jsonify({'success': False, 'message': 'Login failed - server error.'}), 500

@app.route('/api/forgot_password', methods=['POST'])
def forgot_password():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No data received'}), 400
        email = data.get('email', '').strip().lower()
        if not email:
            return jsonify({'success': False, 'message': 'Email is required.'}), 400
        
        user = get_user_by_email_db(email)
        if not user:
            return jsonify({'success': False, 'message': 'If an account exists for that email, a reset link will be sent.'}), 200
            
        # Here you would normally generate a token and send an actual email.
        # For this demo, we'll just simulate a success response.
        return jsonify({'success': True, 'message': 'A password reset link has been sent to your email.'}), 200
    except Exception as e:
        logging.error(f"Forgot password error: {e}")
        return jsonify({'success': False, 'message': 'An error occurred. Please try again later.'}), 500

# ===================================
# ROOM MANAGEMENT ENDPOINTS
# ===================================

@app.route('/api/rooms', methods=['POST'])
def create_room():
    """Admin creates a new room"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No data received'}), 400
        
        admin_email = data.get('admin_email', '').strip().lower()
        name = data.get('name', '').strip()
        description = data.get('description', '').strip()
        
        if not all([admin_email, name]):
            return jsonify({'success': False, 'message': 'Admin email and room name are required.'}), 400
        
        # Verify user is admin
        admin_user = get_user_by_email_db(admin_email)
        if not admin_user or admin_user.get('is_admin') != 1:
            return jsonify({'success': False, 'message': 'Only admins can create rooms.'}), 403
        
        # Generate unique room code
        room_code = generate_room_code()
        room_id = str(uuid.uuid4())
        created_at = datetime.datetime.now().isoformat()
        
        query = "INSERT INTO rooms (id, name, code, description, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?)"
        if execute_query(query, (room_id, name, room_code, description, admin_user['id'], created_at)):
            return jsonify({
                'success': True,
                'message': 'Room created successfully!',
                'room': {
                    'id': room_id,
                    'name': name,
                    'code': room_code,
                    'description': description,
                    'created_at': created_at
                }
            }), 201
        else:
            return jsonify({'success': False, 'message': 'Failed to create room.'}), 500
            
    except Exception as e:
        logging.error(f"Create room error: {e}")
        return jsonify({'success': False, 'message': 'Room creation failed - server error.'}), 500

@app.route('/api/rooms/join', methods=['POST'])
def join_room():
    """Student or faculty joins a room using a code"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No data received'}), 400
        
        room_code = data.get('room_code', '').strip()
        user_email = data.get('user_email', '').strip().lower()
        
        if not all([room_code, user_email]):
            return jsonify({'success': False, 'message': 'Room code and user email are required.'}), 400
        
        # Check if room exists
        room = get_room_by_code_db(room_code)
        if not room:
            return jsonify({'success': False, 'message': 'Room not found. Please check the code and try again.'}), 404
        
        # Get user details
        user = get_user_by_email_db(user_email)
        if not user:
            return jsonify({'success': False, 'message': 'User not found.'}), 404
        
        # Check if user is already in room
        if is_user_in_room_db(room['id'], user_email):
            return jsonify({'success': False, 'message': "You're already a member of this room."}), 409
        
        # Check if user has any rooms (to set active flag)
        user_rooms = get_user_rooms_db(user_email)
        is_active = 1 if len(user_rooms) == 0 else 0  # First room is automatically active
        
        # Add user to room
        joined_at = datetime.datetime.now().isoformat()
        query = "INSERT INTO room_members (room_id, user_id, user_email, role, joined_at, is_active) VALUES (?, ?, ?, ?, ?, ?)"
        
        if execute_query(query, (room['id'], user['id'], user_email, user['role'], joined_at, is_active)):
            return jsonify({
                'success': True,
                'message': 'Successfully joined the room!',
                'room': {
                    'id': room['id'],
                    'name': room['name'],
                    'code': room['code'],
                    'is_active': is_active
                }
            }), 200
        else:
            return jsonify({'success': False, 'message': 'Failed to join room.'}), 500
            
    except Exception as e:
        logging.error(f"Join room error: {e}")
        return jsonify({'success': False, 'message': 'Join room failed - server error.'}), 500

@app.route('/api/rooms/leave', methods=['POST'])
def leave_room():
    """User leaves a room"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No data received'}), 400
        
        room_id = data.get('room_id', '').strip()
        user_email = data.get('user_email', '').strip().lower()
        
        if not all([room_id, user_email]):
            return jsonify({'success': False, 'message': 'Room ID and user email are required.'}), 400
        
        # Check if user is in room
        if not is_user_in_room_db(room_id, user_email):
            return jsonify({'success': False, 'message': 'You are not a member of this room.'}), 404
        
        # Check if this was the active room
        active_room = get_active_room_db(user_email)
        was_active = active_room and active_room['id'] == room_id
        
        # Remove user from room
        query = "DELETE FROM room_members WHERE room_id = ? AND user_email = ?"
        if execute_query(query, (room_id, user_email)):
            # If was active room, set another room as active
            if was_active:
                user_rooms = get_user_rooms_db(user_email)
                if len(user_rooms) > 0:
                    # Set first room as active
                    update_query = "UPDATE room_members SET is_active = 1 WHERE room_id = ? AND user_email = ?"
                    execute_query(update_query, (user_rooms[0]['id'], user_email))
            
            return jsonify({
                'success': True,
                'message': 'Successfully left the room.',
                'needs_new_active': was_active and len(user_rooms) > 0 if was_active else False
            }), 200
        else:
            return jsonify({'success': False, 'message': 'Failed to leave room.'}), 500
            
    except Exception as e:
        logging.error(f"Leave room error: {e}")
        return jsonify({'success': False, 'message': 'Leave room failed - server error.'}), 500

@app.route('/api/rooms/user', methods=['GET'])
def get_user_rooms():
    """Get all rooms a user is a member of"""
    try:
        user_email = request.args.get('email', '').strip().lower()
        if not user_email:
            return jsonify({'success': False, 'message': 'User email is required.'}), 400
        
        rooms = get_user_rooms_db(user_email)
        return jsonify(rooms), 200
        
    except Exception as e:
        logging.error(f"Get user rooms error: {e}")
        return jsonify([]), 500

@app.route('/api/rooms/set-active', methods=['POST'])
def set_active_room():
    """Set a room as the user's active room"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No data received'}), 400
        
        room_id = data.get('room_id', '').strip()
        user_email = data.get('user_email', '').strip().lower()
        
        if not all([room_id, user_email]):
            return jsonify({'success': False, 'message': 'Room ID and user email are required.'}), 400
        
        # Check if user is in room
        if not is_user_in_room_db(room_id, user_email):
            return jsonify({'success': False, 'message': 'You are not a member of this room.'}), 404
        
        # Set all rooms to inactive
        query1 = "UPDATE room_members SET is_active = 0 WHERE user_email = ?"
        execute_query(query1, (user_email,))
        
        # Set this room to active
        query2 = "UPDATE room_members SET is_active = 1 WHERE room_id = ? AND user_email = ?"
        if execute_query(query2, (room_id, user_email)):
            return jsonify({'success': True, 'message': 'Active room updated.'}), 200
        else:
            return jsonify({'success': False, 'message': 'Failed to set active room.'}), 500
            
    except Exception as e:
        logging.error(f"Set active room error: {e}")
        return jsonify({'success': False, 'message': 'Set active room failed - server error.'}), 500

@app.route('/api/rooms/<room_id>', methods=['GET'])
def get_room_details(room_id):
    """Get detailed information about a room including members"""
    try:
        room = get_room_by_id_db(room_id)
        if not room:
            return jsonify({'success': False, 'message': 'Room not found.'}), 404
        
        # Get room members
        members = get_room_members_db(room_id)
        
        # Count students and faculty
        student_count = sum(1 for m in members if m['role'] == 'student')
        faculty_count = sum(1 for m in members if m['role'] == 'faculty')
        
        return jsonify({
            'success': True,
            'room': {
                'id': room['id'],
                'name': room['name'],
                'code': room['code'],
                'description': room['description'],
                'created_at': room['created_at'],
                'student_count': student_count,
                'faculty_count': faculty_count,
                'members': members
            }
        }), 200
        
    except Exception as e:
        logging.error(f"Get room details error: {e}")
        return jsonify({'success': False, 'message': 'Failed to get room details.'}), 500

@app.route('/api/admin/rooms', methods=['GET'])
def get_admin_rooms():
    """Get all rooms created by an admin"""
    try:
        admin_email = request.args.get('email', '').strip().lower()
        if not admin_email:
            return jsonify({'success': False, 'message': 'Admin email is required.'}), 400
        
        # Verify user is admin
        admin_user = get_user_by_email_db(admin_email)
        if not admin_user or admin_user.get('is_admin') != 1:
            return jsonify({'success': False, 'message': 'Unauthorized.'}), 403
        
        # Get all rooms created by this admin
        query = "SELECT * FROM rooms WHERE created_by = ? ORDER BY created_at DESC"
        rooms = fetch_all(query, (admin_user['id'],))
        
        # Add member counts to each room
        for room in rooms:
            members = get_room_members_db(room['id'])
            room['student_count'] = sum(1 for m in members if m['role'] == 'student')
            room['faculty_count'] = sum(1 for m in members if m['role'] == 'faculty')
            room['total_members'] = len(members)
        
        return jsonify(rooms), 200
        
    except Exception as e:
        logging.error(f"Get admin rooms error: {e}")
        return jsonify([]), 500

@app.route('/api/projects', methods=['POST'])
def submit_project():
    def update_project_similarity(new_project_id, new_title, new_description, faculty_email):
        other_projects_query = "SELECT id, title, description FROM projects WHERE assignedFacultyEmail = ? AND id != ?"
        other_projects = fetch_all(other_projects_query, (faculty_email, new_project_id))
        for proj in other_projects:
            sim, _ = calculate_semantic_similarity({'title': new_title, 'description': new_description}, [proj])
            execute_query("REPLACE INTO project_similarity (project_id_1, project_id_2, similarity) VALUES (?, ?, ?)", (new_project_id, proj['id'], sim))
            execute_query("REPLACE INTO project_similarity (project_id_1, project_id_2, similarity) VALUES (?, ?, ?)", (proj['id'], new_project_id, sim))

    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'No data received'}), 400

    title = data.get('title', '').strip()
    domain = data.get('domain', '')
    description = data.get('description', '').strip()
    assigned_faculty_email = data.get('assignedFacultyEmail', '').strip().lower()
    submitted_by_email = data.get('submittedByEmail', '').strip().lower()
    submitted_by_name = data.get('submittedByName', '').strip()
    room_id = data.get('room_id', '').strip()  # Get room_id from request

    if not all([title, domain, description, assigned_faculty_email, submitted_by_email, submitted_by_name]):
        return jsonify({'success': False, 'message': 'Missing required project fields.'}), 400
    
    # Room is optional for backward compatibility, but recommended
    if room_id and not get_room_by_id_db(room_id):
        return jsonify({'success': False, 'message': 'Invalid room ID.'}), 400

    faculty = get_user_by_email_db(assigned_faculty_email)
    if not faculty or faculty['role'] != 'faculty':
        return jsonify({'success': False, 'message': 'Assigned faculty not found or invalid.'}), 400

    submitting_student = get_user_by_email_db(submitted_by_email)
    if not submitting_student or submitting_student['role'] != 'student':
        return jsonify({'success': False, 'message': 'Submitting user not found or is not a student.'}), 400

    # Save project immediately with default similarity (computed in background)
    project_id = str(uuid.uuid4())
    submitted_on = datetime.datetime.now().isoformat()
    insert_query = """
    INSERT INTO projects (id, title, domain, description, assignedFacultyEmail, assignedFacultyName,
                         submittedBy, submittedByName, submittedOn, status, similarity_percentage, similarity_flag, room_id)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    success = execute_query(insert_query, (
        project_id, title, domain, description, assigned_faculty_email,
        faculty['name'], submitted_by_email, submitted_by_name,
        submitted_on, 'pending', 0.0, 'UNIQUE', room_id
    ))

    if success:
        # Run ALL similarity computation in background thread (non-blocking)
        def compute_similarity_async(pid, ptitle, pdesc, faculty_email, student_email, rid):
            try:
                existing_projects_query = "SELECT p.title, p.description FROM projects p WHERE p.submittedBy != ? AND p.room_id = ? AND p.id != ?"
                existing_projects = fetch_all(existing_projects_query, (student_email, rid, pid))
                new_project = {'title': ptitle, 'description': pdesc}
                sim_pct, _ = calculate_semantic_similarity(new_project, existing_projects)

                # Determine similarity flag
                if sim_pct >= DUPLICATE_THRESHOLD:
                    sim_flag = 'DUPLICATE'
                elif sim_pct >= HIGH_SIMILARITY_THRESHOLD:
                    sim_flag = 'HIGH_SIMILARITY'
                elif sim_pct >= MEDIUM_SIMILARITY_THRESHOLD:
                    sim_flag = 'MEDIUM_SIMILARITY'
                else:
                    sim_flag = 'UNIQUE'

                # Update the project with computed similarity
                execute_query("UPDATE projects SET similarity_percentage = ?, similarity_flag = ? WHERE id = ?", (sim_pct, sim_flag, pid))

                # Also update pairwise similarity table
                update_project_similarity(pid, ptitle, pdesc, faculty_email)
            except Exception as e:
                logging.error(f"Background similarity computation error: {e}")

        threading.Thread(target=compute_similarity_async, args=(project_id, title, description, assigned_faculty_email, submitted_by_email, room_id), daemon=True).start()

        response = {
            'success': True,
            'message': 'Project submitted successfully!',
            'project': {
                'id': project_id,
                'title': title,
                'similarity_percentage': 0.0,
                'similarity_flag': 'UNIQUE'
            }
        }
        return jsonify(response), 201
    else:
        return jsonify({'success': False, 'message': 'Project submission failed - database error.'}), 500

@app.route('/api/projects/student', methods=['GET'])
def get_student_projects():
    try:
        student_email = request.args.get('email')
        if not student_email:
            return jsonify({'success': False, 'message': 'Student email is required.'}), 400
        clean_email = student_email.strip().lower()
        logging.info(f"[DEBUG] Student project query for email: '{clean_email}'")
        room_id = request.args.get('room_id', '').strip()
        
        query = '''SELECT id, title, domain, description, assignedFacultyEmail, assignedFacultyName, 
                          submittedBy, submittedByName, submittedOn, updated_at, status, similarity_percentage, 
                          similarity_flag, faculty_comment 
                   FROM projects 
                   WHERE LOWER(submittedBy) = LOWER(?)'''
        params = [clean_email]

        if room_id:
            query += " AND room_id = ?"
            params.append(room_id)
        
        query += " ORDER BY submittedOn DESC"
        student_projects = fetch_all(query, params)
        logging.info(f"[DEBUG] Found {len(student_projects)} projects for student: '{clean_email}'")
        if not student_projects:
            logging.warning(f"No projects found for student: {clean_email}")
        return jsonify(student_projects)
    except Exception as e:
        logging.error(f"Error fetching student projects: {e}")
        return jsonify([])

@app.route('/api/projects/faculty', methods=['GET'])
def get_faculty_projects():
    try:
        faculty_email = request.args.get('email')
        if not faculty_email:
            return jsonify({'success': False, 'message': 'Faculty email is required.'}), 400
        clean_email = faculty_email.strip().lower()
        status = request.args.get('status', '').strip().lower()
        domain = request.args.get('domain', '').strip().lower()
        similarity = request.args.get('similarity', '').strip().lower()
        search = request.args.get('search', '').strip().lower()
        room_id = request.args.get('room_id', '').strip()

        query = "SELECT * FROM projects WHERE LOWER(assignedFacultyEmail) = LOWER(?)"
        params = [clean_email]

        if room_id:
            query += " AND room_id = ?"
            params.append(room_id)

        if status:
            query += " AND LOWER(status) = ?"
            params.append(status)
        if domain:
            query += " AND LOWER(domain) = ?"
            params.append(domain)
        if similarity == 'duplicate':
            query += f" AND similarity_percentage >= {DUPLICATE_THRESHOLD}"
        elif similarity == 'high':
            query += f" AND similarity_percentage >= {HIGH_SIMILARITY_THRESHOLD} AND similarity_percentage < {DUPLICATE_THRESHOLD}"
        if search:
            query += " AND (LOWER(title) LIKE ? OR LOWER(submittedByName) LIKE ? OR LOWER(domain) LIKE ?)"
            search_term = f"%{search}%"
            params.extend([search_term, search_term, search_term])

        query += " ORDER BY submittedOn DESC"
        faculty_projects = fetch_all(query, params)
        logging.info(f"[DEBUG] Found {len(faculty_projects)} projects for faculty: '{clean_email}' with filters.")
        return jsonify(faculty_projects)
    except Exception as e:
        logging.error(f"Error fetching faculty projects: {e}")
        return jsonify([])

@app.route('/api/projects/<project_id>/status', methods=['PUT'])
def update_project_status(project_id):
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No data received'}), 400
        new_status = data.get('status')
        faculty_comment = data.get('faculty_comment')
        project = get_project_by_id_db(project_id)
        if not project:
            logging.error(f"Project not found for status update: {project_id}")
            return jsonify({'success': False, 'message': 'Project not found.'}), 404
        if new_status not in ['approved', 'rejected', 'pending']:
            logging.error(f"Invalid status attempted: {new_status}")
            return jsonify({'success': False, 'message': 'Invalid status.'}), 400
        if new_status == 'rejected' and not faculty_comment:
            faculty_comment = "Rejected by faculty"
        update_query = """
        UPDATE projects SET status = ?, faculty_comment = ?, updated_at = ?
        WHERE id = ?
        """
        try:
            result = execute_query(update_query, (new_status, faculty_comment, datetime.datetime.now().isoformat(), project_id))
            if result:
                return jsonify({'success': True, 'message': 'Project status updated.'}), 200
            else:
                logging.error(f"Failed to update project status for {project_id} (query returned False)")
                return jsonify({'success': False, 'message': 'Failed to update project status.'}), 500
        except Exception as e:
            logging.error(f"Exception during project status update: {e}")
            return jsonify({'success': False, 'message': f'Exception: {e}'}), 500
    except Exception as e:
        logging.error(f"Status update error: {e}")
        return jsonify({'success': False, 'message': 'Status update failed - server error.'}), 500

@app.route('/api/projects/<project_id>', methods=['PUT'])
def resubmit_project(project_id):
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No data received'}), 400
        title = data.get('title', '').strip()
        description = data.get('description', '').strip()
        project = get_project_by_id_db(project_id)
        if not project:
            return jsonify({'success': False, 'message': 'Project not found.'}), 404
        existing_projects_query = "SELECT p.title, p.description FROM projects p WHERE p.id != ? AND p.submittedBy != ? AND p.room_id = ?"
        existing_projects = fetch_all(existing_projects_query, (project_id, project['submittedBy'], project['room_id']))
        new_project = {'title': title, 'description': description}
        similarity_percentage, _ = calculate_semantic_similarity(new_project, existing_projects)
        if similarity_percentage >= DUPLICATE_THRESHOLD:
            similarity_flag = 'DUPLICATE'
        elif similarity_percentage >= HIGH_SIMILARITY_THRESHOLD:
            similarity_flag = 'HIGH_SIMILARITY'
        elif similarity_percentage >= MEDIUM_SIMILARITY_THRESHOLD:
            similarity_flag = 'MEDIUM_SIMILARITY'
        else:
            similarity_flag = 'UNIQUE'
        update_query = """
        UPDATE projects SET title = ?, description = ?, status = 'pending',
        faculty_comment = NULL, similarity_percentage = ?, similarity_flag = ?, updated_at = ?, submittedOn = ?
        WHERE id = ?
        """
        now_iso = datetime.datetime.now().isoformat()
        if execute_query(update_query, (
            title, description, similarity_percentage, similarity_flag,
            now_iso, now_iso, project_id
        )):
            return jsonify({
                'success': True, 
                'message': 'Project updated and resubmitted successfully.',
                'similarity_percentage': round(similarity_percentage, 2),
                'similarity_flag': similarity_flag
            }), 200
        else:
            return jsonify({'success': False, 'message': 'Failed to resubmit project.'}), 500
    except Exception as e:
        logging.error(f"Resubmit error: {e}")
        return jsonify({'success': False, 'message': 'Resubmit failed - server error.'}), 500

@app.route('/api/projects/<project_id>', methods=['DELETE'])
def delete_project(project_id):
    try:
        project = get_project_by_id_db(project_id)
        if not project:
            return jsonify({'success': False, 'message': 'Project not found.'}), 404
        
        # Prevent deletion if project is approved
        if project.get('status') == 'approved':
            return jsonify({'success': False, 'message': 'Cannot delete an approved project.'}), 403
            
        query = "DELETE FROM projects WHERE id = ?"
        if execute_query(query, (project_id,)):
            return jsonify({'success': True, 'message': 'Project deleted successfully.'}), 200
        else:
            return jsonify({'success': False, 'message': 'Failed to delete project.'}), 500
    except Exception as e:
        logging.error(f"Delete error: {e}")
        return jsonify({'success': False, 'message': 'Delete failed - server error.'}), 500

@app.route('/api/faculty_list', methods=['GET'])
def get_faculty_list():
    try:
        room_id = request.args.get('room_id', '').strip()
        if room_id:
            faculty_users = get_room_faculty_db(room_id)
        else:
            faculty_users = get_all_faculty_db()
        return jsonify(faculty_users)
    except Exception as e:
        logging.error(f"Faculty list error: {e}")
        return jsonify([])


# --- Similarity Analysis Endpoint ---
@app.route('/api/similarity_analysis', methods=['GET'])
def similarity_analysis():
    try:
        faculty_email = request.args.get('email')
        if not faculty_email:
            return jsonify({'success': False, 'message': 'Faculty email is required.'}), 400
        room_id = request.args.get('room_id', '').strip()
        # Get all projects for this faculty, optionally filtered by room
        # Query the project_similarity table for actual pairwise comparisons
        # Join with projects table twice to get details for both projects in the pair
        similarity_query = """
        SELECT 
            ps.similarity,
            p1.title as p1_title, p1.submittedByName as p1_student, p1.status as p1_status,
            p2.title as p2_title, p2.submittedByName as p2_student, p2.status as p2_status
        FROM project_similarity ps
        JOIN projects p1 ON ps.project_id_1 = p1.id
        JOIN projects p2 ON ps.project_id_2 = p2.id
        WHERE p1.assignedFacultyEmail = ? 
          AND ps.similarity >= ?
          AND ps.project_id_1 < ps.project_id_2
        """
        query_params = [faculty_email.strip().lower(), HIGH_SIMILARITY_THRESHOLD]

        if room_id:
            similarity_query += " AND p1.room_id = ? AND p2.room_id = ?"
            query_params.extend([room_id, room_id])
            
        similarity_query += " ORDER BY ps.similarity DESC"
        
        results = fetch_all(similarity_query, query_params)

        duplicate_pairs = []
        high_similarity_pairs = []

        for row in results:
            sim = row['similarity']
            pair_data = {
                'project1': {'title': row['p1_title'], 'student': row['p1_student'], 'status': row['p1_status']},
                'project2': {'title': row['p2_title'], 'student': row['p2_student'], 'status': row['p2_status']},
                'similarity_score': sim
            }
            
            if sim >= DUPLICATE_THRESHOLD:
                duplicate_pairs.append(pair_data)
            elif sim >= HIGH_SIMILARITY_THRESHOLD:
                high_similarity_pairs.append(pair_data)

        return jsonify({
            'total_duplicates': len(duplicate_pairs),
            'total_high_similarity': len(high_similarity_pairs),
            'analysis_timestamp': datetime.datetime.now().isoformat(),
            'duplicate_pairs': duplicate_pairs,
            'high_similarity_pairs': high_similarity_pairs
        })
    except Exception as e:
        logging.error(f"Similarity analysis error: {e}")
        return jsonify({'success': False, 'message': 'Similarity analysis failed.'}), 500

# --- Faculty Stats Endpoint ---
@app.route('/api/faculty_stats', methods=['GET'])
def faculty_stats():
    try:
        faculty_email = request.args.get('email')
        if not faculty_email:
            return jsonify({'success': False, 'message': 'Faculty email is required.'}), 400
        room_id = request.args.get('room_id', '').strip()
        query = "SELECT status, similarity_percentage FROM projects WHERE assignedFacultyEmail = ?"
        params = [faculty_email.strip().lower()]
        
        if room_id:
            query += " AND room_id = ?"
            params.append(room_id)
            
        projects = fetch_all(query, params)
        total = len(projects)
        pending = sum(1 for p in projects if p['status'] == 'pending')
        approved = sum(1 for p in projects if p['status'] == 'approved')
        rejected = sum(1 for p in projects if p['status'] == 'rejected')
        duplicates = sum(1 for p in projects if p.get('similarity_percentage', 0) >= DUPLICATE_THRESHOLD)
        avg_similarity = round(sum(p.get('similarity_percentage', 0) for p in projects) / total, 2) if total else 0
        return jsonify({
            'total': total,
            'pending': pending,
            'approved': approved,
            'rejected': rejected,
            'duplicates': duplicates,
            'avg_similarity': avg_similarity
        })
    except Exception as e:
        logging.error(f"Faculty stats error: {e}")
        return jsonify({'success': False, 'message': 'Faculty stats failed.'}), 500


# --- Abstract Upload / View / Download Endpoints ---
@app.route('/api/projects/<project_id>/abstract', methods=['POST'])
def upload_project_abstract(project_id):
    try:
        # Expect multipart/form-data with file and uploader_email
        if 'file' not in request.files:
            return jsonify({'success': False, 'message': 'No file part in the request.'}), 400
        file = request.files['file']
        uploader_email = request.form.get('uploader_email', '').strip().lower()

        if not uploader_email:
            return jsonify({'success': False, 'message': 'Uploader email is required.'}), 400

        project = get_project_by_id_db(project_id)
        if not project:
            return jsonify({'success': False, 'message': 'Project not found.'}), 404

        # Only allow upload if project is approved
        if (project.get('status') or '').lower() != 'approved':
            return jsonify({'success': False, 'message': 'Abstract can only be uploaded after project approval.'}), 403

        # Only the submitting student may upload
        if (project.get('submittedBy') or '').strip().lower() != uploader_email:
            return jsonify({'success': False, 'message': 'Only the submitting student can upload the abstract.'}), 403

        if file.filename == '':
            return jsonify({'success': False, 'message': 'No selected file.'}), 400
        if not allowed_file(file.filename):
            return jsonify({'success': False, 'message': 'Invalid file type. Only PDF or Word documents are allowed.'}), 400

        original_filename = secure_filename(file.filename)
        # Read file bytes to check size
        data = file.read()
        size = len(data)
        if size > MAX_ABSTRACT_SIZE:
            return jsonify({'success': False, 'message': 'File too large. Max 10MB allowed.'}), 413

        timestamp = int(datetime.datetime.now().timestamp())
        stored_filename = f"{project_id}_{timestamp}_{original_filename}"
        stored_path = os.path.join(UPLOAD_FOLDER, stored_filename)
        with open(stored_path, 'wb') as f:
            f.write(data)

        # Extract text for advanced similarity
        extracted_text = ""
        try:
            lower_name = original_filename.lower()
            if lower_name.endswith('.pdf'):
                extracted_text = extract_text_from_pdf(stored_path)
            elif lower_name.endswith('.docx') or lower_name.endswith('.doc'):
                extracted_text = extract_text_from_docx(stored_path)
        except Exception as e:
            logging.error(f"Text extraction failed: {e}")

        if insert_abstract_db(project_id, stored_filename, original_filename, size, uploader_email, extracted_text):
            # Trigger recalculation
            recalculate_project_score(project_id)
            return jsonify({'success': True, 'message': 'Abstract uploaded successfully.'}), 201
        else:
            # remove file if db insert failed
            try:
                os.remove(stored_path)
            except Exception:
                pass
            return jsonify({'success': False, 'message': 'Failed to save abstract metadata.'}), 500

    except Exception as e:
        logging.error(f"Abstract upload error: {e}")
        return jsonify({'success': False, 'message': 'Abstract upload failed - server error.'}), 500


@app.route('/api/project_details', methods=['GET'])
def get_project_details():
    try:
        project_id = request.args.get('id')
        if not project_id:
            return jsonify({'success': False, 'message': 'Project ID required'}), 400
        
        project = get_project_by_id_db(project_id)
        if not project:
            return jsonify({'success': False, 'message': 'Project not found'}), 404
            
        return jsonify(project)
    except Exception as e:
        logging.error(f"Project details error: {e}")
        return jsonify({'success': False, 'message': 'Error fetching details'}), 500

@app.route('/api/projects/<project_id>/abstract', methods=['GET'])
def get_project_abstract(project_id):
    try:
        project = get_project_by_id_db(project_id)
        if not project:
            return jsonify({'success': False, 'message': 'Project not found.'}), 404
        abstract = get_abstract_by_project_id_db(project_id)
        if not abstract:
            return jsonify({'success': False, 'message': 'No abstract submitted.'}), 404
        # Provide metadata and URLs
        stored_filename = abstract['stored_filename']
        view_url = f"/static/abstracts/{stored_filename}"
        download_url = f"/api/abstracts/{stored_filename}/download"
        return jsonify({
            'project_id': project_id,
            'original_filename': abstract['original_filename'],
            'stored_filename': stored_filename,
            'size': abstract['size'],
            'uploaded_by': abstract['uploaded_by'],
            'uploaded_on': abstract['uploaded_on'],
            'view_url': view_url,
            'download_url': download_url
        })
    except Exception as e:
        logging.error(f"Get abstract error: {e}")
        return jsonify({'success': False, 'message': 'Failed to fetch abstract.'}), 500


@app.route('/api/abstracts/<path:filename>/download', methods=['GET'])
def download_abstract(filename):
    try:
        # Security: ensure the file exists in UPLOAD_FOLDER
        safe_name = secure_filename(filename)
        full_path = os.path.join(UPLOAD_FOLDER, safe_name)
        if not os.path.exists(full_path):
            return jsonify({'success': False, 'message': 'File not found.'}), 404
        return send_from_directory(UPLOAD_FOLDER, safe_name, as_attachment=True)
    except Exception as e:
        logging.error(f"Download abstract error: {e}")
        return jsonify({'success': False, 'message': 'Failed to download abstract.'}), 500

# --- Report Data Endpoints ---
@app.route('/api/report/admin', methods=['GET'])
def report_admin():
    """Return all projects, abstracts, and members for a room (admin report)."""
    try:
        room_id = request.args.get('room_id', '').strip()
        if not room_id:
            return jsonify({'success': False, 'message': 'room_id is required.'}), 400

        members = get_room_members_db(room_id)
        room = get_room_by_id_db(room_id)
        if not room:
            return jsonify({'success': False, 'message': 'Room not found.'}), 404

        projects = fetch_all("SELECT * FROM projects WHERE room_id = ?", (room_id,))

        project_ids = [p['id'] for p in projects]
        abstracts = []
        if project_ids:
            placeholders = ','.join(['?'] * len(project_ids))
            abstracts = fetch_all(
                f"SELECT project_id, original_filename FROM abstracts WHERE project_id IN ({placeholders})",
                project_ids
            )

        return jsonify({
            'success': True,
            'room_name': room['name'],
            'members': members,
            'projects': projects,
            'abstracts': abstracts
        })
    except Exception as e:
        logging.error(f"Admin report error: {e}")
        return jsonify({'success': False, 'message': 'Failed to generate report data.'}), 500


@app.route('/api/report/faculty', methods=['GET'])
def report_faculty():
    """Return projects assigned to a specific faculty, abstracts, and members for a room."""
    try:
        room_id = request.args.get('room_id', '').strip()
        faculty_email = request.args.get('faculty_email', '').strip().lower()
        if not room_id or not faculty_email:
            return jsonify({'success': False, 'message': 'room_id and faculty_email are required.'}), 400

        members = get_room_members_db(room_id)
        room = get_room_by_id_db(room_id)
        if not room:
            return jsonify({'success': False, 'message': 'Room not found.'}), 404

        projects = fetch_all(
            "SELECT * FROM projects WHERE room_id = ? AND LOWER(assignedFacultyEmail) = LOWER(?)",
            (room_id, faculty_email)
        )

        project_ids = [p['id'] for p in projects]
        abstracts = []
        if project_ids:
            placeholders = ','.join(['?'] * len(project_ids))
            abstracts = fetch_all(
                f"SELECT project_id, original_filename FROM abstracts WHERE project_id IN ({placeholders})",
                project_ids
            )

        return jsonify({
            'success': True,
            'room_name': room['name'],
            'members': members,
            'projects': projects,
            'abstracts': abstracts
        })
    except Exception as e:
        logging.error(f"Faculty report error: {e}")
        return jsonify({'success': False, 'message': 'Failed to generate report data.'}), 500

# ===================================
# NOTIFICATIONS ENDPOINTS
# ===================================

@app.route('/api/notifications', methods=['GET'])
def get_notifications():
    try:
        email = request.args.get('email', '').strip().lower()
        room_id = request.args.get('room_id', '').strip()
        
        if not email or not room_id:
            return jsonify({'success': False, 'message': 'Email and room_id required'}), 400
            
        query = """
            SELECT * FROM notifications 
            WHERE recipient_email = ? AND room_id = ? 
            ORDER BY created_at DESC 
            LIMIT 50
        """
        notifications = fetch_all(query, (email, room_id))
        return jsonify({'success': True, 'notifications': notifications}), 200
    except Exception as e:
        logging.error(f"Get notifications error: {e}")
        return jsonify({'success': False, 'message': 'Internal Server Error', 'notifications': []}), 500

@app.route('/api/notifications/unread_count', methods=['GET'])
def get_unread_notifications_count():
    try:
        email = request.args.get('email', '').strip().lower()
        room_id = request.args.get('room_id', '').strip()
        
        if not email or not room_id:
            return jsonify({'count': 0}), 400
            
        query = "SELECT COUNT(*) as count FROM notifications WHERE recipient_email = ? AND room_id = ? AND is_read = 0"
        result = fetch_one(query, (email, room_id))
        return jsonify({'count': result['count'] if result else 0}), 200
    except Exception as e:
        logging.error(f"Get unread notifications count error: {e}")
        return jsonify({'count': 0}), 500

@app.route('/api/notifications/read', methods=['PUT'])
def mark_notifications_read():
    try:
        data = request.get_json()
        email = data.get('email', '').strip().lower()
        room_id = data.get('room_id', '').strip()
        
        if not email or not room_id:
            return jsonify({'success': False, 'message': 'Email and room_id required'}), 400
            
        query = "UPDATE notifications SET is_read = 1 WHERE recipient_email = ? AND room_id = ? AND is_read = 0"
        execute_query(query, (email, room_id))
        return jsonify({'success': True}), 200
    except Exception as e:
        logging.error(f"Mark notifications read error: {e}")
        return jsonify({'success': False}), 500

@app.route('/api/notifications/admin', methods=['POST'])
def send_admin_notification():
    try:
        data = request.get_json()
        room_id = data.get('room_id', '').strip()
        admin_email = data.get('sender_email', '').strip().lower()
        title = data.get('title', '').strip()
        message = data.get('message', '').strip()
        
        if not all([room_id, admin_email, title, message]):
            return jsonify({'success': False, 'message': 'All fields are required.'}), 400
            
        admin_user = get_user_by_email_db(admin_email)
        if not admin_user or admin_user.get('is_admin') != 1:
            return jsonify({'success': False, 'message': 'Unauthorized. Only admins can broadcast.'}), 403
            
        # Get all members in the room
        members = get_room_members_db(room_id)
        if not members:
            return jsonify({'success': False, 'message': 'No members in this room.'}), 404
            
        created_at = datetime.datetime.now().isoformat()
        count = 0
        for member in members:
            query = """
                INSERT INTO notifications (room_id, sender_email, sender_name, sender_role, recipient_email, title, message, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """
            success = execute_query(query, (room_id, admin_email, admin_user['name'], 'admin', member['email'], title, message, created_at))
            if success:
                count += 1
                
        return jsonify({'success': True, 'message': f'Sent notification to {count} members.'}), 200
    except Exception as e:
        logging.error(f"Send admin notification error: {e}")
        return jsonify({'success': False, 'message': 'Failed to send notification.'}), 500

@app.route('/api/notifications/faculty', methods=['POST'])
def send_faculty_notification():
    try:
        data = request.get_json()
        room_id = data.get('room_id', '').strip()
        faculty_email = data.get('faculty_email', '').strip().lower()
        title = data.get('title', '').strip()
        message = data.get('message', '').strip()
        
        if not all([room_id, faculty_email, title, message]):
            return jsonify({'success': False, 'message': 'All fields are required.'}), 400
            
        faculty = get_user_by_email_db(faculty_email)
        if not faculty or faculty['role'] != 'faculty':
            return jsonify({'success': False, 'message': 'Unauthorized.'}), 403
            
        # Get all assigned students in this room
        query = "SELECT user_email as email FROM room_members WHERE room_id = ? AND selected_faculty_email = ? AND role = 'student'"
        assigned_students = fetch_all(query, (room_id, faculty_email))
        
        if not assigned_students:
            return jsonify({'success': False, 'message': 'No students assigned to you in this room.'}), 404
            
        created_at = datetime.datetime.now().isoformat()
        count = 0
        for student in assigned_students:
            query = """
                INSERT INTO notifications (room_id, sender_email, sender_name, sender_role, recipient_email, title, message, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """
            success = execute_query(query, (room_id, faculty_email, faculty['name'], 'faculty', student['email'], title, message, created_at))
            if success:
                count += 1
                
        return jsonify({'success': True, 'message': f'Sent notification to {count} assigned students.'}), 200
    except Exception as e:
        logging.error(f"Send faculty notification error: {e}")
        return jsonify({'success': False, 'message': 'Failed to send notification.'}), 500


if __name__ == '__main__':
    print("🚀 Starting ProjectCritique Server...")
    print(f"📊 Database: {DB_PATH}")
    print(f"🤖 AI Similarity: {'Enabled' if SIMILARITY_ENABLED else 'Disabled (using basic similarity)'}")
    print(f"📈 Similarity Thresholds: Duplicate≥{DUPLICATE_THRESHOLD}%, High≥{HIGH_SIMILARITY_THRESHOLD}%")
    print("✅ Server ready!")
    init_db()
    migrate_db()
    app.run(debug=True, use_reloader=False, port=5000, host='0.0.0.0')
