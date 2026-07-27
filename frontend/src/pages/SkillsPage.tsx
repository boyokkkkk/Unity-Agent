import { Icon, type IconName } from "../components/Icon";
import { Link } from "../router";

const skills: Array<{ title: string; domain: string; detail: string; icon: IconName; tone: string; tags: string[] }> = [
  { title: "Unity 工程理解", domain: "PROJECT INTELLIGENCE", detail: "读取工程结构、Assembly Definition、场景和资源依赖，建立任务上下文。", icon: "box", tone: "violet", tags: ["Assets", "Scene", "Packages"] },
  { title: "C# 代码执行", domain: "CODE AGENT", detail: "定位问题、编辑脚本并保持现有架构约束，输出可审查的 Git Diff。", icon: "code", tone: "blue", tags: ["C#", "Refactor", "Diff"] },
  { title: "Unity 自动验证", domain: "VALIDATION", detail: "组织 Compile、EditMode 与 PlayMode 检查，结构化记录验证结果。", icon: "check", tone: "green", tags: ["Compile", "EditMode", "PlayMode"] },
  { title: "视觉与场景检查", domain: "MULTIMODAL", detail: "结合截图与运行产物理解场景表现，为 UI 和游戏逻辑提供反馈。", icon: "eye", tone: "orange", tags: ["Screenshot", "UI", "Scene"] },
  { title: "仓库安全操作", domain: "WORKSPACE", detail: "在项目边界内执行命令，保留用户改动，并对关键文件进行差异审查。", icon: "git", tone: "pink", tags: ["Git", "Sandbox", "Review"] },
  { title: "执行轨迹记录", domain: "OBSERVABILITY", detail: "实时记录模型调用、工具输出、耗时、成本与最终产物，支持完整复盘。", icon: "activity", tone: "cyan", tags: ["Timeline", "Cost", "Artifact"] },
];

export function SkillsPage() {
  return <div className="page skills-page"><header className="page-hero compact-hero"><div><span className="eyebrow">Agent Capabilities</span><h1>Unity 专属 Skill</h1>
    <p>这里展示 Agent 在 Unity 项目任务中可调用的专业能力，而不是通用聊天功能。</p></div>
    <Link className="button button-primary" to="/runs/new"><Icon name="sparkles" size={16} />调用 Skill</Link></header>
    <section className="skill-callout panel"><div className="skill-orbit"><span>UA</span><i /><i /><i /></div><div><span className="eyebrow">Auto orchestration</span><h2>一次任务，自动编排多个能力</h2>
      <p>Agent 会根据任务阶段在工程理解、编码、Unity 验证和产物审查之间切换，并把每一步写入实时轨迹。</p></div><div className="skill-callout-flow"><span>理解</span><i /><span>执行</span><i /><span>验证</span></div></section>
    <section className="skill-grid">{skills.map((skill) => <article className="skill-card panel" key={skill.title}><span className={`skill-icon ${skill.tone}`}><Icon name={skill.icon} /></span>
      <span className="eyebrow">{skill.domain}</span><h2>{skill.title}</h2><p>{skill.detail}</p><div>{skill.tags.map((tag) => <span key={tag}>{tag}</span>)}</div></article>)}</section>
  </div>;
}
