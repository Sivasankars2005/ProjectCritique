"""
seed_data.py — Reset DB and populate with realistic test data
Run: python seed_data.py
"""

import sqlite3
import uuid
import datetime
import os
from werkzeug.security import generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "ProjectCritique.db")

def seed():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # ─── 1. CLEAR ALL TABLES ───────────────────────────────────────────
    tables = [
        "project_similarity", "project_embeddings", "abstracts",
        "notifications", "room_members", "projects", "rooms", "users"
    ]
    for t in tables:
        c.execute(f"DELETE FROM {t}")
    conn.commit()
    print("✅ All tables cleared.")

    # ─── 2. USERS ──────────────────────────────────────────────────────
    now = datetime.datetime.now().isoformat()

    admin_id = str(uuid.uuid4())
    faculty_id = str(uuid.uuid4())
    student_ids = [str(uuid.uuid4()) for _ in range(5)]

    users = [
        # Admin
        (admin_id, "Admin User", "admin@gmail.com",
         "admin123", "admin", 1),
        # Faculty
        (faculty_id, "Dr. Ramesh Kumar", "ramesh@faculty.edu",
         "faculty123", "faculty", 0),
        # Students
        (student_ids[0], "Aarav Sharma", "aarav@student.edu",
         "student123", "student", 0),
        (student_ids[1], "Priya Nair", "priya@student.edu",
         "student123", "student", 0),
        (student_ids[2], "Karthik Menon", "karthik@student.edu",
         "student123", "student", 0),
        (student_ids[3], "Divya Raj", "divya@student.edu",
         "student123", "student", 0),
        (student_ids[4], "Vikram Iyer", "vikram@student.edu",
         "student123", "student", 0),
    ]

    c.executemany(
        "INSERT INTO users (id, name, email, password, role, is_admin) VALUES (?,?,?,?,?,?)",
        users
    )
    print("✅ 7 users created (1 admin, 1 faculty, 5 students).")

    # ─── 3. ROOM ───────────────────────────────────────────────────────
    room_id = str(uuid.uuid4())
    room_code = "CSE2026"
    c.execute(
        "INSERT INTO rooms (id, name, code, description, created_by, created_at) VALUES (?,?,?,?,?,?)",
        (room_id, "CSE Project Lab 2026", room_code,
         "Final year CSE project submissions — Batch 2026", admin_id, now)
    )
    print(f"✅ Room created: 'CSE Project Lab 2026' (code: {room_code})")

    # ─── 4. ROOM MEMBERS ──────────────────────────────────────────────
    # Faculty member
    c.execute(
        "INSERT INTO room_members (room_id, user_id, user_email, role, joined_at, is_active) VALUES (?,?,?,?,?,?)",
        (room_id, faculty_id, "ramesh@faculty.edu", "faculty", now, 1)
    )
    # Student members (all select the same faculty as guide)
    student_emails = [
        "aarav@student.edu", "priya@student.edu", "karthik@student.edu",
        "divya@student.edu", "vikram@student.edu"
    ]
    for sid, email in zip(student_ids, student_emails):
        c.execute(
            "INSERT INTO room_members (room_id, user_id, user_email, role, joined_at, is_active, selected_faculty_email) VALUES (?,?,?,?,?,?,?)",
            (room_id, sid, email, "student", now, 1, "ramesh@faculty.edu")
        )
    print("✅ All users added to room. Faculty assigned as guide.")

    # ─── 5. PROJECT SUBMISSIONS ────────────────────────────────────────
    projects = [
        # HIGH SIMILARITY pair (Aarav & Priya — AI chatbot variants)
        {
            "id": str(uuid.uuid4()),
            "title": "AI Chatbot for Student Academic Assistance",
            "domain": "ai_ml",
            "description": (
                "This project develops an AI-powered chatbot using Natural Language Processing "
                "and machine learning techniques to assist students with academic queries. "
                "The chatbot will leverage transformer-based models to understand student questions "
                "about course material, assignments, and exam preparation, providing instant "
                "intelligent responses. It includes features like FAQ resolution, study plan "
                "generation, and personalized learning recommendations."
            ),
            "student_idx": 0,
        },
        {
            "id": str(uuid.uuid4()),
            "title": "Intelligent Chatbot for Education and Learning Support",
            "domain": "ai_ml",
            "description": (
                "An intelligent conversational agent built using NLP and deep learning to support "
                "student learning in educational institutions. The system uses transformer models "
                "to process natural language queries from students regarding academics, coursework, "
                "and exam tips, delivering accurate and helpful automated responses. Key features "
                "include automated doubt resolution, study material suggestions, and adaptive "
                "learning path generation."
            ),
            "student_idx": 1,
        },
        # MEDIUM SIMILARITY pair (Karthik & Divya — web-based learning platforms)
        {
            "id": str(uuid.uuid4()),
            "title": "Web-Based Collaborative Learning Platform with Video Conferencing",
            "domain": "web_development",
            "description": (
                "A full-stack web application that enables collaborative online learning through "
                "real-time video conferencing, shared whiteboards, and discussion forums. "
                "Built using modern web technologies, it allows teachers to conduct live classes, "
                "share resources, and engage students through interactive quizzes and polls. "
                "The platform includes attendance tracking, session recording, and analytics "
                "dashboards for monitoring student engagement."
            ),
            "student_idx": 2,
        },
        {
            "id": str(uuid.uuid4()),
            "title": "Online Course Management System with Student Analytics",
            "domain": "web_development",
            "description": (
                "A comprehensive web-based course management system that helps educational "
                "institutions organize and deliver online courses. The platform includes "
                "modules for course creation, student enrollment, assignment submission, "
                "and grade management. It features a built-in analytics dashboard that tracks "
                "student performance trends, completion rates, and engagement metrics to help "
                "faculty identify at-risk students early."
            ),
            "student_idx": 3,
        },
        # LOW SIMILARITY (Vikram — completely different domain)
        {
            "id": str(uuid.uuid4()),
            "title": "IoT-Based Smart Irrigation System Using Soil Moisture Sensors",
            "domain": "iot",
            "description": (
                "This project designs and implements an IoT-based smart irrigation system "
                "that uses soil moisture sensors, temperature sensors, and humidity monitors "
                "connected via Arduino and ESP32 microcontrollers. The system automatically "
                "controls water pumps based on real-time soil conditions, reducing water wastage "
                "by up to 40%. A companion mobile app allows farmers to monitor field conditions "
                "remotely and receive alerts when manual intervention is needed. The data is stored "
                "in a cloud database for historical analysis and crop planning."
            ),
            "student_idx": 4,
        },
    ]

    for p in projects:
        idx = p["student_idx"]
        c.execute(
            """INSERT INTO projects 
               (id, title, domain, description, assignedFacultyEmail, assignedFacultyName,
                submittedBy, submittedByName, submittedOn, status, similarity_percentage,
                similarity_flag, room_id) 
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                p["id"], p["title"], p["domain"], p["description"],
                "ramesh@faculty.edu", "Dr. Ramesh Kumar",
                student_emails[idx], users[idx + 2][1],  # +2 to skip admin & faculty
                now, "pending", 0.0, "UNIQUE", room_id
            )
        )

    print("✅ 5 projects submitted (2 HIGH sim, 2 MEDIUM sim, 1 LOW sim).")

    conn.commit()
    conn.close()

    # ─── 6. PRINT SUMMARY ─────────────────────────────────────────────
    print("\n" + "=" * 65)
    print("  📋  SEEDED DATA SUMMARY")
    print("=" * 65)

    print("\n👤 USER CREDENTIALS:")
    print("-" * 65)
    print(f"  {'Role':<10} {'Name':<22} {'Email':<28} {'Password'}")
    print("-" * 65)
    print(f"  {'Admin':<10} {'Admin User':<22} {'admin@gmail.com':<28} admin123")
    print(f"  {'Faculty':<10} {'Dr. Ramesh Kumar':<22} {'ramesh@faculty.edu':<28} faculty123")
    for i, (sid, email) in enumerate(zip(student_ids, student_emails)):
        name = users[i + 2][1]
        print(f"  {'Student':<10} {name:<22} {email:<28} student123")

    print(f"\n🏠 ROOM:")
    print(f"  Name: CSE Project Lab 2026")
    print(f"  Code: {room_code}")
    print(f"  Members: 1 Faculty + 5 Students")

    print(f"\n👨‍🏫 FACULTY GUIDE: Dr. Ramesh Kumar (ramesh@faculty.edu)")

    print(f"\n📄 PROJECT SUBMISSIONS:")
    print("-" * 65)
    for p in projects:
        idx = p["student_idx"]
        name = users[idx + 2][1]
        sim_label = ["🔴 HIGH", "🔴 HIGH", "🟡 MEDIUM", "🟡 MEDIUM", "🟢 LOW"][idx]
        print(f"  [{sim_label}] {name}")
        print(f"          → {p['title']}")
        print(f"          Domain: {p['domain']}")
        print()

    print("=" * 65)
    print("✅ Database seeded successfully! Run `python app.py` to start.")
    print("=" * 65)


if __name__ == "__main__":
    seed()
