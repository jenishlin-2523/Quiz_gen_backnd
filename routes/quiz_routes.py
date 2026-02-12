from flask import Blueprint, request, jsonify
from flask_jwt_extended import get_jwt_identity, jwt_required, get_jwt
from utils.decorators import staff_required, student_required
from services.quiz_service import generate_quiz_from_pdf
from database.mongo import quizzes_collection, quiz_results_collection
from bson import ObjectId
from datetime import datetime

quiz_bp = Blueprint("quiz", __name__)

# ---------------- STAFF GET THEIR QUIZZES ----------------
@quiz_bp.route("/staff/quizzes", methods=["GET"])
@staff_required
def get_staff_quizzes():
    staff_id = get_jwt_identity()
    quizzes_cursor = quizzes_collection.find({"created_by": staff_id}).sort("_id", -1)

    quizzes = []
    for quiz in quizzes_cursor:
        quizzes.append({
            "quiz_id": str(quiz["_id"]),
            "course_id": quiz.get("course_id"),
            "title": quiz.get("title", "Untitled Quiz"),
            "questions_count": len(quiz.get("questions", [])),
            "created_at": quiz.get("created_at", datetime.utcnow())
        })
    return jsonify({"quizzes": quizzes}), 200


# ---------------- STAFF UPLOAD QUIZ ----------------
@quiz_bp.route("/staff/quiz/upload", methods=["POST"])
@staff_required
def staff_upload_quiz():
    if 'pdf' not in request.files:
        return jsonify({"message": "No PDF uploaded"}), 400
    
    pdf_file = request.files['pdf']
    course_id = request.form.get("course_id")
    title = request.form.get("title") or "Untitled Quiz"
    num_questions = request.form.get("num_questions", default=10, type=int)
    course_outcomes_json = request.form.get("course_outcomes")
    
    identity = get_jwt_identity()

    if not course_id:
        return jsonify({"message": "Course ID is required"}), 400
    
    try:
        quiz = generate_quiz_from_pdf(
            pdf_file, 
            created_by=identity, 
            course_id=course_id, 
            title=title,
            num_questions=num_questions,
            course_outcomes_json=course_outcomes_json
        )

        return jsonify({
            "message": "Quiz generated successfully!",
            "quiz_id": quiz["quiz_id"],
            "title": quiz["title"],
            "course_id": quiz["course_id"]
        }), 200

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"message": str(e)}), 500


# ---------------- STAFF GET QUIZ BY ID ----------------
@quiz_bp.route("/staff/quiz/<quiz_id>", methods=["GET"])
@staff_required
def get_staff_quiz_by_id(quiz_id):
    try:
        obj_id = ObjectId(quiz_id)
    except Exception:
        return jsonify({"message": "Invalid quiz ID format"}), 400

    quiz = quizzes_collection.find_one({"_id": obj_id})
    if not quiz:
        return jsonify({"message": "Quiz not found"}), 404

    questions = quiz.get("questions", [])
    for idx, q in enumerate(questions):
        q["question_id"] = str(idx)

    return jsonify({
        "quiz_id": str(quiz["_id"]),
        "title": quiz.get("title", "Untitled Quiz"),
        "course_id": quiz.get("course_id"),
        "questions": questions
    }), 200


# --- STAFF: VIEW RESULTS BY COURSE (With CORS Fix) ---
@quiz_bp.route("/staff/results/<course_id>", methods=["GET", "OPTIONS"])
def get_course_results(course_id):
    if request.method == "OPTIONS":
        return jsonify({"msg": "ok"}), 200

    @jwt_required()
    def fetch_data():
        claims = get_jwt()
        if claims.get("role") != "staff":
            return jsonify({"msg": "Staff access required"}), 403
        try:
            course_quizzes = list(quizzes_collection.find({"course_id": course_id}, {"_id": 1, "title": 1}))
            if not course_quizzes:
                return jsonify({"results": []}), 200

            quiz_ids = [q["_id"] for q in course_quizzes]
            results_list = list(quiz_results_collection.find({"quiz_id": {"$in": quiz_ids}}).sort("submitted_at", -1))

            formatted = []
            for res in results_list:
                quiz_info = next((q for q in course_quizzes if q["_id"] == res["quiz_id"]), None)
                formatted.append({
                    "result_id": str(res["_id"]),
                    "student_id": res.get("student_id"),
                    "quiz_title": quiz_info["title"] if quiz_info else "Deleted Quiz",
                    "score": res.get("score"),
                    "total": res.get("total_questions"),
                    "percentage": res.get("percentage"),
                    "submitted_at": res.get("submitted_at")
                })
            return jsonify({"results": formatted}), 200
        except Exception as e:
            return jsonify({"msg": "Error", "error": str(e)}), 500
    return fetch_data()


# ---------------- STUDENT ROUTES ----------------
@quiz_bp.route("/student/quizzes", methods=["GET"])
@student_required
def student_get_quizzes():
    course_id = request.args.get("course_id")
    query = {}
    if course_id:
        query["course_id"] = course_id

    student_id = get_jwt_identity()
    quizzes_cursor = quizzes_collection.find(query).sort("_id", -1)
    quizzes = []

    for quiz in quizzes_cursor:
        quiz_id = str(quiz["_id"])
        submission = quiz_results_collection.find_one({"quiz_id": quiz["_id"], "student_id": student_id})
        quizzes.append({
            "quiz_id": quiz_id,
            "course_id": quiz.get("course_id"),
            "questions_count": len(quiz.get("questions", [])),
            "title": quiz.get("title", "Untitled Quiz"),
            "submitted": True if submission else False
        })
    return jsonify({"quizzes": quizzes}), 200


@quiz_bp.route("/student/quiz/<quiz_id>", methods=["GET"])
@student_required
def get_student_quiz_by_id(quiz_id):
    try:
        obj_id = ObjectId(quiz_id)
    except Exception:
        return jsonify({"message": "Invalid ID"}), 400

    quiz = quizzes_collection.find_one({"_id": obj_id})
    if not quiz: 
        return jsonify({"message": "Quiz not found"}), 404

    student_id = get_jwt_identity()
    if quiz_results_collection.find_one({"quiz_id": obj_id, "student_id": student_id}):
        return jsonify({"submitted": True, "message": "Already submitted"}), 403

    questions = quiz.get("questions", [])
    sanitized = []
    for idx, q in enumerate(questions):
        q_copy = q.copy()
        q_copy.pop("answer", None)
        q_copy["question_id"] = str(idx)
        sanitized.append(q_copy)

    return jsonify({"submitted": False, "questions": sanitized}), 200


# --- STUDENT: SUBMIT QUIZ ---
@quiz_bp.route("/student/quiz/<quiz_id>/submit", methods=["POST"])
@student_required
def submit_quiz_answers(quiz_id):
    try:
        obj_id = ObjectId(quiz_id)
        student_id = get_jwt_identity()
        
        # Check if already submitted
        if quiz_results_collection.find_one({"quiz_id": obj_id, "student_id": student_id}):
            return jsonify({"message": "Already submitted"}), 403

        # Get quiz from database
        quiz = quizzes_collection.find_one({"_id": obj_id})
        if not quiz: 
            return jsonify({"message": "Quiz not found"}), 404

        # Get user answers from request
        data = request.get_json(force=True)
        user_answers = data.get("answers", {})

        # Evaluate the quiz
        results = evaluate_quiz(quiz, user_answers)
        total = len(results)
        correct = sum(1 for r in results if r["is_correct"])
        percentage = round((correct / total * 100), 2) if total > 0 else 0

        # Save result to database
        quiz_results_collection.insert_one({
            "quiz_id": obj_id,
            "student_id": student_id,
            "score": correct,
            "total_questions": total,
            "percentage": percentage,
            "submitted_at": datetime.utcnow(),
            "details": results
        })
        
        return jsonify({
            "score": correct, 
            "total": total, 
            "percentage": percentage
        }), 200
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"message": str(e)}), 500


# ---------------- HELPER: EVALUATION ----------------
def evaluate_quiz(quiz, user_answers):
    """
    Evaluates quiz answers by comparing student answers with correct answers.
    Expects both answers to be stored as indices: "0", "1", "2", "3"
    """
    results = []
    questions = quiz.get("questions", [])
    
    print(f"\n{'='*60}")
    print(f"DEBUG: Evaluating quiz with {len(questions)} questions")
    print(f"DEBUG: User answers received: {user_answers}")
    print(f"{'='*60}\n")
    
    for idx, q in enumerate(questions):
        q_id = str(idx)
        
        # Get correct answer from database (should be index like "0", "1", "2", "3")
        correct_ans = str(q.get("answer", "")).strip()
        
        # Get student's submitted answer (should also be index like "0", "1", "2", "3")
        student_ans = str(user_answers.get(q_id, "")).strip()
        
        # Check if answer is correct
        is_correct = (student_ans == correct_ans) and (student_ans != "" and correct_ans != "")
        
        # Debug output for each question
        print(f"Question {q_id}:")
        print(f"  Question text: {q.get('question', 'N/A')[:50]}...")
        print(f"  Student answer: '{student_ans}'")
        print(f"  Correct answer: '{correct_ans}'")
        print(f"  Is correct: {is_correct}")
        print(f"  Choices: {q.get('choices', [])}")
        print()
        
        results.append({
            "question_id": q_id,
            "question_text": q.get("question"),
            "student_answer": student_ans,
            "correct_answer": correct_ans,
            "is_correct": is_correct
        })
    
    correct_count = sum(1 for r in results if r["is_correct"])
    print(f"\n{'='*60}")
    print(f"DEBUG: Final score: {correct_count}/{len(results)} correct")
    print(f"{'='*60}\n")
    
    return results