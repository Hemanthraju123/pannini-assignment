import os
from fastapi import FastAPI, Request, Form, UploadFile, File, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from database import SessionLocal, engine, Base
import models
from typing import Optional

app = FastAPI(title="EdTech Assignment Tracker")

Base.metadata.create_all(bind=engine)

app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
templates = Jinja2Templates(directory="templates")

# --- Dependency ---
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- Simple Auth (sessionless, demo only) ---
USERS = [
    {"username": "teacher1", "password": "teachpass", "role": "teacher"},
    {"username": "student1", "password": "studpass", "role": "student"},
]

def authenticate_user(username: str, password: str):
    for user in USERS:
        if user["username"] == username and user["password"] == password:
            return user
    return None

# --- UI Routes ---
@app.get("/", response_class=HTMLResponse)
def home():
    return RedirectResponse(url="/login")

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})

@app.post("/login", response_class=HTMLResponse)
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    user = authenticate_user(username, password)
    if not user:
        return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid credentials"})
    if user["role"] == "teacher":
        return RedirectResponse(url="/teacher?user=" + username, status_code=302)
    else:
        return RedirectResponse(url="/student?user=" + username, status_code=302)

@app.get("/teacher", response_class=HTMLResponse)
def teacher_dashboard(request: Request, user: str, db: Session = Depends(get_db)):
    assignments = db.query(models.Assignment).all()
    submissions = db.query(models.Submission).all()
    return templates.TemplateResponse("teacher.html", {"request": request, "user": user, "assignments": assignments, "submissions": submissions})

@app.get("/student", response_class=HTMLResponse)
def student_dashboard(request: Request, user: str, db: Session = Depends(get_db)):
    assignments = db.query(models.Assignment).all()
    # For each assignment, attach submissions for this assignment
    for a in assignments:
        a.submissions = db.query(models.Submission).filter(models.Submission.assignment_id == a.id).all()
    return templates.TemplateResponse("student.html", {"request": request, "user": user, "assignments": assignments})

# --- API: Create Assignment (Teacher) ---
@app.post("/api/assignments")
def create_assignment(title: str = Form(...), description: str = Form(...), user: str = Form(...), db: Session = Depends(get_db)):
    # Only teacher can create
    teacher = next((u for u in USERS if u["username"] == user and u["role"] == "teacher"), None)
    if not teacher:
        raise HTTPException(status_code=403, detail="Not authorized")
    assignment = models.Assignment(title=title, description=description, created_by=0)  # demo: no user id
    db.add(assignment)
    db.commit()
    db.refresh(assignment)
    return RedirectResponse(url=f"/teacher?user={user}", status_code=302)

# --- API: Submit Assignment (Student) ---
@app.post("/api/submit/{assignment_id}")
def submit_assignment(assignment_id: int, user: str = Form(...), file: UploadFile = File(...), db: Session = Depends(get_db)):
    # Only student can submit
    student = next((u for u in USERS if u["username"] == user and u["role"] == "student"), None)
    if not student:
        raise HTTPException(status_code=403, detail="Not authorized")
    os.makedirs("uploads", exist_ok=True)
    file_location = f"uploads/{user}_{assignment_id}_{file.filename}"
    with open(file_location, "wb") as f:
        f.write(file.file.read())
    submission = models.Submission(assignment_id=assignment_id, student_id=0, file_path=file_location)
    db.add(submission)
    db.commit()
    db.refresh(submission)
    return RedirectResponse(url=f"/student?user={user}", status_code=302)


# --- API: View Submissions (Teacher) ---
@app.get("/api/submissions", response_class=HTMLResponse)
def view_submissions(user: str, db: Session = Depends(get_db)):
    teacher = next((u for u in USERS if u["username"] == user and u["role"] == "teacher"), None)
    if not teacher:
        raise HTTPException(status_code=403, detail="Not authorized")
    submissions = db.query(models.Submission).all()
    return templates.TemplateResponse("submissions.html", {"request": {}, "user": user, "submissions": submissions})

# --- API: Delete Assignment (Teacher) ---
@app.post("/api/delete_assignment/{assignment_id}")
def delete_assignment(assignment_id: int, user: str = Form(...), db: Session = Depends(get_db)):
    teacher = next((u for u in USERS if u["username"] == user and u["role"] == "teacher"), None)
    if not teacher:
        raise HTTPException(status_code=403, detail="Not authorized")
    assignment = db.query(models.Assignment).filter(models.Assignment.id == assignment_id).first()
    if assignment:
        # Delete all submissions for this assignment
        submissions = db.query(models.Submission).filter(models.Submission.assignment_id == assignment_id).all()
        for s in submissions:
            if s.file_path and os.path.exists(s.file_path):
                os.remove(s.file_path)
            db.delete(s)
        db.delete(assignment)
        db.commit()
    return RedirectResponse(url=f"/teacher?user={user}", status_code=302)

# --- API: Delete Submission (Teacher) ---
@app.post("/api/delete_submission/{submission_id}")
def delete_submission_teacher(submission_id: int, user: str = Form(...), db: Session = Depends(get_db)):
    teacher = next((u for u in USERS if u["username"] == user and u["role"] == "teacher"), None)
    if not teacher:
        raise HTTPException(status_code=403, detail="Not authorized")
    submission = db.query(models.Submission).filter(models.Submission.id == submission_id).first()
    if submission:
        if submission.file_path and os.path.exists(submission.file_path):
            os.remove(submission.file_path)
        db.delete(submission)
        db.commit()
    return RedirectResponse(url=f"/teacher?user={user}", status_code=302)

# --- API: Delete Submission (Student) ---
@app.post("/api/delete_own_submission/{submission_id}")
def delete_submission_student(submission_id: int, user: str = Form(...), db: Session = Depends(get_db)):
    student = next((u for u in USERS if u["username"] == user and u["role"] == "student"), None)
    if not student:
        raise HTTPException(status_code=403, detail="Not authorized")
    submission = db.query(models.Submission).filter(models.Submission.id == submission_id).first()
    if submission:
        # Only allow if this user is the submitter (student_id is not used in demo, so check file_path prefix)
        if submission.file_path and submission.file_path.startswith(f"uploads/{user}_"):
            if os.path.exists(submission.file_path):
                os.remove(submission.file_path)
            db.delete(submission)
            db.commit()
    return RedirectResponse(url=f"/student?user={user}", status_code=302)
