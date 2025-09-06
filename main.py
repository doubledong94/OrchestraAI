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
import logging

app = FastAPI(title="OrchestraAI", description="Multi-AI Collaboration Platform")

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('orchestra_ai.log')
    ]
)
logger = logging.getLogger(__name__)

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
        self.max_context_messages: int = 20  # 最大上下文消息数量
        self.max_context_length: int = 8000  # 最大上下文字符长度
    
    def get_context_for_role(self, role: RoleType, max_messages: Optional[int] = None) -> str:
        """获取特定角色的对话上下文"""
        if max_messages is None:
            max_messages = self.max_context_messages
            
        # 获取最近的相关消息
        relevant_messages = []
        
        # 根据角色类型选择不同的上下文策略
        if role == RoleType.PRODUCT_AI:
            # 产品AI需要看到：人类输入 + 自己的历史回复
            for msg in self.messages[-max_messages:]:
                if (msg.role == RoleType.HUMAN or 
                    msg.role == RoleType.PRODUCT_AI):
                    relevant_messages.append(msg)
                    
        elif role == RoleType.ARCHITECT_AI:
            # 架构AI需要看到：人类输入 + 产品AI的分析 + 自己的历史回复
            for msg in self.messages[-max_messages:]:
                if (msg.role == RoleType.HUMAN or 
                    msg.role == RoleType.PRODUCT_AI or
                    msg.role == RoleType.ARCHITECT_AI):
                    relevant_messages.append(msg)
                    
        elif role == RoleType.INTERFACE_AI:
            # 接口AI需要看到：人类输入 + 产品AI分析 + 架构AI设计 + 自己的历史回复
            for msg in self.messages[-max_messages:]:
                if (msg.role == RoleType.HUMAN or 
                    msg.role == RoleType.PRODUCT_AI or
                    msg.role == RoleType.ARCHITECT_AI or
                    msg.role == RoleType.INTERFACE_AI):
                    relevant_messages.append(msg)
                    
        elif role == RoleType.PROGRAMMER_AI:
            # 程序员AI需要看到：全部相关消息（除了系统消息）
            for msg in self.messages[-max_messages:]:
                if msg.message_type != MessageType.SYSTEM_INFO:
                    relevant_messages.append(msg)
        else:
            # 默认情况：所有消息
            relevant_messages = self.messages[-max_messages:]
        
        # 构建上下文字符串，同时管理长度
        context_parts = []
        total_length = 0
        
        # 从最新消息开始，逐步添加到上下文中
        for msg in reversed(relevant_messages):
            role_name = self.get_role_display_name(msg.role)
            timestamp = msg.timestamp.strftime("%H:%M:%S")
            
            # 根据消息重要性决定截断策略
            if msg.role == RoleType.HUMAN:
                # 人类输入最重要，较少截断
                content = msg.content[:500] + "..." if len(msg.content) > 500 else msg.content
            elif msg.message_type == MessageType.AI_RESPONSE:
                # AI回复适中截断
                content = msg.content[:300] + "..." if len(msg.content) > 300 else msg.content
            else:
                # 系统消息较多截断
                content = msg.content[:150] + "..." if len(msg.content) > 150 else msg.content
            
            message_part = f"[{timestamp}] {role_name}: {content}"
            
            # 检查是否超过最大长度
            if total_length + len(message_part) > self.max_context_length:
                break
                
            context_parts.insert(0, message_part)  # 插入到开头保持时间顺序
            total_length += len(message_part) + 1  # +1 for newline
        
        context = "\n".join(context_parts)
        
        # 如果上下文为空，至少包含最后一条人类消息
        if not context and len(self.messages) > 0:
            for msg in reversed(self.messages):
                if msg.role == RoleType.HUMAN:
                    role_name = self.get_role_display_name(msg.role)
                    timestamp = msg.timestamp.strftime("%H:%M:%S")
                    content = msg.content[:500] + "..." if len(msg.content) > 500 else msg.content
                    context = f"[{timestamp}] {role_name}: {content}"
                    break
        
        return context
    
    def get_role_display_name(self, role: RoleType) -> str:
        """获取角色显示名称"""
        role_names = {
            RoleType.HUMAN: "人类用户",
            RoleType.ETHER: "系统",
            RoleType.PRODUCT_AI: "产品AI",
            RoleType.ARCHITECT_AI: "架构AI", 
            RoleType.INTERFACE_AI: "接口AI",
            RoleType.PROGRAMMER_AI: "程序员AI"
        }
        return role_names.get(role, role.value)

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
    logger.info(f"收到人类输入: {content[:100]}{'...' if len(content) > 100 else ''}")
    
    message = Message(
        id=str(uuid.uuid4()),
        role=RoleType.HUMAN,
        message_type=MessageType.USER_INPUT,
        content=content,
        timestamp=datetime.now()
    )
    
    await broadcast_message(message)
    
    if not orchestra_state.requirement_confirmed:
        logger.info("需求尚未确认，触发产品AI分析")
        await trigger_product_ai(content)
    else:
        logger.info("需求已确认，处理确认后的输入")
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
    logger.info(f"触发产品AI分析用户需求: {user_input[:50]}{'...' if len(user_input) > 50 else ''}")
    
    prompt = f"""
{AI_PROMPTS[RoleType.PRODUCT_AI]}

用户需求：{user_input}

请分析这个需求并提出3-5个具体的澄清问题，帮助明确产品需求的细节。
"""
    
    response = await call_ollama_api(prompt, RoleType.PRODUCT_AI)
    if response:
        logger.info(f"产品AI响应生成成功，长度: {len(response)}字符")
        message = Message(
            id=str(uuid.uuid4()),
            role=RoleType.PRODUCT_AI,
            message_type=MessageType.AI_RESPONSE,
            content=response,
            timestamp=datetime.now()
        )
        await broadcast_message(message)
    else:
        logger.error("产品AI响应生成失败")

async def trigger_architect_ai(requirement: str):
    logger.info(f"触发架构AI设计技术方案: {requirement[:50]}{'...' if len(requirement) > 50 else ''}")
    
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
        logger.info(f"架构AI方案设计成功，长度: {len(response)}字符")
        message = Message(
            id=str(uuid.uuid4()),
            role=RoleType.ARCHITECT_AI,
            message_type=MessageType.AI_RESPONSE,
            content=response,
            timestamp=datetime.now()
        )
        await broadcast_message(message)
    else:
        logger.error("架构AI方案设计失败")

async def call_ollama_api(prompt: str, role: RoleType, include_context: bool = True) -> Optional[str]:
    request_id = str(uuid.uuid4())[:8]
    logger.info(f"[{request_id}] 开始Ollama API调用 - 角色: {role.value}, 模型: {orchestra_state.selected_model}")
    
    try:
        ether_message = Message(
            id=str(uuid.uuid4()),
            role=RoleType.ETHER,
            message_type=MessageType.SYSTEM_INFO,
            content=f"正在调用Ollama API为{role.value}生成响应...",
            timestamp=datetime.now()
        )
        await broadcast_message(ether_message)
        
        # 构建完整的提示词（包含上下文）
        full_prompt = prompt
        if include_context and len(orchestra_state.messages) > 0:
            context = orchestra_state.get_context_for_role(role)
            if context:
                full_prompt = f"""以下是相关的对话历史：

{context}

---

基于以上对话历史，请回应以下请求：

{prompt}

请确保你的回应考虑到之前的对话内容，保持连贯性。"""
                
                context_stats = {
                    "total_messages": len(orchestra_state.messages),
                    "context_length": len(context),
                    "context_lines": len(context.split('\n')) if context else 0
                }
                logger.info(f"[{request_id}] 上下文统计: {json.dumps(context_stats, ensure_ascii=False)}")
        
        # 记录请求详情
        request_data = {
            "model": orchestra_state.selected_model,
            "prompt": full_prompt[:500] + "..." if len(full_prompt) > 500 else full_prompt,  # 截断长提示
            "stream": False
        }
        logger.info(f"[{request_id}] 请求数据: {json.dumps(request_data, ensure_ascii=False, indent=2)}")
        
        start_time = datetime.now()
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": orchestra_state.selected_model,
                    "prompt": full_prompt,
                    "stream": False
                },
                timeout=60.0
            )
            
            duration = (datetime.now() - start_time).total_seconds()
            logger.info(f"[{request_id}] API调用耗时: {duration:.2f}秒")
            
            if response.status_code == 200:
                result = response.json()
                response_text = result.get("response", "")
                
                # 记录响应详情
                logger.info(f"[{request_id}] 响应成功 - 长度: {len(response_text)}字符")
                logger.info(f"[{request_id}] 响应内容预览: {response_text[:300]}{'...' if len(response_text) > 300 else ''}")
                
                # 记录额外的响应信息
                if 'eval_count' in result:
                    logger.info(f"[{request_id}] Token统计 - 输出: {result.get('eval_count', 0)}, 输入: {result.get('prompt_eval_count', 0)}")
                if 'total_duration' in result:
                    total_duration_sec = result['total_duration'] / 1e9
                    logger.info(f"[{request_id}] 总处理时间: {total_duration_sec:.2f}秒")
                
                return response_text
            else:
                error_msg = f"Ollama API调用失败: {response.status_code}"
                logger.error(f"[{request_id}] {error_msg} - 响应内容: {response.text}")
                
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
        logger.error(f"[{request_id}] {error_msg}", exc_info=True)
        
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
    logger.info("正在获取可用的Ollama模型列表")
    try:
        start_time = datetime.now()
        async with httpx.AsyncClient() as client:
            response = await client.get("http://localhost:11434/api/tags", timeout=10.0)
            duration = (datetime.now() - start_time).total_seconds()
            
            if response.status_code == 200:
                data = response.json()
                models = [model["name"] for model in data.get("models", [])]
                logger.info(f"成功获取模型列表 (耗时 {duration:.2f}秒): {models}")
                logger.info(f"当前选中模型: {orchestra_state.selected_model}")
                return {"models": models, "selected": orchestra_state.selected_model}
            else:
                logger.error(f"获取模型列表失败 - HTTP {response.status_code}: {response.text}")
                return {"models": ["llama3.1:8b"], "selected": orchestra_state.selected_model, "error": "Failed to fetch models"}
    except Exception as e:
        logger.error(f"获取模型列表时发生错误: {str(e)}", exc_info=True)
        return {"models": ["llama3.1:8b"], "selected": orchestra_state.selected_model, "error": str(e)}

class ModelSelection(BaseModel):
    model_name: str

@app.post("/api/select_model")
async def select_model(model_data: ModelSelection):
    old_model = orchestra_state.selected_model
    new_model = model_data.model_name
    
    logger.info(f"模型切换请求: {old_model} -> {new_model}")
    
    orchestra_state.selected_model = new_model
    
    logger.info(f"模型已成功切换为: {new_model}")
    
    return {"status": "success", "selected_model": new_model}

class ContextSettings(BaseModel):
    max_context_messages: Optional[int] = None
    max_context_length: Optional[int] = None

@app.get("/api/context_settings")
async def get_context_settings():
    return {
        "max_context_messages": orchestra_state.max_context_messages,
        "max_context_length": orchestra_state.max_context_length,
        "current_messages_count": len(orchestra_state.messages)
    }

@app.post("/api/context_settings")
async def update_context_settings(settings: ContextSettings):
    if settings.max_context_messages is not None:
        orchestra_state.max_context_messages = settings.max_context_messages
        logger.info(f"更新最大上下文消息数: {settings.max_context_messages}")
    
    if settings.max_context_length is not None:
        orchestra_state.max_context_length = settings.max_context_length
        logger.info(f"更新最大上下文长度: {settings.max_context_length}")
    
    return {
        "status": "success",
        "max_context_messages": orchestra_state.max_context_messages,
        "max_context_length": orchestra_state.max_context_length
    }

@app.get("/")
async def serve_frontend():
    return FileResponse("static/index.html")

app.mount("/static", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    import uvicorn
    logger.info("启动OrchestraAI多AI协作平台")
    logger.info(f"默认选择模型: {orchestra_state.selected_model}")
    logger.info("服务器将在 http://0.0.0.0:8000 启动")
    uvicorn.run(app, host="0.0.0.0", port=8000)