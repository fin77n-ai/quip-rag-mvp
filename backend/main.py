from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .api import ingest, query, documents, rules, preprocess, tags, taxonomy, analytics, health

app = FastAPI(title="quip-rag", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ingest.router)
app.include_router(query.router)
app.include_router(documents.router)
app.include_router(rules.router)
app.include_router(preprocess.router)
app.include_router(tags.router)
app.include_router(taxonomy.router)
app.include_router(analytics.router)
app.include_router(health.router)
