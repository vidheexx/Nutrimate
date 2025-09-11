import base64, io
from fastapi import FastAPI
from pydantic import BaseModel
from PIL import Image
import torch
import torchvision.transforms as T
import torchvision.models as models
import firebase_admin
from firebase_admin import credentials, firestore

# Firebase init (download serviceAccountKey.json from Firebase console)
cred = credentials.Certificate("serviceAccountKey.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

# Pretrained model
model = models.mobilenet_v2(weights="IMAGENET1K_V1")
model.eval()

transform = T.Compose([
    T.Resize((224,224)),
    T.ToTensor(),
    T.Normalize([0.485,0.456,0.406],[0.229,0.224,0.225])
])

class AnalyzeReq(BaseModel):
    email: str
    image: str  # base64

app = FastAPI()

@app.get("/")
def root():
    return {"msg":"Backend running"}

@app.post("/analyze")
def analyze(data: AnalyzeReq):
    # decode image
    img_bytes = base64.b64decode(data.image)
    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    x = transform(img).unsqueeze(0)

    # extract embedding
    with torch.no_grad():
        feat = model.features(x)
        pooled = torch.mean(feat, dim=[2,3])  # (1,1280)

    # Fake calorie calculation (replace with LogMeal or nutrition DB)
    calories = float(torch.sum(pooled).item() % 500)

    log = {"email": data.email, "calories": calories}
    db.collection("meals").add(log)
    return log
