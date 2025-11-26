import json
import logging
import time
import uvicorn
from fastapi import FastAPI, Request, Depends, HTTPException, status
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
import uuid # Added missing import for uuid

# Import our existing modules
from api_client import ApiClient
from token_manager import TokenManager
from utils import generate_request_body

from config import CONFIG

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.
    """
    # Startup logic can go here if needed
    yield
    # Shutdown logic
    logger.info("Closing API client...")
    await api_client.close()


# --- FastAPI Application Initialization ---
app = FastAPI(
    title="OpenAI Compatible Proxy",
    description="A proxy server that provides an OpenAI-compatible API.",
    version="1.0.0",
    lifespan=lifespan
)

# --- Singleton Instances ---
# These are created once when the app starts
token_manager = TokenManager()
api_client = ApiClient(token_manager)

# --- Pydantic Models for Request Validation ---
class ChatMessage(BaseModel):
    role: str
    content: Any  # Can be string or list of dicts for multimodal

    def get(self, name: str, default=None):
        """
        类似于 dict.get() 的方法，用于安全地获取实例属性。

        :param name: 属性的名称 (字符串)。
        :param default: 属性不存在时返回的值。
        :return: 属性值或默认值。
        """
        # 使用内置的 getattr() 函数进行安全查找
        return getattr(self, name, default)

class ChatCompletionRequest(BaseModel):
    messages: List[ChatMessage]
    model: str
    stream: bool = True
    tools: Optional[List[Dict[str, Any]]] = None
    # Include other OpenAI parameters with default values
    temperature: Optional[float] = Field(default=0.7, ge=0.0, le=2.0)
    top_p: Optional[float] = Field(default=1.0, ge=0.0, le=1.0)
    max_tokens: Optional[int] = Field(default=None)
    
# --- Security and Middleware ---

async def verify_api_key(request: Request):
    """Dependency to verify the API key."""
    if CONFIG.API_KEY:
        auth_header = request.headers.get('authorization')
        if not auth_header:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing API Key")
        
        provided_key = auth_header.split(" ")[-1]
        if provided_key != CONFIG.API_KEY:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API Key")

@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Middleware to log requests and their processing time."""
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    logger.info(
        f'{request.method} {request.url.path} - {response.status_code} ({process_time:.2f}s)'
    )
    return response

# --- API Endpoints ---

@app.get("/v1/models", dependencies=[Depends(verify_api_key)])
async def get_models():
    """Endpoint to get the list of available models."""
    try:
        models = await api_client.get_available_models()
        return JSONResponse(content=models)
    except Exception as e:
        logger.error(f"Failed to get models: {e}")
        raise HTTPException(status_code=500, detail=str(e))

async def stream_chat_generator(request: ChatCompletionRequest):
    """An async generator for streaming chat responses."""
    request_id = f"chatcmpl-{uuid.uuid4().hex}"
    created_time = int(time.time())
    has_tool_call = False

    try:
        # 1. Convert the OpenAI request to the antigravity format
        params = request.model_dump(exclude={"messages", "model", "stream", "tools"})
        antigravity_req_body = generate_request_body(
            token_manager, request.messages, request.model, params, request.tools
        )
        
        # 2. Stream the response from the API client
        async for chunk in api_client.generate_assistant_response(antigravity_req_body):
            if chunk['type'] == 'tool_calls':
                has_tool_call = True
                response_chunk = {
                    "id": request_id,
                    "object": "chat.completion.chunk",
                    "created": created_time,
                    "model": request.model,
                    "choices": [{"index": 0, "delta": {"tool_calls": chunk['tool_calls']}, "finish_reason": None}]
                }
            else: # 'text' or 'thinking'
                response_chunk = {
                    "id": request_id,
                    "object": "chat.completion.chunk",
                    "created": created_time,
                    "model": request.model,
                    "choices": [{"index": 0, "delta": {"content": chunk.get('content', '')}, "finish_reason": None}]
                }
            yield f"data: {json.dumps(response_chunk)}\n\n"

        # 3. Send the final chunk with the finish reason
        finish_reason = "tool_calls" if has_tool_call else "stop"
        final_chunk = {
            "id": request_id,
            "object": "chat.completion.chunk",
            "created": created_time,
            "model": request.model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": finish_reason}]
        }
        yield f"data: {json.dumps(final_chunk)}\n\n"

    except Exception as e:
        logger.error(f"Error during stream generation: {e}")
        error_chunk = {
            "id": request_id,
            "object": "chat.completion.chunk",
            "created": created_time,
            "model": request.model,
            "choices": [{"index": 0, "delta": {"content": f"Error: {e}"}, "finish_reason": "error"}]
        }
        yield f"data: {json.dumps(error_chunk)}\n\n"

    # 4. Send the [DONE] message to signify the end of the stream
    yield "data: [DONE]\n\n"

@app.post("/v1/chat/completions", dependencies=[Depends(verify_api_key)])
async def create_chat_completion(request: ChatCompletionRequest):
    """
    Main endpoint for chat completions. Supports both streaming and non-streaming.
    """
    if request.stream:
        return StreamingResponse(stream_chat_generator(request), media_type="text/event-stream")
    else:
        # Non-streaming logic
        try:
            full_content = ""
            tool_calls = []
            params = request.model_dump(exclude={"messages", "model", "stream", "tools"})
            antigravity_req_body = generate_request_body(
                token_manager, request.messages, request.model, params, request.tools
            )
            
            async for chunk in api_client.generate_assistant_response(antigravity_req_body):
                if chunk['type'] == 'tool_calls':
                    tool_calls = chunk['tool_calls']
                elif chunk['type'] == 'text':
                    full_content += chunk.get('content', '')
            
            message = {"role": "assistant", "content": full_content}
            if tool_calls:
                message["tool_calls"] = tool_calls

            finish_reason = "tool_calls" if tool_calls else "stop"
            
            return {
                "id": f"chatcmpl-{uuid.uuid4().hex}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": request.model,
                "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}]
            }

        except Exception as e:
            logger.error(f"Error during non-stream generation: {e}")
            raise HTTPException(status_code=500, detail=str(e))



if __name__ == "__main__":
    """Main entry point to run the server."""
    logger.info(f"Starting server on {CONFIG.HOST}:{CONFIG.PORT}")
    logger.info(f"API Key validation is {'ENABLED' if CONFIG.API_KEY else 'DISABLED'}")
    
    uvicorn.run(
        app,
        host=CONFIG.HOST,
        port=CONFIG.PORT
    )
