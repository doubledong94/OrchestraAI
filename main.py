from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import json
import asyncio
import httpx
import os
from datetime import datetime
import uuid
from enum import Enum

app = FastAPI(title="OrchestraAI", description="Multi-AI Collaboration Platform")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class RoleType(str, Enum):
    HUMAN = "human"
    ETHER = "ether"
    PRODUCT_AI = "product_ai"
    ARCHITECT_AI = "architect_ai"
    INTERFACE_AI = "interface_ai"
    PROGRAMMER_AI = "programmer_ai"

class MessageType(str, Enum):
    USER_INPUT = "user_input"
    AI_RESPONSE = "ai_response"
    SYSTEM_INFO = "system_info"
    FILE_SAVED = "file_saved"
    ERROR = "error"

class Message(BaseModel):
    id: str
    role: RoleType
    message_type: MessageType
    content: str
    timestamp: datetime
    metadata: Optional[Dict[str, Any]] = None

class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"

class Task(BaseModel):
    id: str
    title: str
    description: str
    status: TaskStatus
    assignee: RoleType
    dependencies: List[str] = []
    created_at: datetime
    updated_at: datetime

class OrchestraState:
    def __init__(self):
        self.messages: List[Message] = []
        self.tasks: Dict[str, Task] = {}
        self.current_requirement: Optional[str] = None
        self.requirement_confirmed: bool = False
        self.websocket_connections: List[WebSocket] = []
        self.file_outputs: List[str] = []
        self.selected_model: str = "llama3.1:8b"

orchestra_state = OrchestraState()

AI_PROMPTS = {
    RoleType.PRODUCT_AI: """
你是产品AI，负责需求分析和产品设计。你的职责包括：
1. 收到人类的初始需求后，向人类提出具体的问题来明确需求细节
2. 问题要具体，最好是选择题，避免模糊问题
3. 明确需求的哪些方面是人类在乎的，哪些是无所谓的
4. 将确认的产品需求整理成文档并交给架构AI
5. 对于无法解决的问题要及时上报给人类

请用专业但易懂的语言与人类沟通，确保需求明确准确。
""",
    
    RoleType.ARCHITECT_AI: """
你是架构AI，负责技术架构设计和任务分解。你的职责包括：
1. 从代码实现角度将产品需求转换为具体的实现步骤
2. 确定哪些步骤能并行执行，哪些有依赖关系
3. 将有依赖关系的步骤交给接口AI设计接口
4. 设计文件目录结构，确定代码文件的存放位置
5. 将可执行的任务分配给程序员AI
6. 收集并拼接程序员AI的代码，通过以太保存文件

请确保架构设计合理，任务分解清晰，便于并行开发。
""",
    
    RoleType.INTERFACE_AI: """
你是接口AI，负责设计模块间的接口。你的职责包括：
1. 为有依赖关系的任务设计清晰的接口规范
2. 定义数据结构、函数签名、API规范
3. 确保接口设计符合最佳实践，易于维护和扩展
4. 提供详细的接口文档和使用示例

请确保接口设计规范、一致，便于不同模块的集成。
""",
    
    RoleType.PROGRAMMER_AI: """
你是程序员AI，负责具体的代码实现。你的职责包括：
1. 根据架构AI分配的任务实现具体代码
2. 遵循接口AI设计的接口规范
3. 编写高质量、可维护的代码
4. 包含必要的注释和错误处理
5. 确保代码符合最佳实践和编码规范

请编写清晰、高效的代码，注重代码质量和可读性。
"""
}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    orchestra_state.websocket_connections.append(websocket)
    
    try:
        await websocket.send_text(json.dumps({
            "type": "connection_established",
            "messages": [msg.model_dump(mode="json") for msg in orchestra_state.messages[-50:]]
        }))
        
        while True:
            data = await websocket.receive_text()
            message_data = json.loads(data)
            
            if message_data["type"] == "human_input":
                await handle_human_input(message_data["content"])
            elif message_data["type"] == "interrupt":
                await handle_human_interrupt(message_data["content"])
                
    except WebSocketDisconnect:
        orchestra_state.websocket_connections.remove(websocket)

async def broadcast_message(message: Message):
    orchestra_state.messages.append(message)
    
    disconnected = []
    for websocket in orchestra_state.websocket_connections:
        try:
            await websocket.send_text(json.dumps({
                "type": "new_message",
                "message": message.model_dump(mode="json")
            }))
        except:
            disconnected.append(websocket)
    
    for ws in disconnected:
        orchestra_state.websocket_connections.remove(ws)

async def handle_human_input(content: str):
    message = Message(
        id=str(uuid.uuid4()),
        role=RoleType.HUMAN,
        message_type=MessageType.USER_INPUT,
        content=content,
        timestamp=datetime.now()
    )
    
    await broadcast_message(message)
    
    if not orchestra_state.requirement_confirmed:
        await trigger_product_ai(content)
    else:
        await handle_confirmed_requirement_input(content)

async def handle_human_interrupt(content: str):
    message = Message(
        id=str(uuid.uuid4()),
        role=RoleType.HUMAN,
        message_type=MessageType.SYSTEM_INFO,
        content=f"【人类打断】{content}",
        timestamp=datetime.now()
    )
    
    await broadcast_message(message)

async def trigger_product_ai(user_input: str):
    prompt = f"""
{AI_PROMPTS[RoleType.PRODUCT_AI]}

用户需求：{user_input}

请分析这个需求并提出3-5个具体的澄清问题，帮助明确产品需求的细节。
"""
    
    response = await call_ollama_api(prompt, RoleType.PRODUCT_AI)
    if response:
        message = Message(
            id=str(uuid.uuid4()),
            role=RoleType.PRODUCT_AI,
            message_type=MessageType.AI_RESPONSE,
            content=response,
            timestamp=datetime.now()
        )
        await broadcast_message(message)

async def trigger_architect_ai(requirement: str):
    prompt = f"""
{AI_PROMPTS[RoleType.ARCHITECT_AI]}

产品需求：{requirement}

请分析这个需求并进行技术架构设计：
1. 分解为具体的实现步骤
2. 识别步骤间的依赖关系
3. 设计文件目录结构
4. 制定开发计划
"""
    
    response = await call_ollama_api(prompt, RoleType.ARCHITECT_AI)
    if response:
        message = Message(
            id=str(uuid.uuid4()),
            role=RoleType.ARCHITECT_AI,
            message_type=MessageType.AI_RESPONSE,
            content=response,
            timestamp=datetime.now()
        )
        await broadcast_message(message)

async def call_ollama_api(prompt: str, role: RoleType) -> Optional[str]:
    try:
        ether_message = Message(
            id=str(uuid.uuid4()),
            role=RoleType.ETHER,
            message_type=MessageType.SYSTEM_INFO,
            content=f"正在调用Ollama API为{role.value}生成响应...",
            timestamp=datetime.now()
        )
        await broadcast_message(ether_message)
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": orchestra_state.selected_model,
                    "prompt": prompt,
                    "stream": False
                },
                timeout=60.0
            )
            
            if response.status_code == 200:
                result = response.json()
                return result.get("response", "")
            else:
                error_msg = f"Ollama API调用失败: {response.status_code}"
                error_message = Message(
                    id=str(uuid.uuid4()),
                    role=RoleType.ETHER,
                    message_type=MessageType.ERROR,
                    content=error_msg,
                    timestamp=datetime.now()
                )
                await broadcast_message(error_message)
                return None
                
    except Exception as e:
        error_msg = f"调用Ollama API时发生错误: {str(e)}"
        error_message = Message(
            id=str(uuid.uuid4()),
            role=RoleType.ETHER,
            message_type=MessageType.ERROR,
            content=error_msg,
            timestamp=datetime.now()
        )
        await broadcast_message(error_message)
        return None

async def handle_confirmed_requirement_input(content: str):
    if "需求确认" in content or "开始开发" in content:
        orchestra_state.requirement_confirmed = True
        orchestra_state.current_requirement = content
        await trigger_architect_ai(content)

async def save_generated_code(filename: str, content: str):
    try:
        output_dir = "generated_code"
        os.makedirs(output_dir, exist_ok=True)
        
        file_path = os.path.join(output_dir, filename)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        orchestra_state.file_outputs.append(file_path)
        
        message = Message(
            id=str(uuid.uuid4()),
            role=RoleType.ETHER,
            message_type=MessageType.FILE_SAVED,
            content=f"代码文件已保存: {file_path}",
            timestamp=datetime.now(),
            metadata={"file_path": file_path}
        )
        await broadcast_message(message)
        
    except Exception as e:
        error_message = Message(
            id=str(uuid.uuid4()),
            role=RoleType.ETHER,
            message_type=MessageType.ERROR,
            content=f"保存文件失败: {str(e)}",
            timestamp=datetime.now()
        )
        await broadcast_message(error_message)

@app.get("/api/messages")
async def get_messages():
    return [msg.model_dump(mode="json") for msg in orchestra_state.messages]

@app.get("/api/tasks")
async def get_tasks():
    return list(orchestra_state.tasks.values())

@app.post("/api/save_code")
async def save_code_endpoint(filename: str, content: str):
    await save_generated_code(filename, content)
    return {"status": "success", "message": f"Code saved to {filename}"}

@app.get("/api/models")
async def get_available_models():
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get("http://localhost:11434/api/tags", timeout=10.0)
            if response.status_code == 200:
                data = response.json()
                models = [model["name"] for model in data.get("models", [])]
                return {"models": models, "selected": orchestra_state.selected_model}
            else:
                return {"models": ["llama3.1:8b"], "selected": orchestra_state.selected_model, "error": "Failed to fetch models"}
    except Exception as e:
        return {"models": ["llama3.1:8b"], "selected": orchestra_state.selected_model, "error": str(e)}

class ModelSelection(BaseModel):
    model_name: str

@app.post("/api/select_model")
async def select_model(model_data: ModelSelection):
    orchestra_state.selected_model = model_data.model_name
    return {"status": "success", "selected_model": model_data.model_name}

@app.get("/")
async def serve_frontend():
    return FileResponse("static/index.html")

app.mount("/static", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)