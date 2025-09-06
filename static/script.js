class OrchestraAI {
    constructor() {
        this.ws = null;
        this.messages = [];
        this.isConnected = false;
        this.messageCounts = {
            human: 0,
            ether: 0,
            product_ai: 0,
            architect_ai: 0,
            interface_ai: 0,
            programmer_ai: 0
        };
        
        this.init();
    }
    
    init() {
        this.setupWebSocket();
        this.setupEventListeners();
        this.setupUI();
        this.loadAvailableModels();
    }
    
    setupWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws`;
        
        this.ws = new WebSocket(wsUrl);
        
        this.ws.onopen = () => {
            console.log('WebSocket连接已建立');
            this.isConnected = true;
            this.updateConnectionStatus();
            this.enableControls();
        };
        
        this.ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            this.handleWebSocketMessage(data);
        };
        
        this.ws.onclose = () => {
            console.log('WebSocket连接已关闭');
            this.isConnected = false;
            this.updateConnectionStatus();
            this.disableControls();
            
            // 尝试重连
            setTimeout(() => {
                console.log('尝试重新连接...');
                this.setupWebSocket();
            }, 3000);
        };
        
        this.ws.onerror = (error) => {
            console.error('WebSocket错误:', error);
        };
    }
    
    setupEventListeners() {
        // 发送按钮
        document.getElementById('send-btn').addEventListener('click', () => {
            this.sendHumanInput();
        });
        
        // 输入框回车发送
        document.getElementById('human-input').addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.sendHumanInput();
            }
        });
        
        // 紧急打断按钮
        document.getElementById('interrupt-btn').addEventListener('click', () => {
            this.showInterruptModal();
        });
        
        // 时间线视图切换
        document.getElementById('timeline-toggle').addEventListener('click', () => {
            this.toggleTimelineView();
        });
        
        document.getElementById('timeline-close').addEventListener('click', () => {
            this.hideTimelineView();
        });
        
        // 打断模态框
        document.getElementById('interrupt-confirm').addEventListener('click', () => {
            this.confirmInterrupt();
        });
        
        document.getElementById('interrupt-cancel').addEventListener('click', () => {
            this.hideInterruptModal();
        });
        
        // 点击模态框外部关闭
        document.getElementById('interrupt-modal').addEventListener('click', (e) => {
            if (e.target === document.getElementById('interrupt-modal')) {
                this.hideInterruptModal();
            }
        });
        
        document.getElementById('timeline-view').addEventListener('click', (e) => {
            if (e.target === document.getElementById('timeline-view')) {
                this.hideTimelineView();
            }
        });
        
        // 模型选择
        document.getElementById('model-select').addEventListener('change', (e) => {
            this.selectModel(e.target.value);
        });
    }
    
    setupUI() {
        this.updateConnectionStatus();
        this.disableControls();
    }
    
    handleWebSocketMessage(data) {
        switch (data.type) {
            case 'connection_established':
                if (data.messages && data.messages.length > 0) {
                    data.messages.forEach(msg => this.addMessage(msg));
                }
                break;
            case 'new_message':
                this.addMessage(data.message);
                break;
            default:
                console.log('未知消息类型:', data.type);
        }
    }
    
    addMessage(messageData) {
        this.messages.push(messageData);
        this.messageCounts[messageData.role]++;
        
        // 更新对应列的消息
        this.renderMessageInColumn(messageData);
        
        // 更新消息计数
        this.updateMessageCount(messageData.role);
        
        // 更新时间线视图（如果打开）
        if (!document.getElementById('timeline-view').classList.contains('hidden')) {
            this.renderTimelineView();
        }
        
        // 播放通知音效（可选）
        this.playNotificationSound();
    }
    
    renderMessageInColumn(messageData) {
        const container = document.getElementById(`messages-${messageData.role}`);
        if (!container) return;
        
        const messageElement = this.createMessageElement(messageData);
        container.appendChild(messageElement);
        
        // 滚动到底部
        container.scrollTop = container.scrollHeight;
        
        // 添加闪烁效果提示新消息
        const column = container.closest('.column');
        column.classList.add('new-message');
        setTimeout(() => {
            column.classList.remove('new-message');
        }, 1000);
    }
    
    createMessageElement(messageData) {
        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${messageData.message_type}`;
        
        const contentDiv = document.createElement('div');
        contentDiv.className = 'message-content';
        contentDiv.textContent = messageData.content;
        
        const timestampDiv = document.createElement('div');
        timestampDiv.className = 'message-timestamp';
        timestampDiv.textContent = this.formatTimestamp(messageData.timestamp);
        
        messageDiv.appendChild(contentDiv);
        messageDiv.appendChild(timestampDiv);
        
        return messageDiv;
    }
    
    updateMessageCount(role) {
        const countElement = document.querySelector(`[data-role="${role}"] .message-count`);
        if (countElement) {
            countElement.textContent = this.messageCounts[role];
        }
    }
    
    sendHumanInput() {
        const input = document.getElementById('human-input');
        const content = input.value.trim();
        
        if (!content || !this.isConnected) return;
        
        this.ws.send(JSON.stringify({
            type: 'human_input',
            content: content
        }));
        
        input.value = '';
    }
    
    showInterruptModal() {
        document.getElementById('interrupt-modal').classList.remove('hidden');
        document.getElementById('interrupt-input').focus();
    }
    
    hideInterruptModal() {
        document.getElementById('interrupt-modal').classList.add('hidden');
        document.getElementById('interrupt-input').value = '';
    }
    
    confirmInterrupt() {
        const input = document.getElementById('interrupt-input');
        const content = input.value.trim();
        
        if (!content || !this.isConnected) return;
        
        this.ws.send(JSON.stringify({
            type: 'interrupt',
            content: content
        }));
        
        this.hideInterruptModal();
    }
    
    toggleTimelineView() {
        const timelineView = document.getElementById('timeline-view');
        
        if (timelineView.classList.contains('hidden')) {
            timelineView.classList.remove('hidden');
            this.renderTimelineView();
        } else {
            timelineView.classList.add('hidden');
        }
    }
    
    hideTimelineView() {
        document.getElementById('timeline-view').classList.add('hidden');
    }
    
    renderTimelineView() {
        const container = document.getElementById('timeline-messages');
        container.innerHTML = '';
        
        // 按时间排序所有消息
        const sortedMessages = [...this.messages].sort((a, b) => 
            new Date(a.timestamp) - new Date(b.timestamp)
        );
        
        sortedMessages.forEach(messageData => {
            const messageElement = this.createTimelineMessageElement(messageData);
            container.appendChild(messageElement);
        });
        
        // 滚动到底部
        container.scrollTop = container.scrollHeight;
    }
    
    createTimelineMessageElement(messageData) {
        const messageDiv = document.createElement('div');
        messageDiv.className = 'timeline-message';
        
        const roleDiv = document.createElement('div');
        roleDiv.className = 'timeline-message-role';
        roleDiv.textContent = this.getRoleDisplayName(messageData.role);
        
        const contentDiv = document.createElement('div');
        contentDiv.className = 'timeline-message-content';
        contentDiv.textContent = messageData.content;
        
        const timeDiv = document.createElement('div');
        timeDiv.className = 'timeline-message-time';
        timeDiv.textContent = this.formatTimestamp(messageData.timestamp);
        
        contentDiv.appendChild(timeDiv);
        messageDiv.appendChild(roleDiv);
        messageDiv.appendChild(contentDiv);
        
        return messageDiv;
    }
    
    getRoleDisplayName(role) {
        const roleNames = {
            human: '👤 人类',
            ether: '⚡ 以太',
            product_ai: '🎯 产品AI',
            architect_ai: '🏗️ 架构AI',
            interface_ai: '🔌 接口AI',
            programmer_ai: '💻 程序员AI'
        };
        return roleNames[role] || role;
    }
    
    updateConnectionStatus() {
        const statusElement = document.getElementById('connection-status');
        
        if (this.isConnected) {
            statusElement.textContent = '已连接';
            statusElement.className = 'status connected';
        } else {
            statusElement.textContent = '断开连接';
            statusElement.className = 'status disconnected';
        }
    }
    
    enableControls() {
        document.getElementById('send-btn').disabled = false;
        document.getElementById('interrupt-btn').disabled = false;
        document.getElementById('human-input').disabled = false;
    }
    
    disableControls() {
        document.getElementById('send-btn').disabled = true;
        document.getElementById('interrupt-btn').disabled = true;
        document.getElementById('human-input').disabled = true;
    }
    
    formatTimestamp(timestamp) {
        const date = new Date(timestamp);
        return date.toLocaleTimeString('zh-CN', {
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
        });
    }
    
    playNotificationSound() {
        // 创建一个简单的通知音效
        try {
            const audioContext = new (window.AudioContext || window.webkitAudioContext)();
            const oscillator = audioContext.createOscillator();
            const gainNode = audioContext.createGain();
            
            oscillator.connect(gainNode);
            gainNode.connect(audioContext.destination);
            
            oscillator.frequency.setValueAtTime(800, audioContext.currentTime);
            oscillator.frequency.setValueAtTime(600, audioContext.currentTime + 0.1);
            
            gainNode.gain.setValueAtTime(0.1, audioContext.currentTime);
            gainNode.gain.exponentialRampToValueAtTime(0.01, audioContext.currentTime + 0.2);
            
            oscillator.start(audioContext.currentTime);
            oscillator.stop(audioContext.currentTime + 0.2);
        } catch (e) {
            // 静默处理音频错误
        }
    }
    
    async loadAvailableModels() {
        try {
            const response = await fetch('/api/models');
            const data = await response.json();
            
            const modelSelect = document.getElementById('model-select');
            
            // 清空现有选项
            modelSelect.innerHTML = '';
            
            // 添加可用模型
            if (data.models && data.models.length > 0) {
                data.models.forEach(model => {
                    const option = document.createElement('option');
                    option.value = model;
                    option.textContent = model;
                    if (model === data.selected) {
                        option.selected = true;
                    }
                    modelSelect.appendChild(option);
                });
            } else {
                // 如果没有可用模型，添加默认选项
                const option = document.createElement('option');
                option.value = 'llama3.1:8b';
                option.textContent = 'llama3.1:8b';
                modelSelect.appendChild(option);
            }
            
            if (data.error) {
                console.warn('获取模型列表时出现警告:', data.error);
            }
        } catch (error) {
            console.error('加载模型列表失败:', error);
            // 保持默认的 llama3.1:8b 选项
        }
    }
    
    async selectModel(modelName) {
        try {
            const response = await fetch('/api/select_model', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ model_name: modelName })
            });
            
            if (response.ok) {
                const data = await response.json();
                console.log('模型已切换为:', data.selected_model);
                
                // 可以添加一个提示消息
                this.showModelChangedNotification(modelName);
            } else {
                console.error('切换模型失败');
            }
        } catch (error) {
            console.error('切换模型时发生错误:', error);
        }
    }
    
    showModelChangedNotification(modelName) {
        // 创建一个临时通知
        const notification = document.createElement('div');
        notification.className = 'model-notification';
        notification.textContent = `已切换到模型: ${modelName}`;
        notification.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            background: #4f46e5;
            color: white;
            padding: 10px 20px;
            border-radius: 5px;
            z-index: 1000;
            font-size: 14px;
            box-shadow: 0 4px 15px rgba(0, 0, 0, 0.2);
            animation: slideIn 0.3s ease-out;
        `;
        
        document.body.appendChild(notification);
        
        // 3秒后移除通知
        setTimeout(() => {
            notification.style.animation = 'slideOut 0.3s ease-out';
            setTimeout(() => {
                document.body.removeChild(notification);
            }, 300);
        }, 3000);
    }
}

// 添加新消息闪烁效果的CSS
const style = document.createElement('style');
style.textContent = `
    .column.new-message {
        animation: newMessageFlash 1s ease-out;
    }
    
    @keyframes newMessageFlash {
        0%, 100% { transform: scale(1); }
        50% { transform: scale(1.02); box-shadow: 0 0 20px rgba(79, 70, 229, 0.5); }
    }
    
    .message {
        transition: all 0.3s ease;
    }
    
    .message:hover {
        transform: translateX(5px);
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.1);
    }
    
    .model-selector {
        display: flex;
        align-items: center;
        gap: 8px;
        margin-right: 20px;
    }
    
    .model-selector label {
        font-size: 14px;
        font-weight: 500;
    }
    
    .model-selector select {
        padding: 4px 8px;
        border: 1px solid #d1d5db;
        border-radius: 4px;
        background: white;
        font-size: 14px;
        min-width: 120px;
    }
    
    .model-selector select:focus {
        outline: none;
        border-color: #4f46e5;
        box-shadow: 0 0 0 2px rgba(79, 70, 229, 0.2);
    }
    
    @keyframes slideIn {
        from {
            transform: translateX(100%);
            opacity: 0;
        }
        to {
            transform: translateX(0);
            opacity: 1;
        }
    }
    
    @keyframes slideOut {
        from {
            transform: translateX(0);
            opacity: 1;
        }
        to {
            transform: translateX(100%);
            opacity: 0;
        }
    }
`;
document.head.appendChild(style);

// 初始化应用
document.addEventListener('DOMContentLoaded', () => {
    window.orchestraAI = new OrchestraAI();
});