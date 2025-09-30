from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, Dict, Any
from datetime import datetime, timezone
import json, os

DATA_FILE = "db_demo.json"

app = FastAPI(title="Nutrimate Demo Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- persistence ---
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

class CalibrateReq(BaseModel):
    email: str
    small: float
    medium: float
    large: float

class AnalyzeReq(BaseModel):
    email: str
    calories: Optional[int] = None
    protein: Optional[float] = None
    carbs: Optional[float] = None
    fats: Optional[float] = None
    name: Optional[str] = "Meal"
    bowl_size: Optional[str] = None   # "small","medium","large"
    portion: Optional[float] = 1.0    # fraction (0.5, 1, 2)

# --- helpers ---
def _today_iso():
    return datetime.now(timezone.utc).date().isoformat()

def _sum_today_for_email(db, email):
    today = _today_iso()
    meals = [m for m in db.get("meals", []) if m.get("email") == email and m.get("date") == today]
    total = {"calories": 0, "protein": 0.0, "carbs": 0.0, "fats": 0.0}
    for m in meals:
        mac = m.get("macros", {})
        total["calories"] += int(mac.get("calories", 0))
        total["protein"] += float(mac.get("protein", 0))
        total["carbs"] += float(mac.get("carbs", 0))
        total["fats"] += float(mac.get("fats", 0))
    return total

# --- routes ---
@app.post("/register")
async def register(req: RegisterReq):
    db = _load_db()
    email = req.email.lower().strip()
    if email in db["users"]:
        raise HTTPException(400, "Email already registered")
    if len(req.password) < 4:
        raise HTTPException(400, "Password too short")
    db["users"][email] = {
        "name": req.name,
        "password": req.password,
        "goal": {"calories": 2000, "protein": 100, "carbs": 250, "fats": 70},
        "created": datetime.now(timezone.utc).isoformat(),
    }
    _save_db(db)
    return {"ok": True, "msg": "registered"}

@app.post("/login")
async def login(req: LoginReq):
    db = _load_db()
    email = req.email.lower().strip()
    u = db["users"].get(email)
    if not u or u.get("password") != req.password:
        raise HTTPException(400, "Invalid credentials")
    return {
        "ok": True,
        "email": email,
        "name": u["name"],
        "goal": u["goal"],
        "calibration": u.get("calibration"),
        "today": _sum_today_for_email(db, email),
    }

@app.post("/set-goal")
async def set_goal(req: SetGoalReq):
    db = _load_db()
    email = req.email.lower().strip()
    if email not in db["users"]:
        raise HTTPException(404, "User not found")
    db["users"][email]["goal"] = {
        "calories": req.calories,
        "protein": req.protein,
        "carbs": req.carbs,
        "fats": req.fats,
    }
    _save_db(db)
    return {"ok": True, "goal": db["users"][email]["goal"], "today": _sum_today_for_email(db, email)}

@app.post("/calibrate")
async def calibrate(req: CalibrateReq):
    db = _load_db()
    email = req.email.lower().strip()
    if email not in db["users"]:
        raise HTTPException(404, "User not found")
    db["users"][email]["calibration"] = {"small": req.small, "medium": req.medium, "large": req.large}
    _save_db(db)
    return {"ok": True, "calibration": db["users"][email]["calibration"]}

@app.post("/analyze")
async def analyze(req: AnalyzeReq):
    if not req.email:
        raise HTTPException(400, "Missing email")
    db = _load_db()
    email = req.email.lower().strip()
    if email not in db["users"]:
        raise HTTPException(404, "User not found")

    c = int(req.calories or 250)
    p = float(req.protein or 12)
    cb = float(req.carbs or 30)
    f = float(req.fats or 8)

    calib = db["users"][email].get("calibration")
    if calib and req.bowl_size in calib:
        factor = calib[req.bowl_size] * (req.portion or 1) / 100.0
        c *= factor
        p *= factor
        cb *= factor
        f *= factor

    meal = {
        "id": f"{email}_{datetime.now(timezone.utc).isoformat()}",
        "email": email,
        "name": req.name or "Meal",
        "macros": {"calories": c, "protein": p, "carbs": cb, "fats": f},
        "date": _today_iso(),
        "created": datetime.now(timezone.utc).isoformat(),
    }
    db["meals"].append(meal)
    _save_db(db)
    return {"ok": True, "meal": meal, "today": _sum_today_for_email(db, email)}

@app.get("/today")
async def today(email: str):
    db = _load_db()
    email = email.lower().strip()
    if email not in db["users"]:
        raise HTTPException(404, "User not found")
    return {"ok": True, "date": _today_iso(), "totals": _sum_today_for_email(db, email)}

@app.get("/history")
async def history(email: str):
    db = _load_db()
    email = email.lower().strip()
    if email not in db["users"]:
        raise HTTPException(404, "User not found")
    meals = [m for m in db["meals"] if m["email"] == email]
    meals.sort(key=lambda x: x.get("created", ""), reverse=True)
    return {"ok": True, "meals": meals}

@app.get("/get-goal")
async def get_goal(email: str):
    db = _load_db()
    email = email.lower().strip()
    if email not in db["users"]:
        raise HTTPException(404, "User not found")
    return {
        "ok": True,
        "goal": db["users"][email]["goal"],
        "calibration": db["users"][email].get("calibration"),
        "today": _sum_today_for_email(db, email),
    }
