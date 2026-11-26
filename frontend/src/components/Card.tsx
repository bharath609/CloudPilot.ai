import type { ReactNode } from "react";

export function Card({
  title,
  subtitle,
  right,
  children,
}: {
  title?: string;
  subtitle?: string;
  right?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="card">
      {(title || right) && (
        <div className="card-head">
          <div>
            {title && <h2 className="card-title">{title}</h2>}
            {subtitle && <p className="card-subtitle">{subtitle}</p>}
          </div>
          {right && <div className="card-right">{right}</div>}
        </div>
      )}
      <div className="card-body">{children}</div>
    </section>
  );
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {hint && <div className="stat-hint">{hint}</div>}
    </div>
  );
}

export function Badge({ tone, children }: { tone: string; children: ReactNode }) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}

export function Loading({ what = "data" }: { what?: string }) {
  return <div className="loading">Loading {what}…</div>;
}

export function ErrorBox({ message }: { message: string }) {
  return <div className="error-box">Error: {message}</div>;
}
