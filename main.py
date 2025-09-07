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
        self.conversation_summaries: Dict[str, str] = {}  # 各阶段的对话总结
        self.summary_trigger_count: int = 6  # 每6条消息触发一次总结
    
    def get_context_for_role(self, role: RoleType, max_messages: Optional[int] = None) -> str:
        """获取特定角色的对话上下文（只使用总结）"""
        # 如果有总结，直接返回最新的总结
        if self.conversation_summaries:
            latest_summary = list(self.conversation_summaries.values())[-1]
            logger.info(f"为角色 {role.value} 提供总结上下文，总结长度: {len(latest_summary)}")
            return latest_summary
        else:
            # 如果没有总结，返回空字符串，让AI基于当前提示词工作
            logger.info(f"为角色 {role.value} 提供空上下文（无总结）")
            return ""
    
    def get_current_conversation_messages_for_role(self, role: RoleType) -> List[Message]:
        """获取当前对话段落的消息（自最后一次总结后）"""
        if not self.conversation_summaries:
            # 如果没有总结，返回所有消息
            return self.get_recent_messages_for_role(role, len(self.messages))
        
        # 找到最后一次总结后的消息
        last_summary_time = None
        if self.conversation_summaries:
            # 寻找最后一个总结生成时间的标记
            for msg in reversed(self.messages):
                if (msg.role == RoleType.ETHER and 
                    msg.message_type == MessageType.SYSTEM_INFO and
                    "已生成对话总结" in msg.content):
                    last_summary_time = msg.timestamp
                    break
        
        if last_summary_time:
            # 返回最后总结时间之后的消息
            current_messages = []
            for msg in self.messages:
                if msg.timestamp > last_summary_time:
                    current_messages.append(msg)
            return self.filter_messages_by_role_relevance(current_messages, role)
        else:
            # 如果没找到总结时间标记，返回最近的消息
            return self.get_recent_messages_for_role(role, self.max_context_messages)
    
    def filter_important_messages_for_role(self, messages: List[Message], role: RoleType, max_count: int) -> List[Message]:
        """筛选角色相关的重要消息"""
        # 按重要性排序：用户输入 > AI回复 > 系统消息 > 错误消息
        importance_order = {
            MessageType.USER_INPUT: 1,
            MessageType.AI_RESPONSE: 2,
            MessageType.SYSTEM_INFO: 3,
            MessageType.ERROR: 4,
            MessageType.FILE_SAVED: 5
        }
        
        role_messages = self.filter_messages_by_role_relevance(messages, role)
        
        # 按重要性和时间排序
        sorted_messages = sorted(role_messages, 
                               key=lambda x: (importance_order.get(x.message_type, 10), -x.timestamp.timestamp()))
        
        return sorted_messages[:max_count]
    
    def filter_messages_by_role_relevance(self, messages: List[Message], role: RoleType) -> List[Message]:
        """根据角色相关性过滤消息"""
        if role == RoleType.PRODUCT_AI:
            return [msg for msg in messages if msg.role in [RoleType.HUMAN, RoleType.PRODUCT_AI, RoleType.ETHER]]
        elif role == RoleType.ARCHITECT_AI:
            return [msg for msg in messages if msg.role in [RoleType.HUMAN, RoleType.PRODUCT_AI, RoleType.ARCHITECT_AI, RoleType.ETHER]]
        elif role == RoleType.INTERFACE_AI:
            return [msg for msg in messages if msg.role in [RoleType.HUMAN, RoleType.PRODUCT_AI, RoleType.ARCHITECT_AI, RoleType.INTERFACE_AI, RoleType.ETHER]]
        elif role == RoleType.PROGRAMMER_AI:
            return [msg for msg in messages if msg.message_type != MessageType.SYSTEM_INFO or msg.role == RoleType.ETHER]
        else:
            return messages

    def get_recent_messages_for_role(self, role: RoleType, max_count: int) -> List[Message]:
        """获取角色相关的最近消息"""
        relevant_messages = []
        
        # 根据角色类型选择不同的消息范围
        if role == RoleType.PRODUCT_AI:
            # 产品AI需要看到：人类输入 + 自己的历史回复
            for msg in reversed(self.messages):
                if (msg.role == RoleType.HUMAN or 
                    msg.role == RoleType.PRODUCT_AI):
                    relevant_messages.insert(0, msg)
                if len(relevant_messages) >= max_count:
                    break
                    
        elif role == RoleType.ARCHITECT_AI:
            # 架构AI需要看到：人类输入 + 产品AI的分析 + 自己的历史回复
            for msg in reversed(self.messages):
                if (msg.role == RoleType.HUMAN or 
                    msg.role == RoleType.PRODUCT_AI or
                    msg.role == RoleType.ARCHITECT_AI):
                    relevant_messages.insert(0, msg)
                if len(relevant_messages) >= max_count:
                    break
                    
        elif role == RoleType.INTERFACE_AI:
            # 接口AI需要看到：人类输入 + 产品AI分析 + 架构AI设计 + 自己的历史回复
            for msg in reversed(self.messages):
                if (msg.role == RoleType.HUMAN or 
                    msg.role == RoleType.PRODUCT_AI or
                    msg.role == RoleType.ARCHITECT_AI or
                    msg.role == RoleType.INTERFACE_AI):
                    relevant_messages.insert(0, msg)
                if len(relevant_messages) >= max_count:
                    break
                    
        elif role == RoleType.PROGRAMMER_AI:
            # 程序员AI需要看到：全部相关消息（除了系统消息）
            for msg in reversed(self.messages):
                if msg.message_type != MessageType.SYSTEM_INFO:
                    relevant_messages.insert(0, msg)
                if len(relevant_messages) >= max_count:
                    break
        else:
            # 默认情况：所有最近消息
            relevant_messages = self.messages[-max_count:]
        
        return relevant_messages

    def get_compressed_context_for_role(self, role: RoleType) -> str:
        """获取压缩的上下文（仅总结 + 最关键的最近消息）"""
        context_parts = []
        
        # 添加最新的总结
        if self.conversation_summaries:
            latest_summary = list(self.conversation_summaries.values())[-1]
            context_parts.append(f"【对话总结】{latest_summary}")
            context_parts.append("---")
        
        # 只添加最关键的最近消息（最后3-5条）
        key_messages = self.get_recent_messages_for_role(role, 5)
        for msg in key_messages[-3:]:  # 只取最后3条
            role_name = self.get_role_display_name(msg.role)
            timestamp = msg.timestamp.strftime("%H:%M:%S")
            context_parts.append(f"[{timestamp}] {role_name}: {msg.content}")
        
        return "\n".join(context_parts)
    
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

**第一阶段 - 需求收集**：
1. 收到人类的初始需求后，向人类提出具体的问题来明确需求细节
2. 问题要具体，最好是选择题，避免模糊问题
3. 明确需求的哪些方面是人类在乎的，哪些是无所谓的
4. 每次回复都要评估：是否已经收集到足够的信息来设计产品

**第二阶段 - 需求确认与总结**：
当你认为已经收集到足够信息时，必须：
1. 明确声明："基于我们的对话，我认为已经收集到足够的产品需求信息"
2. 提供完整的需求总结，包括：
   - 核心功能需求
   - 用户角色和权限
   - 关键业务流程
   - 技术要求和约束
   - 优先级说明
3. 询问用户："请确认以上需求总结是否完整准确？如果确认无误，我将把需求移交给架构AI进行技术设计。"

**重要原则**：
- 不要无限制地问问题，通常3-5轮对话应该能收集到基本信息
- 要主动判断何时信息已经足够进行产品设计
- 如果遇到无法解决的问题，及时上报给人类
- 用专业但易懂的语言与人类沟通

**回复格式指导**：
- 如果还需要更多信息，继续提问
- 如果信息足够，使用"【需求确认】"标记开始需求总结
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
    
    # 检查产品AI是否发出了需求确认信号
    if (message.role == RoleType.PRODUCT_AI and 
        message.message_type == MessageType.AI_RESPONSE and
        "【需求确认】" in message.content):
        
        logger.info("检测到产品AI需求确认信号，自动启动架构AI")
        
        # 标记需求已确认
        orchestra_state.requirement_confirmed = True
        orchestra_state.current_requirement = message.content
        
        # 发送流程转换系统消息
        transition_message = Message(
            id=str(uuid.uuid4()),
            role=RoleType.ETHER,
            message_type=MessageType.SYSTEM_INFO,
            content="✅ 产品AI已完成需求收集和总结，自动启动架构设计阶段...",
            timestamp=datetime.now()
        )
        orchestra_state.messages.append(transition_message)
        
        # 广播流程转换消息
        for websocket in orchestra_state.websocket_connections:
            try:
                await websocket.send_text(json.dumps({
                    "type": "new_message", 
                    "message": transition_message.model_dump(mode="json")
                }))
            except:
                pass
        
        # 自动触发架构AI（异步执行避免阻塞）
        import asyncio
        asyncio.create_task(auto_trigger_architect_ai(message.content))
    
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
    logger.info(f"收到人类输入: {content}")  # 完整记录
    
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
        logger.info("需求已确认，继续后续协作流程")
        # 需求已确认后，用户的输入可以用于指导后续的AI协作
        await handle_post_requirement_input(content)

def has_recent_product_confirmation() -> bool:
    """检查最近是否有产品AI的需求确认"""
    # 检查最近5条消息中是否有产品AI的需求确认
    recent_messages = orchestra_state.messages[-5:]
    for msg in recent_messages:
        if (msg.role == RoleType.PRODUCT_AI and 
            msg.message_type == MessageType.AI_RESPONSE and
            "【需求确认】" in msg.content):
            return True
    return False

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
    logger.info(f"触发产品AI分析用户需求: {user_input}")  # 完整记录
    
    # 统计产品AI和人类的对话轮数来判断是否应该开始总结
    product_ai_messages = sum(1 for msg in orchestra_state.messages 
                             if msg.role == RoleType.PRODUCT_AI and msg.message_type == MessageType.AI_RESPONSE)
    
    if product_ai_messages >= 2:  # 2轮对话后开始提醒总结
        additional_instruction = """

**重要提醒**: 这已经是我们的第{}轮对话了。请评估是否已经收集到足够的需求信息。如果是，请使用"【需求确认】"标记开始需求总结。""".format(product_ai_messages + 1)
    else:
        additional_instruction = ""
    
    prompt = f"""
{AI_PROMPTS[RoleType.PRODUCT_AI]}

用户输入：{user_input}

请根据用户的输入继续需求分析。如果这是初始需求，请提出3-5个具体的澄清问题。如果这是对之前问题的回答，请基于已有信息继续深入了解或考虑是否可以开始需求总结。{additional_instruction}
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
    logger.info(f"触发架构AI设计技术方案: {requirement}")  # 完整记录
    
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

async def call_ollama_api_for_summary(prompt: str) -> Optional[str]:
    """专门用于调用总结AI的函数，不触发总结更新"""
    request_id = str(uuid.uuid4())[:8]
    logger.info(f"[{request_id}] 开始调用总结AI - 模型: {orchestra_state.selected_model}")
    
    try:
        start_time = datetime.now()
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": orchestra_state.selected_model,
                    "prompt": prompt,
                    "stream": False
                },
                timeout=1000.0
            )
            
            duration = (datetime.now() - start_time).total_seconds()
            logger.info(f"[{request_id}] 总结API调用耗时: {duration:.2f}秒")
            
            if response.status_code == 200:
                result = response.json()
                response_text = result.get("response", "")
                
                logger.info(f"[{request_id}] 总结生成成功，长度: {len(response_text)}字符")
                return response_text
            else:
                error_msg = f"总结AI调用失败: {response.status_code}"
                logger.error(f"[{request_id}] {error_msg}")
                return None
                
    except Exception as e:
        error_msg = f"调用总结AI时发生错误: {str(e)}"
        logger.error(f"[{request_id}] {error_msg}", exc_info=True)
        return None

async def call_ollama_api(prompt: str, role: RoleType, include_context: bool = True) -> Optional[str]:
    request_id = str(uuid.uuid4())[:8]
    logger.info(f"[{request_id}] 开始Ollama API调用 - 角色: {role.value}, 模型: {orchestra_state.selected_model}")
    
    try:
        # 如果是有角色的AI（不是ETHER总结AI），先生成/更新总结
        if role != RoleType.ETHER and len(orchestra_state.messages) > 0:
            await ensure_summary_updated()
        
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
        
        # 记录Ollama输入
        logger.info(f"[{request_id}] ===== OLLAMA输入 =============================")
        logger.info(f"[{request_id}] 模型: {orchestra_state.selected_model}")
        logger.info(f"[{request_id}] 输入Prompt: {full_prompt}")
        logger.info(f"[{request_id}] ================================================")
        
        start_time = datetime.now()
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": orchestra_state.selected_model,
                    "prompt": full_prompt,
                    "stream": False
                },
                timeout=1000.0
            )
            
            duration = (datetime.now() - start_time).total_seconds()
            logger.info(f"[{request_id}] API调用耗时: {duration:.2f}秒")
            
            if response.status_code == 200:
                result = response.json()
                response_text = result.get("response", "")
                
                # 记录响应详情（完整版本）
                logger.info(f"[{request_id}] ===== OLLAMA输出 =============================")
                logger.info(f"[{request_id}] 响应长度: {len(response_text)}字符")
                logger.info(f"[{request_id}] 输出内容: {response_text}")
                logger.info(f"[{request_id}] ================================================")
                
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
    """处理需求确认阶段的用户输入（已废弃，保留向后兼容）"""
    if "需求确认" in content or "开始开发" in content or "确认" in content:
        orchestra_state.requirement_confirmed = True
        orchestra_state.current_requirement = content
        
        # 发送确认消息
        confirmation_message = Message(
            id=str(uuid.uuid4()),
            role=RoleType.ETHER,
            message_type=MessageType.SYSTEM_INFO,
            content="✅ 需求已确认！正在启动架构设计阶段...",
            timestamp=datetime.now()
        )
        await broadcast_message(confirmation_message)
        
        # 获取产品AI的需求总结作为架构设计的输入
        requirement_summary = extract_requirement_summary()
        await trigger_architect_ai(requirement_summary or content)

async def handle_post_requirement_input(content: str):
    """处理需求确认后的用户输入"""
    logger.info(f"需求确认后的用户输入: {content}")  # 完整记录
    
    # 用户可能想要：
    # 1. 修改需求
    # 2. 指导当前AI的工作
    # 3. 询问进度
    # 4. 打断当前流程
    
    if any(keyword in content for keyword in ["修改", "更改", "重新", "不对"]):
        # 用户想要修改需求，重置状态
        logger.info("用户要求修改需求，重置协作状态")
        
        reset_message = Message(
            id=str(uuid.uuid4()),
            role=RoleType.ETHER,
            message_type=MessageType.SYSTEM_INFO,
            content="🔄 检测到需求修改请求，重置协作状态，重新开始需求收集...",
            timestamp=datetime.now()
        )
        await broadcast_message(reset_message)
        
        # 重置状态
        orchestra_state.requirement_confirmed = False
        orchestra_state.current_requirement = None
        
        # 重新触发产品AI
        await trigger_product_ai(content)
        
    else:
        # 用户的指导意见，可以传递给当前活跃的AI角色
        guidance_message = Message(
            id=str(uuid.uuid4()),
            role=RoleType.ETHER,
            message_type=MessageType.SYSTEM_INFO,
            content=f"📝 用户指导意见已记录: {content}",
            timestamp=datetime.now()
        )
        await broadcast_message(guidance_message)


def get_messages_since_last_summary() -> List[Message]:
    """获取自上次总结后的所有消息"""
    if not orchestra_state.conversation_summaries:
        return orchestra_state.messages
    
    # 找到最后一次总结的时间标记
    last_summary_time = None
    for msg in reversed(orchestra_state.messages):
        if (msg.role == RoleType.ETHER and 
            msg.message_type == MessageType.SYSTEM_INFO and
            "已生成对话总结" in msg.content):
            last_summary_time = msg.timestamp
            break
    
    if last_summary_time:
        return [msg for msg in orchestra_state.messages if msg.timestamp > last_summary_time]
    else:
        return orchestra_state.messages

def is_conversation_endpoint(message: Message) -> bool:
    """判断是否是对话结束点"""
    # 对话结束的标志：
    # 1. 产品AI发出需求确认
    # 2. 架构AI完成技术方案设计
    # 3. 程序员AI完成代码实现
    # 4. 用户发出明确的结束指令
    # 5. 出现错误消息后
    # 6. 文件保存完成后
    
    if message.role == RoleType.PRODUCT_AI and "【需求确认】" in message.content:
        logger.info("检测到产品AI需求确认，标记为对话结束点")
        return True
    
    if message.role == RoleType.ARCHITECT_AI and any(keyword in message.content for keyword in ["技术方案设计完成", "架构设计完成", "开发计划制定完成"]):
        logger.info("检测到架构AI完成设计，标记为对话结束点")
        return True
    
    if message.role == RoleType.PROGRAMMER_AI and any(keyword in message.content for keyword in ["代码实现完成", "程序开发完成", "代码编写完成"]):
        logger.info("检测到程序员AI完成实现，标记为对话结束点")
        return True
    
    if message.role == RoleType.HUMAN and any(keyword in message.content for keyword in ["结束", "完成", "停止", "谢谢", "好的", "OK", "ok"]):
        logger.info("检测到用户结束指令，标记为对话结束点")
        return True
    
    if message.message_type == MessageType.ERROR:
        logger.info("检测到错误消息，标记为对话结束点")
        return True
    
    if message.message_type == MessageType.FILE_SAVED:
        logger.info("检测到文件保存完成，标记为对话结束点")
        return True
    
    # 检查最近几条消息，如果没有新的AI响应（超过30秒），也视为对话结束
    if len(orchestra_state.messages) >= 3:
        recent_messages = orchestra_state.messages[-3:]
        last_ai_response = None
        for msg in reversed(recent_messages):
            if msg.message_type == MessageType.AI_RESPONSE:
                last_ai_response = msg
                break
        
        if last_ai_response:
            time_since_last_ai = (datetime.now() - last_ai_response.timestamp).total_seconds()
            if time_since_last_ai > 30:  # 30秒无AI响应
                logger.info(f"最后AI响应已过去{time_since_last_ai}秒，标记为对话结束点")
                return True
    
    return False

def extract_requirement_summary() -> Optional[str]:
    """提取产品AI的需求总结"""
    # 从最近的消息中寻找产品AI的需求确认消息
    for msg in reversed(orchestra_state.messages):
        if (msg.role == RoleType.PRODUCT_AI and 
            msg.message_type == MessageType.AI_RESPONSE and
            "【需求确认】" in msg.content):
            return msg.content
    return None

async def auto_trigger_architect_ai(requirement_summary: str):
    """自动触发架构AI的异步函数"""
    try:
        # 给用户一点时间看到流程转换消息
        await asyncio.sleep(1)
        
        logger.info("自动触发架构AI开始技术设计")
        await trigger_architect_ai(requirement_summary)
        
    except Exception as e:
        logger.error(f"自动触发架构AI时发生错误: {str(e)}")
        
        # 发送错误消息
        error_message = Message(
            id=str(uuid.uuid4()),
            role=RoleType.ETHER,
            message_type=MessageType.ERROR,
            content=f"❌ 自动启动架构AI时发生错误: {str(e)}",
            timestamp=datetime.now()
        )
        await broadcast_message(error_message)

async def ensure_summary_updated():
    """确保总结是最新的，如果需要则生成新总结"""
    messages_since_last_summary = get_messages_since_last_summary()
    
    # 如果没有总结，或自上次总结后有新消息，则生成新总结
    if not orchestra_state.conversation_summaries or len(messages_since_last_summary) > 0:
        logger.info("检测到需要更新总结，开始生成...")
        await generate_conversation_summary()

async def generate_conversation_summary():
    """生成对话总结"""
    try:
        if len(orchestra_state.messages) < 4:  # 消息太少不需要总结
            return
            
        logger.info("开始生成对话总结")
        
        # 获取当前对话段落的所有消息（自上次总结后的所有消息）
        if orchestra_state.conversation_summaries:
            # 找到最后一次总结后的所有消息
            last_summary_time = None
            for msg in reversed(orchestra_state.messages):
                if (msg.role == RoleType.ETHER and 
                    msg.message_type == MessageType.SYSTEM_INFO and
                    "已生成对话总结" in msg.content):
                    last_summary_time = msg.timestamp
                    break
            
            if last_summary_time:
                current_conversation = [msg for msg in orchestra_state.messages if msg.timestamp > last_summary_time]
            else:
                current_conversation = orchestra_state.messages[-20:]  # 如果找不到标记，使用最近20条
        else:
            # 第一次总结，使用所有消息
            current_conversation = orchestra_state.messages
        
        # 如果消息太少，不生成总结
        if len(current_conversation) < 3:
            logger.info(f"当前对话段落消息太少({len(current_conversation)}条)，跳过总结")
            return
        
        recent_messages = current_conversation
        
        # 构建总结提示词，过滤掉以太(系统)消息
        messages_text = []
        for msg in recent_messages:
            # 跳过以太(系统)的消息，只保留实际对话
            if msg.role == RoleType.ETHER:
                continue
            role_name = orchestra_state.get_role_display_name(msg.role)
            timestamp = msg.timestamp.strftime("%H:%M:%S")
            messages_text.append(f"[{timestamp}] {role_name}: {msg.content}")
        
        # 检查是否有之前的总结，如果有，则生成增量总结
        previous_summary = ""
        if orchestra_state.conversation_summaries:
            latest_summary = list(orchestra_state.conversation_summaries.values())[-1]
            previous_summary = f"""
之前的对话总结：
{latest_summary}

---
"""

        summary_prompt = f"""
你是一个专业的对话总结AI，需要为多AI协作系统生成简洁有效的对话总结。这个总结将作为AI对话时的上下文，而不是完整的聊天历史。

{previous_summary}
本次新增对话内容：
{chr(10).join(messages_text)}

总结目标：
生成一个简洁但信息完整的总结，用于替代完整的聊天历史，让AI能够理解：
1. **当前项目状态**：需求确认情况、设计进展、开发状态
2. **关键技术决策**：架构选择、技术栈、设计原则
3. **重要约束条件**：用户要求、技术限制、业务规则
4. **待解决问题**：当前阻塞点、需要澄清的问题
5. **下一步行动**：明确的后续任务和责任分工

总结要求：
- 保持客观事实，避免冗余描述
- 突出核心信息，忽略客套话
- 使用清晰的结构化格式
- 确保AI能基于此总结继续协作
- 总结长度控制在500字以内

请生成结构化总结：
"""
        
        # 调用AI生成总结（总结AI需要特殊的上下文处理）
        summary = await call_ollama_api_for_summary(summary_prompt)
        
        if summary:
            # 保存总结
            summary_key = f"summary_{len(orchestra_state.messages)}"
            orchestra_state.conversation_summaries[summary_key] = summary
            
            logger.info(f"对话总结生成成功，保存为 {summary_key}")
            logger.info(f"总结内容: {summary}")
            
            # 将总结内容作为ETHER消息展示在界面上
            summary_display_message = Message(
                id=str(uuid.uuid4()),
                role=RoleType.ETHER,
                message_type=MessageType.SYSTEM_INFO,
                content=f"📋 **对话总结**\n\n{summary}",
                timestamp=datetime.now()
            )
            # 注意：这里不能调用broadcast_message，会导致递归
            orchestra_state.messages.append(summary_display_message)
            
            # 直接发送给客户端展示总结内容
            for websocket in orchestra_state.websocket_connections:
                try:
                    await websocket.send_text(json.dumps({
                        "type": "new_message",
                        "message": summary_display_message.model_dump(mode="json")
                    }))
                except:
                    pass
                    
        else:
            logger.error("对话总结生成失败")
            
    except Exception as e:
        logger.error(f"生成对话总结时发生错误: {str(e)}", exc_info=True)

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
            response = await client.get("http://localhost:11434/api/tags", timeout=1000.0)
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

class SummarySettings(BaseModel):
    summary_trigger_count: Optional[int] = None

@app.get("/api/summary_settings")
async def get_summary_settings():
    return {
        "summary_trigger_count": orchestra_state.summary_trigger_count,
        "summaries_count": len(orchestra_state.conversation_summaries),
        "current_messages_count": len(orchestra_state.messages)
    }

@app.post("/api/summary_settings") 
async def update_summary_settings(settings: SummarySettings):
    if settings.summary_trigger_count is not None:
        orchestra_state.summary_trigger_count = settings.summary_trigger_count
        logger.info(f"更新总结触发频率: 每{settings.summary_trigger_count}条消息")
    
    return {
        "status": "success",
        "summary_trigger_count": orchestra_state.summary_trigger_count
    }

@app.get("/api/summaries")
async def get_conversation_summaries():
    return {
        "summaries": orchestra_state.conversation_summaries,
        "count": len(orchestra_state.conversation_summaries)
    }

@app.post("/api/generate_summary")
async def manual_generate_summary():
    """手动触发对话总结"""
    if len(orchestra_state.messages) < 3:
        return {"status": "error", "message": "消息数量太少，无需总结"}
    
    import asyncio
    asyncio.create_task(generate_conversation_summary())
    
    return {"status": "success", "message": "已开始生成对话总结"}

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