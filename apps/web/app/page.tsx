import Link from "next/link";
import { navigationItems } from "@/lib/navigation";

const sections = [
  {
    title: "Market overview",
    description: "The ten-asset universe and market regime will appear here once the API is connected.",
    href: "/chart",
    action: "View chart workspace",
  },
  {
    title: "Daily brief",
    description: "A transparent Coin of the Day or No Trade result, backed by dated evidence.",
    href: "/brief",
    action: "Open daily brief",
  },
  {
    title: "News & events",
    description: "Source-linked articles and provider health will be shown here.",
    href: "/news",
    action: "Review evidence",
  },
  {
    title: "Outlook",
    description: "Week, month and year scenarios will be displayed as ranges with uncertainty.",
    href: "/outlook",
    action: "See outlook areas",
  },
] as const;

export default function HomePage() {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">CM</span>
          <div>
            <strong>Crypto Market</strong>
            <span>Insights</span>
          </div>
        </div>
        <nav aria-label="Primary navigation">
          {navigationItems.map((item, index) => (
            <Link className={index === 0 ? "nav-link active" : "nav-link"} href={item.href} key={item.href}>
              <span className="nav-index">0{index + 1}</span>
              {item.label}
            </Link>
          ))}
        </nav>
        <p className="sidebar-note">Research only. No execution, custody, or personalized advice.</p>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <div>
            <p className="eyebrow">Daily research cockpit</p>
            <h1>Good morning, researcher.</h1>
          </div>
          <div className="status-pill">
            <span className="status-dot" />
            API connection pending
          </div>
        </header>

        <section className="hero-card" aria-labelledby="research-status">
          <div>
            <p className="eyebrow">Today&apos;s decision state</p>
            <h2 id="research-status">No published brief yet</h2>
            <p className="hero-copy">
              The dashboard is ready for live, source-grounded results. It will never fill a missing
              result with invented market data.
            </p>
          </div>
          <div className="hero-badge">AWAITING API DATA</div>
        </section>

        <section className="section-heading">
          <div>
            <p className="eyebrow">Workspace</p>
            <h2>Research areas</h2>
          </div>
          <p className="muted">Last refresh: not available</p>
        </section>

        <section className="card-grid" aria-label="Research areas">
          {sections.map((section) => (
            <article className="area-card" key={section.title}>
              <div className="placeholder-icon" aria-hidden="true">
                —
              </div>
              <h3>{section.title}</h3>
              <p>{section.description}</p>
              <Link href={section.href} className="text-link">
                {section.action} <span aria-hidden="true">→</span>
              </Link>
            </article>
          ))}
        </section>

        <section className="notice-card">
          <div>
            <p className="eyebrow">Product boundary</p>
            <h2>Evidence before narrative</h2>
          </div>
          <p>
            This local-first application is read-only research software. Deterministic calculations
            will be completed before any AI explanation, and No Trade is always a valid outcome.
          </p>
        </section>
      </main>
    </div>
  );
}
