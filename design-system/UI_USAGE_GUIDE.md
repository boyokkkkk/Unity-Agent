# Unity Agent Console - 像素艺术 UI 使用指南

## 快速启动

### 1. 启动前端开发服务器
```powershell
cd frontend
npm run dev
```

访问：http://localhost:5173

### 2. 启动后端服务
```powershell
# 在项目根目录
python -m uvicorn src.game_agent.baseline_cli:app --reload
```

## 设计系统文件说明

### 核心样式文件
```
frontend/src/
├── pixel-theme.css       # 🎨 设计系统核心
│   ├── CSS 变量定义（颜色、间距、阴影）
│   ├── 基础组件样式（按钮、卡片、输入框）
│   ├── 字体系统配置
│   └── 响应式断点
│
├── pixel-effects.css     # ✨ 8-bit 视觉效果
│   ├── 闪烁光标动画
│   ├── CRT 扫描线效果
│   ├── 像素粒子动画
│   ├── 街机发光效果
│   └── 像素边框动画
│
├── pixel-workspace.css   # 🏢 工作台布局
│   ├── 侧边栏样式（街机柜式）
│   ├── 导航系统
│   ├── 项目列表
│   ├── 状态指示器
│   └── 移动端响应式
│
└── pixel-home.css        # 🏠 主页样式
    ├── 英雄区
    ├── 统计卡片（街机分数牌）
    ├── 像素办公室场景
    ├── Agent 工作站
    ├── 活动面板
    └── 响应式布局
```

## 色彩使用指南

### 主题色彩
```css
/* 主要交互元素 */
--color-primary: #7C3AED    /* 导航、链接、主要按钮 */
--color-accent: #EC4899     /* CTA、强调、运行状态 */
--color-secondary: #6366F1  /* 辅助色、Agent 身体 */

/* 状态色彩 */
成功/在线：#10B981 (绿色)
警告/待处理：#F59E0B (橙色)
错误/离线：#DC2626 (红色)

/* 背景和文本 */
--color-background: #FAF5FF  /* 页面背景 */
--color-foreground: #0F172A  /* 文本颜色 */
--color-muted: #F7F3FD       /* 次要背景 */
--color-border: #EFE7FC      /* 边框颜色 */
```

### 应用场景
- **紫色系**：品牌识别、导航、主要操作
- **粉色系**：高优先级操作、运行中状态、特殊强调
- **中性色**：内容展示、说明文本、辅助信息

## 组件使用示例

### 按钮组件
```tsx
// 主要按钮 - 高优先级操作
<button className="button-primary">
  <Icon name="plus" size={16} />
  创建任务
</button>

// 次要按钮 - 常规操作
<button className="button-secondary">
  查看详情
  <Icon name="arrow" size={15} />
</button>

// 图标按钮 - 工具操作
<button className="icon-button" aria-label="刷新">
  <Icon name="refresh" />
</button>
```

### 卡片组件
```tsx
// 标准卡片
<div className="panel">
  <div className="panel-heading">
    <h2>标题</h2>
  </div>
  <div className="panel-body">
    内容区域
  </div>
</div>

// 带悬停效果的卡片
<div className="card">
  内容会有 3D 抬起效果
</div>
```

### 状态徽章
```tsx
// 运行中状态
<span className="status-badge status-live">
  <span className="status-dot" />
  运行中
</span>

// 成功状态
<span className="status-badge status-success">
  <span className="status-dot" />
  已完成
</span>

// 待处理状态
<span className="status-badge status-warning">
  <span className="status-dot" />
  待处理
</span>
```

### 输入框
```tsx
<div>
  <label className="field-label">
    任务描述
    <span>必填</span>
  </label>
  <textarea 
    className="input"
    placeholder="描述你想要 Agent 完成的任务..."
  />
</div>
```

## 特殊效果应用

### 闪烁效果（运行状态）
```tsx
<span className="status-badge status-live is-pulsing">
  <span className="status-dot" />
  Agent 工作中
</span>
```

### 光标闪烁
```tsx
<span className="cursor-blink">正在输入</span>
```

### CRT 屏幕效果
```tsx
<div className="crt-screen">
  <div className="scanlines">
    内容会有扫描线效果
  </div>
</div>
```

### 像素网格背景
```tsx
<div className="pixel-grid">
  内容会有网格背景
</div>
```

## 响应式设计

### 断点说明
```css
/* 小手机 */
@media (max-width: 375px) {
  /* 最小化间距，单列布局 */
}

/* 平板和大手机 */
@media (max-width: 768px) {
  /* 侧边栏变抽屉，网格变单列 */
}

/* 笔记本电脑 */
@media (max-width: 1024px) {
  /* 网格从 4 列变 2 列 */
}

/* 桌面（默认） */
@media (min-width: 1440px) {
  /* 最大宽度约束，居中显示 */
}
```

### 移动端适配特点
- 侧边栏自动隐藏，通过汉堡菜单打开
- 统计卡片从 4 列变为 1 列堆叠
- 工作站网格从 4 列变为 1 列
- 触摸友好的按钮尺寸（最小 48x48px）

## 可访问性功能

### 键盘导航
- 所有交互元素支持 Tab 键导航
- 焦点状态有明显的 4px 虚线外框
- Enter/Space 键可激活按钮

### 屏幕阅读器
- 使用语义化 HTML（nav, section, article）
- aria-label 提供描述性标签
- 装饰性图标使用 aria-hidden

### 减少动画
```css
@media (prefers-reduced-motion: reduce) {
  /* 所有动画缩短为 0.01ms */
}
```

## 自定义和扩展

### 添加新组件
1. 在相应的 CSS 文件中添加样式
2. 遵循像素网格对齐（4px 的倍数）
3. 使用 CSS 变量保持一致性
4. 添加响应式断点

### 修改颜色
1. 编辑 `pixel-theme.css` 中的 CSS 变量
2. 所有组件会自动更新
3. 保持足够的对比度（>4.5:1）

### 添加动画
1. 使用 `steps()` 而非 `ease` 实现帧动画
2. 动画时长建议：0.3-1.5s
3. 添加 `@media (prefers-reduced-motion)` 支持

## 常见问题

### Q: 字体没有加载？
A: 检查 `index.html` 是否包含 Google Fonts 链接：
```html
<link href="https://fonts.googleapis.com/css2?family=Press+Start+2P&family=VT323&display=swap" rel="stylesheet">
```

### Q: 样式没有生效？
A: 检查 `main.tsx` 中的导入顺序：
```tsx
// 像素主题需要在原有样式之前导入
import "./pixel-theme.css";
import "./pixel-effects.css";
import "./pixel-workspace.css";
import "./pixel-home.css";
```

### Q: 移动端侧边栏无法打开？
A: 确保 `WorkspaceLayout.tsx` 中的 mobile-menu 和 nav-backdrop 正常工作。

### Q: 动画太快/太慢？
A: 在 `pixel-effects.css` 中调整 animation-duration。

## 性能优化建议

### 字体加载
- 使用 `preconnect` 加速 Google Fonts
- 考虑使用 `font-display: swap`

### CSS 优化
- 避免深层嵌套选择器
- 使用 CSS 变量减少重复
- 动画优先使用 transform 和 opacity

### 图片优化
- 像素艺术使用 PNG 格式
- 添加 `image-rendering: pixelated`
- 考虑使用 SVG 图标

## 开发工具

### 推荐浏览器扩展
- React Developer Tools - 组件调试
- Accessibility Insights - 可访问性检查
- ColorZilla - 颜色拾取

### 调试技巧
```javascript
// 在浏览器控制台查看 CSS 变量
getComputedStyle(document.documentElement)
  .getPropertyValue('--color-primary')
```

## 资源链接

- [Press Start 2P Font](https://fonts.google.com/specimen/Press+Start+2P)
- [VT323 Font](https://fonts.google.com/specimen/VT323)
- [Design System Master](../design-system/unity-agent-console/MASTER.md)
- [Implementation Report](../design-system/IMPLEMENTATION_REPORT.md)

## 反馈和改进

如果发现设计问题或有改进建议，请：
1. 查看 IMPLEMENTATION_REPORT.md 了解设计决策
2. 在相应的 CSS 文件中查找相关代码
3. 遵循现有的设计模式进行修改
4. 测试响应式和可访问性

---

**最后更新**：2026-08-02  
**设计版本**：v1.0  
**状态**：✅ 生产就绪
