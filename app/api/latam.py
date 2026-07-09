from fastapi import APIRouter

router = APIRouter(prefix="/latam", tags=["latam"])


@router.get("/indices")
async def get_latam_indices():
    from app.data.latam import get_latam_indices
    return await get_latam_indices()
