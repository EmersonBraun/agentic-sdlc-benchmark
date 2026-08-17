const projects = [
  { key: "WEB", name: "Website refresh", status: "Active", progress: 72, color: "coral" },
  { key: "OPS", name: "Operations handbook", status: "Planning", progress: 34, color: "blue" },
  { key: "MOB", name: "Mobile companion", status: "Paused", progress: 18, color: "gold" },
];

const activities = [
  { title: "Review onboarding flow", project: "Website refresh", owner: "ML", due: "Today", status: "In progress" },
  { title: "Draft incident checklist", project: "Operations handbook", owner: "JR", due: "Tomorrow", status: "Todo" },
  { title: "Validate beta feedback", project: "Mobile companion", owner: "AK", due: "Friday", status: "Blocked" },
  { title: "Publish release notes", project: "Website refresh", owner: "ML", due: "Friday", status: "Todo" },
];

const statusClass: Record<string, string> = {
  "In progress": "status statusProgress",
  Todo: "status statusTodo",
  Blocked: "status statusBlocked",
};

export default function Home() {
  return (
    <main className="shell">
      <aside className="sidebar">
        <div className="brand"><span className="brandMark">N</span><span>northstar</span></div>
        <div className="workspace"><span className="workspaceDot" /> Acme Studio <span className="chevron">⌄</span></div>
        <nav aria-label="Primary navigation" className="nav">
          <a className="navItem active" href="#overview"><span>◈</span> Overview</a>
          <a className="navItem" href="#projects"><span>▦</span> Projects</a>
          <a className="navItem" href="#activities"><span>✓</span> My activities <b>6</b></a>
          <a className="navItem" href="#timeline"><span>◷</span> Timeline</a>
        </nav>
        <div className="sidebarSection"><span>Workspace</span><button aria-label="Add workspace item">+</button></div>
        <nav aria-label="Workspace navigation" className="nav compact">
          <a className="navItem" href="#team"><span>♧</span> Team</a>
          <a className="navItem" href="#activity-log"><span>≋</span> Activity log</a>
        </nav>
        <div className="sidebarBottom"><a className="navItem" href="#settings"><span>⚙</span> Settings</a><div className="userMini"><span className="avatar avatarRose">ML</span><span><strong>Marina Lima</strong><small>Admin</small></span><span className="chevron">⌄</span></div></div>
      </aside>

      <section className="content" id="overview">
        <header className="topbar"><div className="breadcrumbs"><span>Acme Studio</span><span>/</span><strong>Overview</strong></div><div className="topActions"><button className="iconButton" aria-label="Search">⌕</button><button className="iconButton" aria-label="Notifications">♢</button><button className="createButton">＋ New activity</button></div></header>
        <div className="pageIntro"><div><p className="eyebrow">Monday, September 22, 2025</p><h1>Good morning, Marina<span className="wave">✦</span></h1><p className="introText">Here is the pulse of your workspace. You have <strong>6 activities</strong> needing attention.</p></div><button className="dateButton">This week <span>⌄</span></button></div>

        <div className="metricGrid" aria-label="Workspace metrics">
          <article className="metricCard"><div className="metricLabel"><span className="metricIcon iconCoral">◒</span> Active projects</div><div className="metricValue">08</div><div className="metricTrend trendUp">↗ 12.5% <span>vs last month</span></div></article>
          <article className="metricCard"><div className="metricLabel"><span className="metricIcon iconBlue">✓</span> Completed this week</div><div className="metricValue">24</div><div className="metricTrend trendUp">↗ 8.2% <span>vs last week</span></div></article>
          <article className="metricCard"><div className="metricLabel"><span className="metricIcon iconGold">◷</span> On-time rate</div><div className="metricValue">94<span className="unit">%</span></div><div className="metricTrend trendDown">↘ 2.4% <span>vs last week</span></div></article>
        </div>

        <div className="sectionHeading" id="projects"><div><h2>Projects</h2><p>Keep an eye on the work that moves the team forward.</p></div><a href="#all-projects">View all <span>→</span></a></div>
        <div className="projectGrid">{projects.map((project) => <article className="projectCard" key={project.key}><div className={`projectIcon ${project.color}`}>{project.key.slice(0, 1)}</div><div className="projectCardHeader"><div><h3>{project.name}</h3><p><span className={`dot ${project.color}`} /> {project.status}</p></div><button className="moreButton" aria-label={`More options for ${project.name}`}>•••</button></div><div className="progressMeta"><span>Progress</span><strong>{project.progress}%</strong></div><div className="progressTrack"><span className={project.color} style={{ width: `${project.progress}%` }} /></div><div className="projectFooter"><div className="avatarStack"><span className="avatar avatarBlue">ML</span><span className="avatar avatarGold">AK</span><span className="avatar avatarInk">+3</span></div><span className="activityCount">{project.key === "WEB" ? "12" : project.key === "OPS" ? "08" : "04"} activities</span></div></article>)}</div>

        <div className="sectionHeading activitiesHeading" id="activities"><div><h2>My activities</h2><p>Your personal focus list for the week.</p></div><a href="#all-activities">View all <span>→</span></a></div>
        <div className="activityTable"><div className="tableHead"><span>Activity</span><span>Project</span><span>Due date</span><span>Status</span></div>{activities.map((activity) => <div className="tableRow" key={activity.title}><div className="activityTitle"><span className="checkCircle" /> <strong>{activity.title}</strong></div><div className="projectName"><span className="miniProject" /> {activity.project}</div><div className="dueDate"><span className="avatar avatarRose">{activity.owner}</span>{activity.due}</div><div><span className={statusClass[activity.status]}>{activity.status}</span></div></div>)}</div>

        <footer className="footer"><span>Northstar workspace</span><span>All systems operational <i className="systemDot" /></span><span>v0.1.0</span></footer>
      </section>
    </main>
  );
}

