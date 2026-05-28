from fastapi import APIRouter

router = APIRouter(prefix="/siniestros", tags=["Siniestros"])


@router.get("")
def siniestros_module_status() -> dict[str, str]:
    return {"status": "ready", "module": "siniestros"}
