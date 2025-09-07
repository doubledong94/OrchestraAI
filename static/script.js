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
        this.userSelectedColumn = null; // 用户手动选择的列
        this.lastMessageColumn = null;  // 最后一次有消息的列
        this.isComposing = false; // 用于跟踪输入法状态
        
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
        
        // 输入法组合事件监听
        const humanInput = document.getElementById('human-input');
        
        humanInput.addEventListener('compositionstart', () => {
            this.isComposing = true;
            this.updateInputHint();
        });
        
        humanInput.addEventListener('compositionend', () => {
            this.isComposing = false;
            this.updateInputHint();
        });
        
        // 输入框回车发送 - 修复输入法冲突
        humanInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                if (this.isComposing) {
                    // 输入法组合中，只有 Shift+Enter 才发送
                    if (e.shiftKey) {
                        e.preventDefault();
                        this.sendHumanInput();
                    }
                } else {
                    // 非输入法状态，Enter 发送，Shift+Enter 换行
                    if (!e.shiftKey) {
                        e.preventDefault();
                        this.sendHumanInput();
                    }
                }
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
        
        // 列点击事件 - 手动设置活跃列
        document.querySelectorAll('.column').forEach(column => {
            column.addEventListener('click', (e) => {
                const role = column.getAttribute('data-role');
                if (role) {
                    this.setUserSelectedColumn(role);
                }
            });
        });
    }
    
    setupUI() {
        this.updateConnectionStatus();
        this.disableControls();
        this.updateInputHint();
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
        
        // 设置最新消息列
        this.setLastMessageColumn(messageData.role);
        
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
        
        // 检查是否为AI生成的消息（非human角色）且内容包含markdown标记
        if (messageData.role !== 'human' && this.containsMarkdown(messageData.content)) {
            // 渲染markdown内容并清理多余空白
            let parsedContent = marked.parse(messageData.content);
            // 移除HTML标签间的多余空白字符
            parsedContent = parsedContent.replace(/>\s+</g, '><').trim();
            contentDiv.innerHTML = parsedContent;
        } else {
            // 普通文本内容
            contentDiv.textContent = messageData.content;
        }
        
        const timestampDiv = document.createElement('div');
        timestampDiv.className = 'message-timestamp';
        timestampDiv.textContent = this.formatTimestamp(messageData.timestamp);
        
        messageDiv.appendChild(contentDiv);
        messageDiv.appendChild(timestampDiv);
        
        return messageDiv;
    }
    
    containsMarkdown(text) {
        // 检查文本是否包含常见的markdown标记
        const markdownPatterns = [
            /^#{1,6}\s/m,           // 标题
            /\*\*.*?\*\*/,          // 粗体
            /\*.*?\*/,              // 斜体
            /`.*?`/,                // 行内代码
            /```[\s\S]*?```/,       // 代码块
            /^\s*[-*+]\s/m,         // 列表
            /^\s*\d+\.\s/m,         // 有序列表
            /\[.*?\]\(.*?\)/,       // 链接
            /^\s*>\s/m,             // 引用
            /^\s*\|.*\|/m,          // 表格
            /---+/,                 // 分割线
        ];
        
        return markdownPatterns.some(pattern => pattern.test(text));
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
        
        // 检查是否为AI生成的消息（非human角色）且内容包含markdown标记
        if (messageData.role !== 'human' && this.containsMarkdown(messageData.content)) {
            // 渲染markdown内容并清理多余空白
            let parsedContent = marked.parse(messageData.content);
            // 移除HTML标签间的多余空白字符
            parsedContent = parsedContent.replace(/>\s+</g, '><').trim();
            contentDiv.innerHTML = parsedContent;
        } else {
            // 普通文本内容
            contentDiv.textContent = messageData.content;
        }
        
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
    
    setUserSelectedColumn(role) {
        this.userSelectedColumn = role;
        this.updateColumnLayout();
        
        // 添加用户选择动画
        const column = document.querySelector(`[data-role="${role}"]`);
        if (column) {
            column.classList.add('user-selected');
        }
    }
    
    setLastMessageColumn(role) {
        
        // 更新最新消息列
        this.lastMessageColumn = role;
        this.updateColumnLayout();
        
        // 添加最近活跃动画
        const column = document.querySelector(`[data-role="${role}"]`);
        if (column) {
            column.classList.add('recently-active');
            setTimeout(() => {
                column.classList.remove('recently-active');
            }, 2000);
        }
    }
    
    updateColumnLayout() {
        const container = document.querySelector('.columns-container');
        
        // 获取活跃的列
        const activeColumns = [];
        if (this.userSelectedColumn) activeColumns.push(this.userSelectedColumn);
        if (this.lastMessageColumn && this.lastMessageColumn !== this.userSelectedColumn) {
            activeColumns.push(this.lastMessageColumn);
        }
        
        // 清除所有活跃状态
        document.querySelectorAll('.column').forEach(column => {
            column.classList.remove('active', 'user-selected', 'message-active');
        });
        
        if (activeColumns.length > 0) {
            container.classList.add('has-active');
            
            // 设置活跃列的样式和布局
            if (activeColumns.length === 1) {
                container.setAttribute('data-active', activeColumns[0]);
                container.removeAttribute('data-dual-active');
            } else if (activeColumns.length === 2) {
                container.setAttribute('data-dual-active', `${activeColumns[0]}-${activeColumns[1]}`);
                container.removeAttribute('data-active');
            }
            
            // 为活跃列添加对应的CSS类
            if (this.userSelectedColumn) {
                const userColumn = document.querySelector(`[data-role="${this.userSelectedColumn}"]`);
                if (userColumn) {
                    userColumn.classList.add('active', 'user-selected');
                }
            }
            
            if (this.lastMessageColumn) {
                const messageColumn = document.querySelector(`[data-role="${this.lastMessageColumn}"]`);
                if (messageColumn) {
                    messageColumn.classList.add('active', 'message-active');
                }
            }
        } else {
            container.classList.remove('has-active');
            container.removeAttribute('data-active');
            container.removeAttribute('data-dual-active');
        }
    }
    
    updateInputHint() {
        const humanInput = document.getElementById('human-input');
        const sendBtn = document.getElementById('send-btn');
        const inputContainer = humanInput.closest('.input-container');
        
        // 移除之前的提示元素
        const existingHint = inputContainer.querySelector('.input-hint');
        if (existingHint) {
            existingHint.remove();
        }
        
        // 创建新的提示元素
        const hintElement = document.createElement('div');
        hintElement.className = 'input-hint';
        
        if (this.isComposing) {
            hintElement.textContent = '输入法组合中... (Shift+Enter 发送)';
            sendBtn.textContent = 'Shift+Enter 发送';
            hintElement.style.color = '#f59e0b';
        } else {
            hintElement.textContent = 'Enter 发送, Shift+Enter 换行';
            sendBtn.textContent = '发送 (Enter)';
            hintElement.style.color = '#666';
        }
        
        inputContainer.appendChild(hintElement);
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
    
    /* 输入提示样式 */
    .input-container {
        position: relative;
        padding-bottom: 25px;
    }
    
    .input-hint {
        position: absolute;
        bottom: 5px;
        left: 0;
        font-size: 12px;
        opacity: 0.7;
        transition: all 0.3s ease;
        pointer-events: none;
        font-style: italic;
    }
    
    .input-container:hover .input-hint,
    .input-container:focus-within .input-hint {
        opacity: 1;
    }
    
    /* 发送按钮动态文本样式 */
    #send-btn {
        transition: all 0.3s ease;
        min-width: 120px;
    }
    
    #send-btn:hover {
        background: linear-gradient(135deg, #3730a3, #6b21a8);
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
    
    /* Markdown content styles */
    .message-content h1,
    .message-content h2,
    .message-content h3,
    .message-content h4,
    .message-content h5,
    .message-content h6 {
        margin: 10px 0 5px 0;
        color: #1f2937;
        font-weight: 600;
    }
    
    .message-content h1 { font-size: 1.5em; }
    .message-content h2 { font-size: 1.3em; }
    .message-content h3 { font-size: 1.2em; }
    .message-content h4 { font-size: 1.1em; }
    .message-content h5 { font-size: 1em; }
    .message-content h6 { font-size: 0.9em; }
    
    .message-content p {
        margin: 8px 0;
        line-height: 1.5;
    }
    
    .message-content code {
        background: #f3f4f6;
        padding: 2px 4px;
        border-radius: 3px;
        font-family: 'Courier New', Courier, monospace;
        font-size: 0.9em;
        color: #dc2626;
    }
    
    .message-content pre {
        background: #1f2937;
        color: #f9fafb;
        padding: 12px;
        border-radius: 6px;
        overflow-x: auto;
        margin: 10px 0;
        font-family: 'Courier New', Courier, monospace;
        font-size: 0.9em;
        line-height: 1.4;
    }
    
    .message-content pre code {
        background: none;
        padding: 0;
        color: inherit;
        font-size: inherit;
    }
    
    .message-content blockquote {
        border-left: 4px solid #6b7280;
        margin: 10px 0;
        padding: 8px 16px;
        background: #f9fafb;
        font-style: italic;
        color: #4b5563;
    }
    
    .message-content ul,
    .message-content ol {
        margin: 8px 0;
        padding-left: 20px;
    }
    
    .message-content li {
        margin: 4px 0;
        line-height: 1.4;
    }
    
    .message-content table {
        border-collapse: collapse;
        width: 100%;
        margin: 10px 0;
        font-size: 0.9em;
    }
    
    .message-content th,
    .message-content td {
        border: 1px solid #d1d5db;
        padding: 8px 12px;
        text-align: left;
    }
    
    .message-content th {
        background: #f3f4f6;
        font-weight: 600;
    }
    
    .message-content hr {
        border: none;
        border-top: 2px solid #e5e7eb;
        margin: 15px 0;
    }
    
    .message-content a {
        color: #4f46e5;
        text-decoration: none;
    }
    
    .message-content a:hover {
        text-decoration: underline;
    }
    
    .message-content strong {
        font-weight: 600;
        color: #1f2937;
    }
    
    .message-content em {
        font-style: italic;
        color: #4b5563;
    }
    
    /* Timeline message markdown styles */
    .timeline-message-content h1,
    .timeline-message-content h2,
    .timeline-message-content h3,
    .timeline-message-content h4,
    .timeline-message-content h5,
    .timeline-message-content h6 {
        margin: 8px 0 4px 0;
        color: #1f2937;
        font-weight: 600;
    }
    
    .timeline-message-content h1 { font-size: 1.3em; }
    .timeline-message-content h2 { font-size: 1.2em; }
    .timeline-message-content h3 { font-size: 1.1em; }
    .timeline-message-content h4 { font-size: 1em; }
    .timeline-message-content h5 { font-size: 0.95em; }
    .timeline-message-content h6 { font-size: 0.9em; }
    
    .timeline-message-content p {
        margin: 6px 0;
        line-height: 1.4;
    }
    
    .timeline-message-content code {
        background: #f3f4f6;
        padding: 1px 3px;
        border-radius: 2px;
        font-family: 'Courier New', Courier, monospace;
        font-size: 0.85em;
        color: #dc2626;
    }
    
    .timeline-message-content pre {
        background: #1f2937;
        color: #f9fafb;
        padding: 8px;
        border-radius: 4px;
        overflow-x: auto;
        margin: 8px 0;
        font-family: 'Courier New', Courier, monospace;
        font-size: 0.8em;
        line-height: 1.3;
    }
    
    .timeline-message-content pre code {
        background: none;
        padding: 0;
        color: inherit;
        font-size: inherit;
    }
    
    .timeline-message-content blockquote {
        border-left: 3px solid #6b7280;
        margin: 6px 0;
        padding: 6px 12px;
        background: #f9fafb;
        font-style: italic;
        color: #4b5563;
        font-size: 0.9em;
    }
    
    .timeline-message-content ul,
    .timeline-message-content ol {
        margin: 6px 0;
        padding-left: 16px;
    }
    
    .timeline-message-content li {
        margin: 2px 0;
        line-height: 1.3;
        font-size: 0.9em;
    }
`;
document.head.appendChild(style);

// 初始化应用
document.addEventListener('DOMContentLoaded', () => {
    window.orchestraAI = new OrchestraAI();
});