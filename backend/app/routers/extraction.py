"""Debug-only extraction test endpoint.

Citations:
- D-05: Registered ONLY when settings.debug is True (gated in create_app())
- D-06: Returns extraction result JSON — no DB persistence (developer surface only)

Test override pattern:
    Tests inject a mocked ExtractionService via:
        app.dependency_overrides[get_extraction_service] = lambda: mocked_service
    This mirrors the override_get_db pattern in test_health.py and means NO live
    OpenAI call is made during the test suite.

get_extraction_service() is the SOLE construction site for ExtractionService.
The openai_api_key flows from settings into AsyncOpenAI — never referenced in
service code (T-02-02).
"""
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from openai import AsyncOpenAI

from app.config import Settings, get_settings
from app.services.extraction import ExtractionResult, ExtractionService
from app.services.storage import LocalStorageBackend

router = APIRouter()


def get_extraction_service(
    settings: Settings = Depends(get_settings),
) -> ExtractionService:
    """Construct ExtractionService with all dependencies.

    This is the SOLE construction site for ExtractionService in production.
    Tests override this via:
        app.dependency_overrides[get_extraction_service] = lambda: mocked_service
    """
    openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    storage = LocalStorageBackend(root=settings.storage_path)
    return ExtractionService(
        openai_client=openai_client,
        storage=storage,
        settings=settings,
    )


@router.post("/test", response_model=ExtractionResult)
async def extraction_test(
    file: UploadFile = File(...),
    service: ExtractionService = Depends(get_extraction_service),
) -> ExtractionResult:
    """POST /extraction/test — developer surface for testing extraction pipeline.

    Accepts a multipart file upload, runs extraction, returns ExtractionResult JSON.
    No DB write (D-06). Registered only when settings.debug is True (D-05).

    curl example:
        curl -F file=@invoice.jpg http://localhost:8000/extraction/test
    """
    data = await file.read(10 * 1024 * 1024 + 1)  # read up to 10 MB + 1 byte
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File exceeds 10 MB limit")
    return await service.extract(
        image_bytes=data,
        filename=file.filename or "upload.bin",
    )
