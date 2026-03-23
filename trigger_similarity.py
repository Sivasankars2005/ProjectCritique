"""
trigger_similarity.py — Trigger similarity recalculation for all seeded projects
Run this AFTER seed_data.py and while app.py is NOT running (it loads the AI model itself).
Usage: python trigger_similarity.py
"""

import sqlite3
import os
import sys
import datetime
import numpy as np

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "ProjectCritique.db")

# Thresholds (must match app.py)
DUPLICATE_THRESHOLD = 75.0
HIGH_SIMILARITY_THRESHOLD = 50.0
MEDIUM_SIMILARITY_THRESHOLD = 35.0
SIMILARITY_BASELINE = 44.0

print("🤖 Loading AI model (sentence-transformers/all-MiniLM-L6-v2)...")
try:
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
    print("✅ Model loaded successfully.")
except Exception as e:
    print(f"❌ Failed to load model: {e}")
    sys.exit(1)


def chunk_text(text, chunk_size=300):
    words = text.split()
    if not words:
        return [""]
    return [" ".join(words[i:i + chunk_size]) for i in range(0, len(words), chunk_size)]


def compute_embedding(text):
    chunks = chunk_text(text)
    embeddings = model.encode(chunks, convert_to_numpy=True, show_progress_bar=False)
    return embeddings.mean(axis=0)


def calibrate_score(raw_score):
    if raw_score <= SIMILARITY_BASELINE:
        return 0.0
    calibrated = ((raw_score - SIMILARITY_BASELINE) / (100.0 - SIMILARITY_BASELINE)) * 100.0
    return min(round(calibrated, 2), 100.0)


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Get all projects
    c.execute("SELECT id, title, description, submittedBy, room_id FROM projects")
    projects = [dict(row) for row in c.fetchall()]

    if not projects:
        print("⚠️  No projects found in database. Run seed_data.py first.")
        return

    print(f"\n📊 Computing similarity for {len(projects)} projects...\n")

    # Step 1: Compute and cache embeddings for all projects
    embeddings = {}
    for p in projects:
        text = f"{p['title']} {p['description']}".strip()
        emb = compute_embedding(text)
        embeddings[p['id']] = emb

        # Cache in DB
        emb_bytes = emb.astype(np.float32).tobytes()
        c.execute(
            "INSERT OR REPLACE INTO project_embeddings (project_id, embedding, updated_at) VALUES (?, ?, ?)",
            (p['id'], emb_bytes, datetime.datetime.now().isoformat())
        )

    print("✅ All embeddings computed and cached.\n")

    # Step 2: For each project, compute max similarity against all OTHER projects in same room
    print(f"{'Student':<20} {'Similarity':<12} {'Flag':<18} {'Title'}")
    print("-" * 90)

    for p in projects:
        others = [o for o in projects if o['id'] != p['id'] and o['room_id'] == p['room_id']]

        max_raw = 0.0
        most_similar_title = ""

        for other in others:
            emb_a = embeddings[p['id']]
            emb_b = embeddings[other['id']]

            dot = float(np.dot(emb_a, emb_b))
            norm = float(np.linalg.norm(emb_a) * np.linalg.norm(emb_b))
            raw = (dot / norm * 100.0) if norm > 0 else 0.0

            if raw > max_raw:
                max_raw = raw
                most_similar_title = other['title']

        calibrated = calibrate_score(max_raw)

        # Determine flag
        if calibrated >= DUPLICATE_THRESHOLD:
            flag = "DUPLICATE"
        elif calibrated >= HIGH_SIMILARITY_THRESHOLD:
            flag = "HIGH_SIMILARITY"
        elif calibrated >= MEDIUM_SIMILARITY_THRESHOLD:
            flag = "MEDIUM_SIMILARITY"
        else:
            flag = "UNIQUE"

        # Update DB
        c.execute(
            "UPDATE projects SET similarity_percentage = ?, similarity_flag = ? WHERE id = ?",
            (calibrated, flag, p['id'])
        )

        # Also store pairwise similarity
        for other in others:
            emb_a = embeddings[p['id']]
            emb_b = embeddings[other['id']]
            dot = float(np.dot(emb_a, emb_b))
            norm = float(np.linalg.norm(emb_a) * np.linalg.norm(emb_b))
            raw = (dot / norm * 100.0) if norm > 0 else 0.0
            cal = calibrate_score(raw)
            try:
                c.execute(
                    "INSERT OR REPLACE INTO project_similarity (project_id_1, project_id_2, similarity) VALUES (?, ?, ?)",
                    (p['id'], other['id'], cal)
                )
            except Exception:
                pass

        # Emoji for flag
        flag_emoji = {"DUPLICATE": "🔴", "HIGH_SIMILARITY": "🟠", "MEDIUM_SIMILARITY": "🟡", "UNIQUE": "🟢"}.get(flag, "⚪")

        print(f"  {p['submittedBy']:<25} {calibrated:>5.1f}%    {flag_emoji} {flag:<18} {p['title'][:50]}")
        if most_similar_title:
            print(f"  {'':>25} Most similar to: {most_similar_title[:50]}")
        print()

    conn.commit()
    conn.close()

    print("=" * 90)
    print("✅ Similarity scores computed and saved! Restart `python app.py` to see the results.")
    print("=" * 90)


if __name__ == "__main__":
    main()
