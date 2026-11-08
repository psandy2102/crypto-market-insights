import Link from "next/link";
import { notFound } from "next/navigation";
import { navigationItems } from "@/lib/navigation";

type SectionPageProps = {
  params: Promise<{ section: string }>;
};

const sectionContent: Record<string, { title: string; description: string }> = {
  brief: {
    title: "Daily brief",
    description: "Published Coin of the Day and No Trade results will appear here.",
  },
  chart: {
    title: "Chart workspace",
    description: "Venue-specific candles, indicators, and setup levels will appear here.",
  },
  news: {
    title: "News & events",
    description: "Deduplicated, source-linked evidence will appear here.",
  },
  outlook: {
    title: "Scenario outlook",
    description: "Week, month, and year ranges with assumptions will appear here.",
  },
  performance: {
    title: "Historical performance",
    description: "Chronological, cost-aware evaluation will appear here.",
  },
  settings: {
    title: "Settings & health",
    description: "Configuration, provider status, and data freshness will appear here.",
  },
};

export function generateStaticParams() {
  return navigationItems
    .filter((item) => item.href !== "/")
    .map((item) => ({ section: item.href.slice(1) }));
}

export default async function SectionPage({ params }: SectionPageProps) {
  const { section } = await params;
  const content = sectionContent[section];

  if (!content) {
    notFound();
  }

  return (
    <main className="placeholder-page">
      <p className="eyebrow">Research workspace</p>
      <h1>{content.title}</h1>
      <p className="placeholder-page-copy">{content.description}</p>
      <p className="placeholder-page-note">
        This area is intentionally empty until the backend publishes verified data.
      </p>
      <Link href="/" className="text-link">
        ← Back to overview
      </Link>
    </main>
  );
}
