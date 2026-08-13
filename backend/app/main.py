from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import router
from .chemistry.encoding import install_opi_utf8_compatibility
from .config import configure_orca_environment, load_settings
from .jobs.manager import JobManager
from .fields import CubeFieldService
from .plots import PlotSamplingService
from .surfaces.service import SurfaceService
from .ao import AOAnalysisService


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings()
    # Install before diagnostics, jobs, or OPI parsing can touch ORCA text files.
    install_opi_utf8_compatibility()
    configure_orca_environment(settings.orca_path)
    app.state.jobs = JobManager(settings)
    app.state.fields = CubeFieldService()
    app.state.surfaces = SurfaceService(app.state.jobs, app.state.fields)
    app.state.plots = PlotSamplingService(app.state.jobs, app.state.fields)
    app.state.ao = AOAnalysisService(app.state.jobs, settings)
    yield
    app.state.jobs.executor.shutdown(wait=False, cancel_futures=True)


app = FastAPI(
    title="GeoORCA Local API",
    version="0.1.0",
    description="Coordinate-first editor backend. Calculations are local optimizations, not global minima.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Content-Type"],
)
app.include_router(router)


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "GeoORCA API", "docs": "/docs"}
