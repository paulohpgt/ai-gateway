from fastapi import FastAPI
from app.health import router as health_router

app = FastAPI(title="VisualExata AI Gateway")

app.include_router(health_router)

@app.get("/")
def root():
    return {"status": "ai-gateway running"}
