from fastapi import FastAPI, Form
from fastapi.middleware.cors import CORSMiddleware
from database import engine, SessionLocal
import models

models.Base.metadata.create_all(bind=engine)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/contact")
async def contact(name: str = Form(...), email: str = Form(...), message: str = Form(...)):
    try:
        db = SessionLocal()

        new_contact = models.Contact(
            name=name,
            email=email,
            message=message
        )

        db.add(new_contact)
        db.commit()

        return {"message": "Message received ✅"}

    except Exception as e:
        return {"message": "Error occurred ❌"}