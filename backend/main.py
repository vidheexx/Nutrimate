# backend/main.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
import json
import os

DATA_FILE = "db_demo.json"

app = FastAPI(title="Nutrimate Demo Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- tiny JSON persistence for demo ---
def _load_db():
    if not os.path.exists(DATA_FILE):
        db = {"users": {}, "meals": []}
        with open(DATA_FILE, "w") as f:
            json.dump(db, f)
        return db
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def _save_db(db):
    with open(DATA_FILE, "w") as f:
        json.dump(db, f, default=str)

# --- models ---
class RegisterReq(BaseModel):
    email: str
    password: str
    name: str

class LoginReq(BaseModel):
    email: str
    password: str

class SetGoalReq(BaseModel):
    email: str
    calories: int
    protein: int
    carbs: int
    fats: int

class AnalyzeReq(BaseModel):
    email: str
    calories: Optional[int] = None
    protein: Optional[float] = None
    carbs: Optional[float] = None
    fats: Optional[float] = None
    name: Optional[str] = "Meal"

# --- helpers ---
def _today_iso():
    return datetime.now(timezone.utc).date().isoformat()

def _sum_today_for_email(db, email):
    today = _today_iso()
    meals = [m for m in db.get("meals", []) if m.get("email")==email and m.get("date")==today]
    total = {"calories": 0, "protein": 0.0, "carbs": 0.0, "fats": 0.0}
    for m in meals:
        mac = m.get("macros", {})
        total["calories"] += int(mac.get("calories",0))
        total["protein"] += float(mac.get("protein",0))
        total["carbs"] += float(mac.get("carbs",0))
        total["fats"] += float(mac.get("fats",0))
    return total

# --- routes ---
@app.post("/register")
async def register(req: RegisterReq):
    db = _load_db()
    email = req.email.lower().strip()
    if email in db["users"]:
        raise HTTPException(status_code=400, detail="Email already registered")
    if len(req.password) < 4:
        raise HTTPException(status_code=400, detail="Password too short (min 4 chars)")
    db["users"][email] = {
        "name": req.name,
        "password": req.password,
        "goal": {"calories": 2000, "protein": 100, "carbs": 250, "fats": 70},
        "created": datetime.now(timezone.utc).isoformat()
    }
    _save_db(db)
    return {"ok": True, "msg": "registered"}

@app.post("/login")
async def login(req: LoginReq):
    db = _load_db()
    email = req.email.lower().strip()
    u = db["users"].get(email)
    if not u or u.get("password") != req.password:
        raise HTTPException(status_code=400, detail="Invalid credentials")
    totals = _sum_today_for_email(db, email)
    return {"ok": True, "email": email, "name": u.get("name"), "goal": u.get("goal"), "today": totals}

@app.post("/set-goal")
async def set_goal(req: SetGoalReq):
    db = _load_db()
    email = req.email.lower().strip()
    if email not in db["users"]:
        raise HTTPException(status_code=404, detail="User not found")
    db["users"][email]["goal"] = {
        "calories": int(req.calories),
        "protein": int(req.protein),
        "carbs": int(req.carbs),
        "fats": int(req.fats),
    }
    _save_db(db)
    totals = _sum_today_for_email(db, email)
    return {"ok": True, "goal": db["users"][email]["goal"], "today": totals}

@app.post("/analyze")
async def analyze(req: AnalyzeReq):
    """
    Demo analyze: Accepts email + macros (frontend should send macros).
    Saves a meal and returns updated today's totals & saved meal.
    """
    if not req.email:
        raise HTTPException(status_code=400, detail="Missing email")
    db = _load_db()
    email = req.email.lower().strip()
    if email not in db["users"]:
        raise HTTPException(status_code=404, detail="User not found")

    calories = int(req.calories) if req.calories is not None else 250
    protein = float(req.protein) if req.protein is not None else 12.0
    carbs = float(req.carbs) if req.carbs is not None else 30.0
    fats = float(req.fats) if req.fats is not None else 8.0

    meal = {
        "id": f"{email}_{datetime.now(timezone.utc).isoformat()}",
        "email": email,
        "name": req.name or "Meal",
        "macros": {"calories": calories, "protein": protein, "carbs": carbs, "fats": fats},
        "date": _today_iso(),
        "created": datetime.now(timezone.utc).isoformat()
    }
    db["meals"].append(meal)
    _save_db(db)

    totals = _sum_today_for_email(db, email)
    return {"ok": True, "meal": meal, "today": totals}

@app.get("/today")
async def today(email: str):
    db = _load_db()
    email = email.lower().strip()
    if email not in db["users"]:
        raise HTTPException(status_code=404, detail="User not found")
    totals = _sum_today_for_email(db, email)
    return {"ok": True, "date": _today_iso(), "totals": totals}

@app.get("/history")
async def history(email: str):
    db = _load_db()
    email = email.lower().strip()
    if email not in db["users"]:
        raise HTTPException(status_code=404, detail="User not found")
    meals = [m for m in db.get("meals", []) if m.get("email")==email]
    meals.sort(key=lambda x: x.get("created",""), reverse=True)
    return {"ok": True, "meals": meals}

@app.get("/get-goal")
async def get_goal(email: str):
    db = _load_db()
    email = email.lower().strip()
    if email not in db["users"]:
        raise HTTPException(status_code=404, detail="User not found")
    goal = db["users"][email].get("goal", {"calories":2000,"protein":100,"carbs":250,"fats":70})
    totals = _sum_today_for_email(db, email)
    return {"ok": True, "goal": goal, "today": totals}

@app.post("/calibrate")
async def calibrate(payload: Dict[str, Any]):
    return {"ok": True, "msg": "calibrated (demo)"}
