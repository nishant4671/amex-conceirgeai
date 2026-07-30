from contextlib import asynccontextmanager
import logging
from typing import AsyncGenerator
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.security import mask_payload
from app.services.database import verify_db_connection
from app.services.redis_client import close_redis, init_redis, verify_redis_connection

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup and shutdown lifecycle events."""
    logger.info("Starting up Amex ConciergeAI Backend...")
    
    # 1. Initialize Redis
    await init_redis()
    
    # 2. Verify Database Connection
    db_ok = await verify_db_connection()
    if not db_ok:
        logger.warning("Database connection check failed on startup.")
    
    # 3. Verify Redis Connection
    redis_ok = await verify_redis_connection()
    if not redis_ok:
        logger.warning("Redis connection check failed on startup.")
        
    yield
    
    # Shutdown
    logger.info("Shutting down Amex ConciergeAI Backend...")
    await close_redis()


app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    lifespan=lifespan,
)

# Register disruptions router
from app.api.disruptions import router as disruptions_router
app.include_router(disruptions_router, prefix=settings.API_V1_STR)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Global exception handler with PII masking in logs
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # Safely mask request components before logging
    safe_query_params = mask_payload(dict(request.query_params))
    safe_url = mask_payload(str(request.url))
    
    logger.error(
        f"Unhandled exception occurred. URL: {safe_url} | "
        f"Params: {safe_query_params} | Error: {str(exc)}",
        exc_info=True
    )
    
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "An internal server error occurred. The incident has been logged securely.",
            "error_type": exc.__class__.__name__
        }
    )


@app.get("/health", status_code=status.HTTP_200_OK)
async def health_check() -> dict:
    """System health check endpoint checking DB and Redis."""
    db_status = await verify_db_connection()
    redis_status = await verify_redis_connection()
    
    overall_status = "healthy" if db_status and redis_status else "degraded"
    
    return {
        "status": overall_status,
        "environment": settings.ENVIRONMENT,
        "services": {
            "postgres": "connected" if db_status else "disconnected",
            "redis": "connected" if redis_status else "disconnected"
        }
    }
