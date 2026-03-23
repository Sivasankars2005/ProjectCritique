import numpy as np
from sentence_transformers import SentenceTransformer

model = SentenceTransformer('all-MiniLM-L6-v2')

SIMILARITY_BASELINE = 14.0

def calibrate_score(raw_score):
    if raw_score <= SIMILARITY_BASELINE:
        return 0.0
    calibrated = ((raw_score - SIMILARITY_BASELINE) / (100.0 - SIMILARITY_BASELINE)) * 100.0
    return min(round(calibrated, 2), 100.0)

# --- Reference Project ---
reference = {
    "title": "AI Chatbot for Student Academic Assistance",
    "description": """This project develops an AI-powered chatbot using Natural Language Processing and machine 
learning techniques to assist students with academic queries. The chatbot will leverage transformer-based models 
to understand student questions about course material, assignments, and exam preparation, providing instant 
intelligent responses. It includes features like FAQ resolution, study plan generation, and personalized 
learning recommendations."""
}

# --- Test Projects ---
test_projects = [
    {
        "expected": "~1%",
        "title": "Smart Irrigation System using IoT",
        "description": """This project designs an automated irrigation system for agricultural fields using IoT 
sensors deployed across the farm. Soil moisture sensors, temperature probes, and humidity detectors continuously 
monitor environmental conditions and transmit data to a central microcontroller. The system uses threshold-based 
logic to trigger water pumps automatically when soil moisture drops below optimal levels. A mobile app allows 
farmers to monitor field conditions remotely and manually override the system."""
    },
    {
        "expected": "~10%",
        "title": "Hospital Appointment Booking System",
        "description": """This project builds a web-based hospital management platform that allows patients to 
register, search for doctors by specialization, and book appointments online. The system manages doctor 
availability calendars, sends automated SMS and email reminders for upcoming appointments, and maintains digital 
patient records. Admin staff can manage ward allocations, track patient history, and generate billing reports. 
The backend is built using Flask and SQLite, with a responsive HTML frontend."""
    },
    {
        "expected": "~20%",
        "title": "AI-based Traffic Signal Control System",
        "description": """This project implements an intelligent traffic management system using computer vision 
and deep learning to monitor vehicle density at intersections in real time. A camera feed is processed using 
YOLO object detection to count vehicles in each lane. The system dynamically adjusts signal timing based on 
congestion levels, reducing average wait times during peak hours. A dashboard displays live traffic analytics 
for city traffic controllers."""
    },
    {
        "expected": "~30%",
        "title": "NLP-based Sentiment Analysis Tool for Product Reviews",
        "description": """This project develops a sentiment analysis pipeline that processes large volumes of 
customer product reviews from e-commerce platforms. Using transformer-based models like BERT, the system 
classifies reviews as positive, negative, or neutral and extracts key opinion phrases. A business dashboard 
visualizes sentiment trends over time by product category. The tool helps businesses identify common customer 
complaints and improve product quality."""
    },
    {
        "expected": "~50%",
        "title": "AI-powered Resume Screening System",
        "description": """This project builds an automated recruitment tool that uses NLP and transformer-based 
models to match candidate resumes against job descriptions. The system extracts skills, qualifications, and 
experience from uploaded resume PDFs and ranks candidates based on semantic similarity scores. Recruiters can 
set filters for required skills and experience levels, and the system generates a shortlist with match 
percentage explanations. It uses all-MiniLM-L6-v2 for semantic embeddings and Flask for the backend API."""
    },
    {
        "expected": "~70%",
        "title": "Intelligent Tutoring System using NLP",
        "description": """This project develops an intelligent tutoring platform that uses transformer-based NLP 
models to interact with students in a subject-specific conversational interface. Students can ask questions 
about course topics, and the system retrieves relevant answers from a curated knowledge base using semantic 
search. The tutor generates personalized quizzes based on weak areas identified from past interactions and 
tracks student progress over sessions. It supports multiple subjects and adapts difficulty based on student 
performance."""
    },
    {
        "expected": "~90%",
        "title": "AI Chatbot for Student Academic Support using Deep Learning",
        "description": """This project creates an AI-powered conversational chatbot designed to assist university 
students with academic queries using Natural Language Processing and deep learning. The chatbot is built on 
transformer-based language models that understand and respond to student questions related to course content, 
assignment deadlines, and exam preparation strategies. Key features include automated FAQ resolution, 
personalized study plan generation, and intelligent learning recommendations based on student performance 
history."""
    },
]

# --- Compute embeddings ---
def get_embedding(title, description):
    text = f"{title} {description}".strip()
    return model.encode([text], convert_to_numpy=True)[0]

print("Computing embeddings...")
ref_emb = get_embedding(reference["title"], reference["description"])

print("\n" + "="*65)
print(f"{'Expected':<10} {'Raw':>8} {'Calibrated':>12}  Title")
print("="*65)

for proj in test_projects:
    emb = get_embedding(proj["title"], proj["description"])
    
    dot = float(np.dot(ref_emb, emb))
    norm = float(np.linalg.norm(ref_emb) * np.linalg.norm(emb))
    raw = (dot / norm * 100.0) if norm > 0 else 0.0
    calibrated = calibrate_score(raw)
    
    # Verdict
    if calibrated >= 80:
        verdict = "🔴 DUPLICATE"
    elif calibrated >= 50:
        verdict = "🟠 HIGH"
    elif calibrated >= 25:
        verdict = "🟡 MEDIUM"
    else:
        verdict = "🟢 UNIQUE"
    
    print(f"{proj['expected']:<10} {raw:>7.1f}% {calibrated:>10.1f}%  {verdict}  {proj['title'][:35]}")

print("="*65)
print("\nDone! Compare 'Calibrated' column against 'Expected' column.")
print("If they're far apart, your SIMILARITY_BASELINE needs adjusting.")