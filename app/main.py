from fastapi import FastAPI, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1 import auth, projects, analyses, dashboard
from app.core.config import settings

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Backend for Stackwise - Code analysis platform",
    version="1.0.0"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API v1
api_v1_router = APIRouter(prefix=settings.API_V1_STR)
api_v1_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_v1_router.include_router(projects.router, prefix="/projects", tags=["Projects"])
api_v1_router.include_router(analyses.router, tags=["Analyses"])
api_v1_router.include_router(dashboard.router, prefix="/dashboard", tags=["Dashboard"])

app.include_router(api_v1_router)

@app.get("/health")
async def health_check():
    return {"status": "healthy", "version": "1.0.0"}
