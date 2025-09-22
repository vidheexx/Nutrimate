from fastapi import FastAPI, HTTPException, Depends, Request
from pydantic import BaseModel
from firebase_admin import credentials, firestore
import firebase_admin
import bcrypt
import os
import jwt
from datetime import datetime, timedelta

SECRET_KEY = "supersecretkey"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24

# === FIREBASE INIT ===
sa_path = "serviceAccountKey.json"
if not os.path.exists(sa_path):
    raise RuntimeError("Missing serviceAccountKey.json in backend/")

cred = credentials.Certificate(sa_path)
if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)
db = firestore.client()

app = FastAPI(title="Nutrimate Backend")

# === Auth helpers ===
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

# === Models ===
class RegisterReq(BaseModel):
    name: str
    email: str
    password: str

class LoginReq(BaseModel):
    email: str
    password: str

class GoalReq(BaseModel):
    goal: int

class MealReq(BaseModel):
    name: str
    macros: dict

# === Routes ===
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
        "goal": 2000
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
    return {"ok": True, "token": token, "email": user["email"], "name": user.get("name", "")}

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

@app.get("/get-goal")   # ✅ missing decorator added back
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
