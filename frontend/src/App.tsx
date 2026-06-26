import { useEffect, useState } from "react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";

const API = "http://localhost:8000";

interface Summary {
  date: string;
  sip_count: number;
  break_count: number;
  avg_break_duration_min: number;
  lunch_duration_min: number | null;
  total_events: number;
}

interface WeekDay {
  date: string;
  sip_count: number;
  break_count: number;
}

interface Event {
  id: number;
  activity: string;
  confidence: number;
  timestamp: string;
}

const ACTIVITY_COLORS: Record<string, string> = {
  at_desk: "#4ade80",
  away: "#facc15",
  sipping: "#60a5fa",
  stretching: "#f472b6",
  unknown: "#94a3b8",
};

function StatCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="bg-white rounded-2xl p-5 shadow-sm border border-slate-100">
      <p className="text-sm text-slate-500 mb-1">{label}</p>
      <p className="text-3xl font-semibold text-slate-800">{value}</p>
      {sub && <p className="text-xs text-slate-400 mt-1">{sub}</p>}
    </div>
  );
}

export default function App() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [weekly, setWeekly] = useState<WeekDay[]>([]);
  const [events, setEvents] = useState<Event[]>([]);

  useEffect(() => {
    fetch(`${API}/summary`).then((r) => r.json()).then(setSummary);
    fetch(`${API}/weekly`).then((r) => r.json()).then(setWeekly);
    fetch(`${API}/events`).then((r) => r.json()).then(setEvents);

    // Refresh every 30 seconds
    const id = setInterval(() => {
      fetch(`${API}/summary`).then((r) => r.json()).then(setSummary);
      fetch(`${API}/events`).then((r) => r.json()).then(setEvents);
    }, 30_000);
    return () => clearInterval(id);
  }, []);

  const recentEvents = events.slice(-20).reverse();

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 p-6 font-sans">
      <header className="mb-8">
        <h1 className="text-2xl font-bold">Desk Watcher</h1>
        <p className="text-sm text-slate-500">
          {summary?.date ?? "Today"} · {summary?.total_events ?? 0} events logged
        </p>
      </header>

      {/* Stats row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        <StatCard label="Sips today" value={summary?.sip_count ?? "—"} sub="hydration events" />
        <StatCard label="Breaks" value={summary?.break_count ?? "—"} sub={`avg ${summary?.avg_break_duration_min ?? 0} min`} />
        <StatCard
          label="Lunch"
          value={summary?.lunch_duration_min ? `${summary.lunch_duration_min} min` : "—"}
          sub="midday break"
        />
        <StatCard label="Total events" value={summary?.total_events ?? "—"} />
      </div>

      {/* Weekly chart */}
      <div className="bg-white rounded-2xl p-5 shadow-sm border border-slate-100 mb-8">
        <h2 className="text-sm font-semibold text-slate-600 mb-4">Weekly Overview</h2>
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={weekly} margin={{ top: 0, right: 0, left: -20, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
            <XAxis dataKey="date" tick={{ fontSize: 11 }} tickFormatter={(d) => d.slice(5)} />
            <YAxis tick={{ fontSize: 11 }} />
            <Tooltip />
            <Bar dataKey="sip_count" name="Sips" fill="#60a5fa" radius={[4, 4, 0, 0]} />
            <Bar dataKey="break_count" name="Breaks" fill="#facc15" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Recent events */}
      <div className="bg-white rounded-2xl p-5 shadow-sm border border-slate-100">
        <h2 className="text-sm font-semibold text-slate-600 mb-4">Recent Events</h2>
        <div className="space-y-2">
          {recentEvents.length === 0 && (
            <p className="text-sm text-slate-400">No events yet today.</p>
          )}
          {recentEvents.map((e) => (
            <div key={e.id} className="flex items-center gap-3 text-sm">
              <span
                className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                style={{ backgroundColor: ACTIVITY_COLORS[e.activity] ?? "#94a3b8" }}
              />
              <span className="text-slate-400 w-20 flex-shrink-0 text-xs">
                {new Date(e.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
              </span>
              <span className="font-medium capitalize">{e.activity.replace("_", " ")}</span>
              <span className="text-slate-400 text-xs ml-auto">{Math.round(e.confidence * 100)}%</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
