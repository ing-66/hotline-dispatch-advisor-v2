from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.api.routes import router
from backend.gateways.qdrant_adapter import KnowledgeGatewayError
from backend.gateways.real_llm import LLMGatewayError

app = FastAPI(title="热线派单顾问 V2", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:3000",
        "http://localhost:3000",
        "http://127.0.0.1:3001",
        "http://localhost:3001",
        "http://127.0.0.1:8899",
        "http://localhost:8899",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)

@app.exception_handler(KnowledgeGatewayError)
def knowledge_gateway_error(_: Request, exc: KnowledgeGatewayError):
    return JSONResponse(status_code=503, content={"error": "knowledge_unavailable", "detail": str(exc)})


@app.exception_handler(LLMGatewayError)
def llm_gateway_error(_: Request, exc: LLMGatewayError):
    return JSONResponse(status_code=503, content={"error": "llm_unavailable", "detail": str(exc)})
