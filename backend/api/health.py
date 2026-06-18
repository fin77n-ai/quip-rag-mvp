from fastapi import APIRouter
from ..services import duck_lance_store
import lancedb
from ..config import settings

router = APIRouter()

@router.get("/health")
def health_check():
    services = {"status": "ok"}
    try:
        if duck_lance_store.is_enabled():
            db = lancedb.connect(str(settings.lance_dir))
            table = db.open_table("chunks")
            count = table.count_rows()
            services["vector_store"] = f"ok ({count} chunks)"
        else:
            services["vector_store"] = "disabled"
    except Exception as e:
        services["vector_store"] = f"error: {str(e)}"
    return services
