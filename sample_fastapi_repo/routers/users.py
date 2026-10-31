from fastapi import APIRouter

router = APIRouter()

@router.get("/")
def list_users():
    return []

@router.post("/")
async def create_user():
    return {}

@router.get("/{user_id}")
def get_user(user_id: int):
    return {}
