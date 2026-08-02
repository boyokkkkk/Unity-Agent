# Unity Agent Console - 像素风格 + 简洁排版

## 设计理念

**保持像素艺术风格 + 学习原型的简洁排版**

根据您提供的原型图片，我们保留了像素艺术的视觉风格（像素字体、粗边框、方形元素），但学习了原型的简洁排版设计，去除了多余的框和装饰。

---

## 原型排版分析

### 原型的优点
1. ✅ **清晰的信息层级** - 大标题 → 统计数字 → 列表
2. ✅ **留白充足** - 元素之间有足够的呼吸空间
3. ✅ **减少边框** - 只在必要处使用边框
4. ✅ **统一的网格** - 统计卡片、筛选标签对齐整齐
5. ✅ **简洁的列表项** - 只显示关键信息

### 当前界面问题
1. ❌ 过多嵌套的 panel 和边框
2. ❌ 信息密度过高
3. ❌ 视觉噪音太多
4. ❌ 缺少清晰的视觉层级

---

## 改进方案

### 页面结构（学习原型）

```
┌─────────────────────────────────────┐
│ 标题区                               │ ← 简洁，无边框
│ EXPERIMENT REGISTRY                  │
│ 实验运行记录                          │
│ 描述文字...                          │
└─────────────────────────────────────┘

┌───────┬───────┬───────┬───────┐
│   0   │   0   │   0   │   0   │     ← 统计卡片，4px 边框
│ 全部  │ 运行中 │ 已提交 │ 失败  │
└───────┴───────┴───────┴───────┘

┌─────────────────────────────────────┐
│ RUNS                    [刷新按钮]   │ ← 列表标题
├─────────────────────────────────────┤
│ [搜索框]         [全部][运行中]...   │ ← 工具栏
├─────────────────────────────────────┤
│ ● 任务名称              状态  时间 → │ ← 列表项，极简
│ ● 任务名称              状态  时间 → │
│ ● 任务名称              状态  时间 → │
└─────────────────────────────────────┘
```

### 关键改进点

#### 1. 标题区 - 无边框，突出文字
```tsx
<header className="runs-page-header">
  <span className="eyebrow">EXPERIMENT REGISTRY</span>
  <h1>实验运行记录</h1>
  <p>集中查看每一次 Unity Agent 实验...</p>
</header>
```

**特点**：
- 无背景、无边框
- 使用小标签（eyebrow）增加层级
- 大标题 32px 像素字体

#### 2. 统计卡片 - 数字优先
```tsx
<div className="stat-box">
  <span className="stat-number purple">12</span>
  <span className="stat-label">正在运行</span>
</div>
```

**特点**：
- 40px 大数字（像素字体）
- 彩色数字，灰色标签
- 4px 边框 + 像素化四角
- 充足的内边距

#### 3. 列表容器 - 单一边框
```tsx
<div className="runs-list-container">
  <div className="runs-list-header">...</div>
  <div className="run-item">...</div>
  <div className="run-item">...</div>
</div>
```

**特点**：
- 整个列表只有一个外边框
- 列表项之间用细线分隔（2px）
- 无嵌套的 panel

#### 4. 列表项 - Grid 布局
```tsx
<div className="run-item">
  <div className="run-status-indicator" />  <!-- 状态点 -->
  <div className="run-content">             <!-- 任务信息 -->
    <p className="run-task">任务名称</p>
    <div className="run-meta">Run ID · 项目</div>
  </div>
  <span className="run-time">2分钟前</span>
  <span className="run-arrow">→</span>
</div>
```

**布局**：
```
[●] [任务名称              ] [时间] [→]
    [Run ID · 项目路径     ]
```

**特点**：
- CSS Grid 四列布局
- 状态点 12x12px
- 箭头 32x32px 方框
- 悬停时箭头变色

---

## 去除的多余元素

### Before（当前）
```tsx
<section className="panel run-registry">          // ← 外层 panel
  <SectionHeader />                               // ← 独立头部组件
  <div className="toolbar">                       // ← 工具栏容器
    <label className="search-box">               // ← 搜索框 label
      <span>⌕</span>
      <input />
    </label>
  </div>
  <div className="run-table-wrap">               // ← 表格包装
    <table className="run-table">                // ← 表格布局
      <thead><tr><th>...</th></tr></thead>
      <tbody>
        <tr>                                      // ← 表格行
          <td>...</td>
        </tr>
      </tbody>
    </table>
  </div>
</section>
```

**问题**：
- 3 层嵌套容器
- 表格语义不匹配（非表格数据）
- 过多的边框和背景

### After（简化后）
```tsx
<div className="runs-list-container">            // ← 单一容器
  <div className="runs-list-header">            // ← 简单头部
    <h2>RUNS</h2>
    <button className="refresh-button">↻</button>
  </div>
  <div className="runs-toolbar">                 // ← 搜索 + 筛选
    <div className="runs-search">
      <input />
    </div>
    <div className="runs-filter-tabs">
      <button>全部</button>
      <button>运行中</button>
    </div>
  </div>
  <div className="run-item">                     // ← 扁平的列表项
    ...
  </div>
</div>
```

**优点**：
- 1 层容器
- 扁平的列表项（非表格）
- 单一外边框
- 清晰的视觉层级

---

## 像素风格保留

### 保持的像素元素
✅ **字体**：Press Start 2P（标题）+ VT323（正文）  
✅ **边框**：3-4px 粗边框  
✅ **方形**：无圆角设计  
✅ **像素化四角**：使用伪元素装饰  
✅ **8-bit 颜色**：鲜艳的紫色、粉色、绿色  
✅ **闪烁动画**：运行中状态的 blink 动画  

### 去除的像素效果
❌ 过度的 3D 阴影  
❌ 多层嵌套边框  
❌ 像素网格背景（干扰阅读）  
❌ 过多的装饰性元素  

---

## 实现细节

### CSS 组织
```
runs-page-clean.css
├── 页面布局（最大宽度、边距）
├── 标题区（无边框）
├── 统计卡片（Grid 4列）
├── 工具栏（Flex 布局）
├── 列表容器（单一边框）
└── 列表项（Grid 布局）
```

### 响应式断点
```css
/* 平板 */
@media (max-width: 1024px) {
  .runs-stats-bar {
    grid-template-columns: repeat(2, 1fr); /* 2列 */
  }
}

/* 手机 */
@media (max-width: 768px) {
  .run-item {
    grid-template-columns: auto 1fr;      /* 2列 */
  }
  .runs-stats-bar {
    grid-template-columns: 1fr;           /* 1列 */
  }
}
```

---

## 使用方法

### 1. 样式已导入
```tsx
// main.tsx
import "./pixel-theme.css";       // 像素基础
import "./runs-page-clean.css";   // 简洁排版
```

### 2. 组件无需修改
现有的 `RunsPage.tsx` 组件已经使用了正确的类名：
- `.runs-page` - 页面容器
- `.page-hero` - 标题区
- `.metric-strip` - 统计条
- `.run-registry` - 列表容器

### 3. 查看效果
刷新浏览器即可看到新的简洁布局。

---

## 对比总结

| 方面 | 原设计 | 新设计 |
|------|--------|--------|
| 容器嵌套 | 3-4 层 | 1-2 层 |
| 边框数量 | 很多 | 最小化 |
| 列表实现 | Table | Grid |
| 信息密度 | 过高 | 适中 |
| 留白 | 不足 | 充足 |
| 视觉层级 | 模糊 | 清晰 |
| 像素风格 | 保留 | 保留 |

---

## 设计原则（学习自原型）

1. **少即是多** - 去除不必要的边框和容器
2. **呼吸空间** - 元素之间保持充足间距
3. **视觉层级** - 大小、颜色、位置建立层级
4. **功能优先** - 装饰服务于功能
5. **保持风格** - 像素艺术的核心特征不变

---

**现在界面更简洁、清晰，同时保持了像素艺术的独特风格！** 🎮✨
