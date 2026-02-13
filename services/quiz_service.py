import fitz
import re
import json
from groq import Groq
from config import GROQ_API_KEY, GROQ_MODEL
from database.mongo import quizzes_collection
from datetime import datetime
from bson import ObjectId

groq_client = Groq(api_key=GROQ_API_KEY)

# --- HELPER UTILITIES ---

def clean_string(text):
    """
    Removes prefixes like 'A)', '1.', or 'Answer:' and extra whitespace.
    """
    if not text:
        return ""
    # Regex removes: 'A) ', 'A. ', '1) ', '1. ', 'Answer: ', 'Option 1: '
    cleaned = re.sub(r"^\s*([A-Za-z0-9]+[\)\.]|Answer:|Option \d+:)\s*", "", str(text), flags=re.IGNORECASE)
    return cleaned.strip()

def text_chunk_limit(text, max_tokens=2000):
    """Limit the text chunk to prevent token overflow while keeping context."""
    return text[:max_tokens * 4]

# --- CORE FUNCTIONS ---

def generate_quiz_from_pdf(pdf_file, created_by, course_id, title, num_questions, course_outcomes_json):
    try:
        all_cos = json.loads(course_outcomes_json) if course_outcomes_json else []
        
        pdf_stream = pdf_file.read()
        doc = fitz.open(stream=pdf_stream, filetype="pdf")
        extracted_text = "".join(page.get_text() for page in doc)
        doc.close()
        
        if not extracted_text.strip():
            raise ValueError("The uploaded PDF seems to be empty or contains only images.")
            
    except Exception as e:
        raise Exception(f"Preprocessing Error: {e}")

    # IMPROVED PROMPT: Forces AI to provide the TEXT of the answer, not the index.
    prompt = f"""
Generate exactly {num_questions} multiple choice questions from this text:
{text_chunk_limit(extracted_text)}

COURSE: {course_id}
OUTCOMES TO COVER:
{chr(10).join(all_cos)}

STRICT RULES:
1. Provide the output ONLY as a valid JSON array.
2. Each object must have: "question", "options" (array of 4), "answer", and "co_tag".
3. The "answer" field must contain the EXACT TEXT from the "options" array, NOT a number or letter.
4. Do NOT include prefixes like 'A)' or '1.' in the options or the answer.
"""

    try:
        response = groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": "You are a specialized JSON generator for academic assessments. You always provide the full text of the correct answer in the answer field."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2
        )

        raw_content = response.choices[0].message.content.strip()
        start_idx = raw_content.find("[")
        end_idx = raw_content.rfind("]")
        
        if start_idx == -1 or end_idx == -1:
            raise ValueError("AI response did not contain a JSON array.")
        
        json_str = raw_content[start_idx : end_idx + 1]
        quiz_data = json.loads(json_str)

        sanitized_questions = []
        for idx, q in enumerate(quiz_data):
            clean_opts = [clean_string(opt) for opt in q.get("options", [])]
            raw_ans = q.get("answer") or q.get("correct_answer")
            
            sanitized_questions.append({
                "question_id": str(idx),
                "question": q.get("question"),
                "options": clean_opts,
                "answer": clean_string(raw_ans),
                "co_tag": q.get("co_tag", "General")
            })

        quiz_document = {
            "title": title,
            "course_id": course_id,
            "questions": sanitized_questions,
            "num_questions": len(sanitized_questions),
            "created_by": created_by,
            "created_at": datetime.utcnow()
        }
        
        result = quizzes_collection.insert_one(quiz_document)

        return {
            "quiz_id": str(result.inserted_id),
            "title": title,
            "course_id": course_id,
            "questions": sanitized_questions
        }

    except Exception as e:
        raise Exception(f"Quiz Generation Error: {str(e)}")

def evaluate_quiz(quiz, user_answers):
    """
    Scores the quiz. Handles both index-based answers ("1") and 
    text-based answers ("The actual answer") found in your DB.
    """
    results = []
    questions = quiz.get("questions", [])
    total_score = 0
    
    for q in questions:
        q_id = q.get("question_id")
        student_raw = user_answers.get(q_id, "")
        
        # Stored answer from DB
        db_answer = str(q.get("answer", "")).strip()
        options = q.get("options", [])
        
        is_correct = False
        correct_display_text = db_answer

        # --- LOGIC TO HANDLE BOTH PATTERNS ---
        
        # Pattern 1: DB answer is a numeric index (like "0", "1", "2")
        if db_answer.isdigit():
            idx = int(db_answer)
            if 0 <= idx < len(options):
                correct_display_text = options[idx]
                if str(student_raw).strip().lower() == str(correct_display_text).strip().lower():
                    is_correct = True
        
        # Pattern 2: DB answer is the full text
        else:
            if str(student_raw).strip().lower() == db_answer.lower():
                is_correct = True
        
        if is_correct:
            total_score += 1
            
        results.append({
            "question": q.get("question"),
            "correct_answer": correct_display_text,
            "student_answer": student_raw,
            "is_correct": is_correct,
            "co_tag": q.get("co_tag", "General")
        })
        
    return {
        "score": total_score,
        "total": len(questions),
        "breakdown": results
    }