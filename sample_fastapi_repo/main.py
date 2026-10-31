from fastapi import FastAPI
from routers import users

app = FastAPI()

app.include_router(users.router, prefix="/users")

@app.get("/health")
def health_check():
    return {"status": "ok"}
