from fastapi import FastAPI, HTTPException, Depends, Request
from pydantic import BaseModel
from firebase_admin import credentials, firestore
import firebase_admin
import bcrypt
import os
import jwt
from datetime import datetime, timedelta
import base64

# === CONFIG ===
SECRET_KEY = "supersecretkey"  # ⚠️ change in production
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 1 day

# === FIREBASE INIT ===
sa_path = "serviceAccountKey.json"
if not os.path.exists(sa_path):
    raise RuntimeError("Missing serviceAccountKey.json in backend/")

cred = credentials.Certificate(sa_path)
if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)
db = firestore.client()

app = FastAPI(title="Nutrimate Backend")

# === HELPERS ===
def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(request: Request):
    auth = request.headers.get("Authorization")
    if not auth or not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")
    token = auth.split(" ")[1]
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if not email:
            raise HTTPException(status_code=401, detail="Invalid token")
        return email
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

# === MODELS ===
class RegisterReq(BaseModel):
    name: str
    email: str
    password: str
    bowl_size: int
    target_weight: float

class LoginReq(BaseModel):
    email: str
    password: str

class GoalReq(BaseModel):
    goal: int

class MealReq(BaseModel):
    name: str
    macros: dict

class AnalyzeReq(BaseModel):
    image: str  # base64 string

# === ROUTES ===
@app.post("/register")
def register(data: RegisterReq):
    users_ref = db.collection("users").document(data.email)
    if users_ref.get().exists:
        raise HTTPException(status_code=400, detail="User already exists")

    hashed_pw = bcrypt.hashpw(data.password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    users_ref.set({
        "name": data.name,
        "email": data.email,
        "password": hashed_pw,
        "goal": 2000,
        "bowl_size": data.bowl_size,
        "target_weight": data.target_weight,
    })
    return {"ok": True, "msg": "User registered successfully"}

@app.post("/login")
def login(data: LoginReq):
    user_doc = db.collection("users").document(data.email).get()
    if not user_doc.exists:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    user = user_doc.to_dict()
    if not bcrypt.checkpw(data.password.encode("utf-8"), user["password"].encode("utf-8")):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token({"sub": user["email"]})
    return {
        "ok": True,
        "token": token,
        "email": user["email"],
        "name": user.get("name", ""),
        "bowl_size": user.get("bowl_size", 250),
        "target_weight": user.get("target_weight", 0),
    }

@app.post("/analyze")
def analyze(req: AnalyzeReq, email: str = Depends(get_current_user)):
    user_doc = db.collection("users").document(email).get()
    if not user_doc.exists:
        raise HTTPException(status_code=404, detail="User not found")
    user = user_doc.to_dict()
    bowl_size = user.get("bowl_size", 250)

    try:
        img_bytes = base64.b64decode(req.image)
        s = len(img_bytes)
    except Exception:
        s = 25000

    # fake base macros
    base_cal = 150 + (s % 151)  # 150–300
    base_pro = 5 + (s % 16)     # 5–20
    base_car = 20 + (s % 31)    # 20–50
    base_fat = 5 + (s % 11)     # 5–15

    factor = bowl_size / 100.0
    macros = {
        "calories": int(round(base_cal * factor)),
        "protein": round(base_pro * factor, 1),
        "carbs": round(base_car * factor, 1),
        "fats": round(base_fat * factor, 1),
    }

    meal_id = f"{email}_{datetime.utcnow().isoformat()}"
    db.collection("meals").document(meal_id).set({
        "email": email,
        "name": "Bowl Meal",
        "macros": macros,
        "created": datetime.utcnow().isoformat()
    })

    return {"ok": True, "macros": macros, "bowl_size": bowl_size}

@app.post("/add-meal")
def add_meal(data: MealReq, email: str = Depends(get_current_user)):
    meal_id = f"{email}_{datetime.utcnow().isoformat()}"
    db.collection("meals").document(meal_id).set({
        "email": email,
        "name": data.name,
        "macros": data.macros,
        "created": datetime.utcnow().isoformat()
    })
    return {"ok": True, "msg": "Meal added"}

@app.get("/today")
def today(email: str = Depends(get_current_user)):
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    meals_ref = db.collection("meals").where("email", "==", email).stream()

    total = 0
    today_meals = []
    for doc in meals_ref:
        data = doc.to_dict()
        created = data.get("created", "")[:10]
        if created == today_str:
            cals = data.get("macros", {}).get("calories", 0) or 0
            total += cals
            today_meals.append(data)
    return {"email": email, "date": today_str, "calories": total, "meals": today_meals}

@app.get("/history")
def get_history(email: str = Depends(get_current_user)):
    meals_ref = db.collection("meals").where("email", "==", email).stream()
    meals = [doc.to_dict() for doc in meals_ref]
    meals.sort(key=lambda x: x.get("created", ""), reverse=True)
    return {"email": email, "meals": meals}

@app.get("/get-goal")
def get_goal(email: str = Depends(get_current_user)):
    doc = db.collection("users").document(email).get()
    if doc.exists:
        return {"goal": doc.to_dict().get("goal", 2000)}
    return {"goal": 2000}

@app.post("/set-goal")
def set_goal(data: GoalReq, email: str = Depends(get_current_user)):
    if data.goal <= 0:
        raise HTTPException(status_code=400, detail="Goal must be positive")
    db.collection("users").document(email).set({"goal": data.goal}, merge=True)
    return {"ok": True, "goal": data.goal}
