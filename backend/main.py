from fastapi import FastAPI, HTTPException, Depends, File, UploadFile
from fastapi.security import OAuth2PasswordBearer
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from database import engine, Base, get_db
from models import User, Flashcard, Expense, CodeReview
from pydantic import BaseModel
import hashlib
from datetime import datetime, timedelta
from jose import jwt
import os
from dotenv import load_dotenv
import requests as http_requests
import json

# Load environment variables
load_dotenv()

# JWT Configuration
SECRET_KEY = "your-super-secret-key-change-this-in-production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# Create database tables
Base.metadata.create_all(bind=engine)

# Initialize FastAPI app
app = FastAPI(title="DevKit AI Platform")

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

# ---------- Request Models ----------
class SignupRequest(BaseModel):
    email: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

class CodeReviewRequest(BaseModel):
    code: str
    language: str

class FlashcardRequest(BaseModel):
    notes: str
    num_cards: int = 5

class ExpenseRequest(BaseModel):
    text: str

# ---------- Helper Functions ----------
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def create_access_token(data: dict, expires_delta: timedelta = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

# ---------- FALLBACK FUNCTIONS (MUST BE DEFINED BEFORE USE) ----------
def get_fallback_feedback(code: str, language: str) -> str:
    """Basic rule-based code check when AI is unavailable."""
    if language == 'python':
        if 'print' in code and ('(' not in code or ')' not in code):
            return "❌ Missing parentheses in print statement."
        if 'def ' in code and ':' not in code:
            return "❌ Missing colon (:) after function definition."
        if code.count('"') % 2 != 0 or code.count("'") % 2 != 0:
            return "❌ Unclosed string. Check your quotes."
    return "✅ Your code appears structurally correct."

# ---------- Public Endpoints ----------
@app.get("/health")
def health_check():
    return {"status": "OK", "message": "Server is running with database connected"}

@app.post("/signup")
def signup(user_data: SignupRequest, db: Session = Depends(get_db)):
    existing_user = db.query(User).filter(User.email == user_data.email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    hashed_password = hash_password(user_data.password)
    new_user = User(email=user_data.email, password=hashed_password)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return {"message": "User created successfully", "id": new_user.id}

@app.post("/login")
def login(login_data: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == login_data.email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    hashed_input = hash_password(login_data.password)
    if user.password != hashed_input:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    access_token = create_access_token(data={"sub": user.email, "user_id": user.id})
    return {"access_token": access_token, "token_type": "bearer", "user_id": user.id}

# ---------- Protected Endpoints ----------
@app.get("/profile")
def get_profile(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("user_id")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        user = db.query(User).filter(User.id == user_id).first()
        if user is None:
            raise HTTPException(status_code=401, detail="User not found")
        return {"id": user.id, "email": user.email}
    except:
        raise HTTPException(status_code=401, detail="Invalid token")

# ---------- AI Code Reviewer ----------
@app.post("/review-code")
def review_code(request: CodeReviewRequest, token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("user_id")
    except:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="Gemini API key not configured")
    
    prompt = f"""
You are a strict code reviewer. Analyze the following {request.language} code.

INSTRUCTIONS:
1. If the code has NO errors and is perfectly correct, respond ONLY with the word: "Correct!"
2. If the code has ANY errors, bugs, or missing parts, respond with a VERY SHORT bullet list (max 3 bullets) explaining ONLY what is missing or wrong. Keep it extremely clear for a beginner.

Code:
{request.code}
"""
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
    
    try:
        response = http_requests.post(url, json=payload, timeout=20)
        response.raise_for_status()
        data = response.json()
        feedback = data["candidates"][0]["content"]["parts"][0]["text"]
        
        new_review = CodeReview(
            user_id=user_id,
            code=request.code,
            language=request.language,
            feedback=feedback
        )
        db.add(new_review)
        db.commit()
        
        return {"feedback": feedback}
    except Exception as e:
        return {"feedback": get_fallback_feedback(request.code, request.language)}
    
@app.post("/review-file")
async def review_file(
    token: str = Depends(oauth2_scheme),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("user_id")
    except:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    content = await file.read()
    try:
        code = content.decode("utf-8")
    except:
        raise HTTPException(status_code=400, detail="Could not read file. Please upload a text-based code file.")
    
    lang_map = {
        ".py": "python", ".js": "javascript", ".ts": "typescript",
        ".java": "java", ".c": "c", ".cpp": "cpp", ".cs": "csharp",
        ".go": "go", ".rs": "rust", ".rb": "ruby", ".php": "php",
        ".html": "html", ".css": "css", ".json": "json"
    }
    ext = os.path.splitext(file.filename)[1].lower()
    language = lang_map.get(ext, "unknown")
    
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="Gemini API key not configured")
    
    prompt = f"""
You are a strict code reviewer. Analyze the following {language} code.

INSTRUCTIONS:
1. If the code has NO errors and is perfectly correct, respond ONLY with: "Correct!"
2. If the code has ANY errors, bugs, or missing parts, respond with a VERY SHORT bullet list (max 3 bullets).

Code:
{code}
"""
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
    
    try:
        response = http_requests.post(url, json=payload, timeout=20)
        response.raise_for_status()
        data = response.json()
        feedback = data["candidates"][0]["content"]["parts"][0]["text"]
        
        new_review = CodeReview(
            user_id=user_id,
            code=code[:500] + ("..." if len(code) > 500 else ""),
            language=language,
            feedback=feedback
        )
        db.add(new_review)
        db.commit()
        
        return {"feedback": feedback, "language": language}
    except Exception as e:
        return {"feedback": get_fallback_feedback(code, language), "language": language}

# ---------- AI Flashcard Generator ----------
@app.post("/generate-flashcards")
def generate_flashcards(request: FlashcardRequest, token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("user_id")
    except:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="Gemini API key not configured")
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
    
    prompt = f"""Generate {request.num_cards} flashcards from the following text.
    Return ONLY valid JSON in this exact format:
    [
        {{"front": "Question 1", "back": "Answer 1"}},
        {{"front": "Question 2", "back": "Answer 2"}}
    ]
    Text: {request.notes}"""
    
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    
    try:
        response = http_requests.post(url, json=payload, timeout=20)
        response.raise_for_status()
        data = response.json()
        flashcard_data = data["candidates"][0]["content"]["parts"][0]["text"]
        
        try:
            flashcards = json.loads(flashcard_data)
            saved_cards = []
            for card in flashcards:
                new_card = Flashcard(
                    user_id=user_id,
                    front=card["front"],
                    back=card["back"]
                )
                db.add(new_card)
                db.commit()
                db.refresh(new_card)
                saved_cards.append({"id": new_card.id, "front": new_card.front, "back": new_card.back})
            return {"flashcards": saved_cards}
        except json.JSONDecodeError:
            return {"flashcards": [], "raw": flashcard_data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI Error: {str(e)}")

# ---------- AI Expense Parser ----------
@app.post("/parse-expense")
def parse_expense(request: ExpenseRequest, token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("user_id")
    except:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="Gemini API key not configured")
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
    
    prompt = f"""Extract the category and amount from this expense text.
    Return ONLY valid JSON in this exact format:
    {{"category": "category_name", "amount": "amount"}}
    Text: {request.text}"""
    
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    
    try:
        response = http_requests.post(url, json=payload, timeout=20)
        response.raise_for_status()
        data = response.json()
        result_text = data["candidates"][0]["content"]["parts"][0]["text"]
        
        try:
            expense_data = json.loads(result_text)
            new_expense = Expense(
                user_id=user_id,
                description=request.text,
                category=expense_data["category"],
                amount=expense_data["amount"]
            )
            db.add(new_expense)
            db.commit()
            db.refresh(new_expense)
            return {
                "id": new_expense.id,
                "description": new_expense.description,
                "category": new_expense.category,
                "amount": new_expense.amount
            }
        except json.JSONDecodeError:
            return {"raw": result_text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI Error: {str(e)}")

# ---------- History Endpoints ----------
@app.get("/history")
def get_history(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("user_id")
    except:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    reviews = db.query(CodeReview).filter(CodeReview.user_id == user_id).order_by(CodeReview.created_at.desc()).all()
    
    return [
        {
            "id": r.id,
            "code": r.code,
            "language": r.language,
            "feedback": r.feedback[:150] + ("..." if len(r.feedback) > 150 else ""),
            "created_at": r.created_at.strftime("%Y-%m-%d %H:%M")
        } for r in reviews
    ]

@app.delete("/history/{review_id}")
def delete_history(review_id: int, token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("user_id")
    except:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    review = db.query(CodeReview).filter(CodeReview.id == review_id, CodeReview.user_id == user_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    
    db.delete(review)
    db.commit()
    return {"message": "Review deleted successfully"}

# ---------- SERVE STATIC FILES ----------
app.mount("/", StaticFiles(directory="static", html=True), name="static")