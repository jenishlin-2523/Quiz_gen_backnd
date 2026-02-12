import fitz
import re
import json
from groq import Groq
from config import GROQ_API_KEY, GROQ_MODEL
from database.mongo import quizzes_collection
from datetime import datetime

groq_client = Groq(api_key=GROQ_API_KEY)

def text_chunk_limit(text, max_tokens=2000):
    """Limit the text chunk to prevent token overflow while keeping context."""
    # Rough estimation: 1 token ≈ 4 characters
    return text[:max_tokens * 4]

def generate_quiz_from_pdf(pdf_file, created_by, course_id, title, num_questions, course_outcomes_json):
    """
    Generates an OBE-compliant quiz. 
    Handles cases where AI includes conversational text around the JSON.
    """
    try:
        # 1. Parse Course Outcomes
        all_cos = json.loads(course_outcomes_json) if course_outcomes_json else []
        
        # 2. Extract Text from PDF
        pdf_stream = pdf_file.read()
        doc = fitz.open(stream=pdf_stream, filetype="pdf")
        extracted_text = "".join(page.get_text() for page in doc)
        doc.close()
        
        if not extracted_text.strip():
            raise ValueError("The uploaded PDF seems to be empty or contains only images.")
            
    except Exception as e:
        raise Exception(f"Preprocessing Error: {e}")

    # 3. Enhanced Prompt
    prompt = f"""
Generate exactly {num_questions} multiple choice questions from this text:
{text_chunk_limit(extracted_text)}

COURSE: {course_id}
OUTCOMES TO COVER:
{chr(10).join(all_cos)}

STRICT RULES:
1. Provide the output ONLY as a valid JSON array.
2. Each object must have: "question", "options" (array of 4), "answer", and "co_tag".
3. Distribute questions across the COs provided.
"""

    try:
        # 4. Call Groq
        response = groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": "You are a specialized JSON generator for academic assessments. Do not include introductory text."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2
        )

        raw_content = response.choices[0].message.content.strip()

        # 5. Robust JSON Extraction (Fixes the IndexError: No such group)
        try:
            # Find the first '[' and the last ']'
            start_idx = raw_content.find("[")
            end_idx = raw_content.rfind("]")
            
            if start_idx == -1 or end_idx == -1:
                print(f"DEBUG RAW CONTENT: {raw_content}")
                raise ValueError("AI response did not contain a JSON array.")
            
            json_str = raw_content[start_idx : end_idx + 1]
            quiz_data = json.loads(json_str)

        except json.JSONDecodeError:
            print(f"FAILED TO PARSE: {raw_content}")
            raise ValueError("AI generated invalid JSON structure.")

        # 6. Save to Database
        quiz_document = {
            "title": title,
            "course_id": course_id,
            "questions": quiz_data,
            "num_questions": len(quiz_data),
            "created_by": created_by,
            "created_at": datetime.utcnow()
        }
        
        result = quizzes_collection.insert_one(quiz_document)

        return {
            "quiz_id": str(result.inserted_id),
            "title": title,
            "course_id": course_id,
            "questions": quiz_data
        }

    except Exception as e:
        # This will be caught by the route and sent to frontend
        raise Exception(f"Quiz Generation Error: {str(e)}")

def get_latest_quiz():
    quiz = quizzes_collection.find_one(sort=[("_id", -1)])
    if quiz:
        quiz["_id"] = str(quiz["_id"])
        return quiz
    return None

def evaluate_quiz(quiz, user_answers):
    """
    Scores the quiz and maintains CO mapping for analytics.
    """
    results = []
    questions = quiz.get("questions", [])
    
    for idx, q in enumerate(questions):
        q_id = str(idx)
        selected = user_answers.get(q_id)
        
        results.append({
            "question": q.get("question"),
            "correct_answer": q.get("answer"),
            "student_answer": selected,
            "is_correct": selected == q.get("answer"),
            "co_tag": q.get("co_tag", "General")
        })
    return results