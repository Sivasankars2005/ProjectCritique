import numpy as np
from sentence_transformers import SentenceTransformer
from itertools import combinations
import random

model = SentenceTransformer('all-MiniLM-L6-v2')

# Put your actual project descriptions here
projects = [
    "A library management system with book tracking and user accounts",
    "Weather forecasting app using machine learning and historical data",
    "E-commerce platform with payment gateway and inventory management",
    "Chat application with real-time messaging using WebSockets",
    "Student attendance tracking system with QR code scanning",
    "Hospital management system for patient records and appointments",
    "Food delivery app with restaurant listings and order tracking",
    "Online quiz platform with timer and score tracking",
]

# Encode all projects
embeddings = model.encode(projects)

# Compute cosine similarity for ALL pairs
from sklearn.metrics.pairwise import cosine_similarity
sim_matrix = cosine_similarity(embeddings)

scores = []
pairs = []

for i, j in combinations(range(len(projects)), 2):
    score = sim_matrix[i][j] * 100  # convert to percentage
    scores.append(score)
    pairs.append((i, j, score))

# Sort to see lowest and highest
pairs.sort(key=lambda x: x[2])

print("=== LOWEST similarity pairs (these are your 'unrelated' baseline) ===")
for i, j, score in pairs[:5]:
    print(f"  {score:.1f}% | '{projects[i][:40]}' vs '{projects[j][:40]}'")

print("\n=== HIGHEST similarity pairs (potential duplicates) ===")
for i, j, score in reversed(pairs[-5:]):
    print(f"  {score:.1f}% | '{projects[i][:40]}' vs '{projects[j][:40]}'")

print("\n=== STATISTICS ===")
print(f"  Min score:    {np.min(scores):.1f}%")
print(f"  Max score:    {np.max(scores):.1f}%")
print(f"  Mean score:   {np.mean(scores):.1f}%")
print(f"  Median score: {np.median(scores):.1f}%")
print(f"\n  ✅ Suggested baseline cutoff: {np.mean(scores):.1f}% (use this instead of 44%)")