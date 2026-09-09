import { useState } from 'react';

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api';

type Option = { label: string; value: string };
type Belief = { id: string; statement: string; confidence: number; sources: string[] };
type Change = { belief_id: string; operation: string; before?: Belief; after?: Belief; evidence: string[]; explanation: string };
type Session = {
  id: string; lesson_title: string; profile: string; beliefs: Belief[]; unresolved_questions: string[];
  messages: Array<{ id: string; role: 'user' | 'assistant'; content: string; leakage_flags?: Array<{ claim: string; reason: string }> }>;
  history: Array<{ turn_id: string; at: string; changes: Change[]; teaching_message_id: string }>;
  run_config: Record<string, unknown>;
  evaluation: { corrected: string[]; remaining: string[]; newly_introduced: string[]; stalled: string[]; certainty: string };
};

export default function TeachBot({ topics, onExit }: { topics: Option[]; onExit: () => void }) {
  const [topic, setTopic] = useState(topics[0]?.value || 'default');
  const [profile, setProfile] = useState('blank_slate');
  const [session, setSession] = useState<Session | null>(null);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [snapshots, setSnapshots] = useState<Array<{ id: string; name: string }>>([]);
  const [changed, setChanged] = useState<string[]>([]);

  const call = async (path: string, body?: unknown) => {
    const response = await fetch(`${API_BASE}${path}`, { method: body ? 'POST' : 'GET', headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || 'TeachBot request failed.');
    return payload;
  };
  const start = async () => {
    setBusy(true); setError('');
    try { setSession(await call('/teachbot/start', { lesson_code: topic, learner_profile: profile })); setChanged([]); setSnapshots([]); }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not start TeachBot.'); } finally { setBusy(false); }
  };
  const send = async () => {
    if (!session || !text.trim() || busy) return;
    const content = text.trim(); setText(''); setBusy(true); setError('');
    try { const data = await call('/teachbot/turn', { session_id: session.id, content, request_id: crypto.randomUUID() }); setSession(data.session); setChanged(data.accepted_changes.map((c: Change) => c.belief_id)); }
    catch (e) { setText(content); setError(e instanceof Error ? e.message : 'Turn failed.'); } finally { setBusy(false); }
  };
  const snapshot = async () => {
    if (!session) return;
    try { const snap = await call(`/teachbot/${session.id}/snapshot`, { name: `After turn ${session.history.length}` }); setSnapshots(items => [...items, snap]); }
    catch (e) { setError(e instanceof Error ? e.message : 'Snapshot failed.'); }
  };
  const restore = async (id: string) => {
    if (!session) return;
    try { setSession(await call(`/teachbot/${session.id}/restore`, { snapshot_id: id })); setChanged([]); }
    catch (e) { setError(e instanceof Error ? e.message : 'Restore failed.'); }
  };
  const exportRun = async () => {
    if (!session) return;
    const data = await call(`/teachbot/${session.id}/export`);
    const link = document.createElement('a'); link.href = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })); link.download = `teachbot-${session.id}.json`; link.click(); URL.revokeObjectURL(link.href);
  };

  if (!session) return <div className="tb-shell"><header className="tb-header"><button onClick={onExit}>← Prototypes</button><b>Michigan Virtual · TEACHBOT</b></header><main className="tb-start"><p className="tb-kicker">LEARNING BY TEACHING AN AI LEARNER</p><h1>Teach it to understand it.</h1><p>You are the teacher. TeachBot begins with limited simulated knowledge and changes its beliefs only from your teaching.</p><label>Topic<select value={topic} onChange={e => setTopic(e.target.value)}>{topics.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}</select></label><label>Learner profile<select value={profile} onChange={e => setProfile(e.target.value)}><option value="blank_slate">Blank-slate novice</option><option value="confident_novice">Confident novice with misconceptions</option><option value="uncertain">Uncertain learner</option></select></label>{error && <p className="tb-error">{error}</p>}<button className="tb-primary" disabled={busy} onClick={start}>{busy ? 'Preparing learner…' : 'Start teaching'}</button></main></div>;

  const evalCards: Array<[string, string[]]> = [['Corrected', session.evaluation.corrected], ['Remaining', session.evaluation.remaining], ['Newly introduced', session.evaluation.newly_introduced], ['Stalled', session.evaluation.stalled]];
  return <div className="tb-shell"><header className="tb-header"><button onClick={onExit}>← Prototypes</button><div><b>TEACHBOT</b><span>{session.lesson_title} · {session.profile.replace('_', ' ')}</span></div><nav><button onClick={snapshot}>Save snapshot</button><select aria-label="Restore snapshot" value="" onChange={e => restore(e.target.value)}><option value="">Restore…</option>{snapshots.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</select><button onClick={exportRun}>Export JSON</button><button onClick={start}>Reset</button></nav></header><div className="tb-notice"><strong>You teach; TeachBot learns.</strong> The belief panel is simulated learner state—not hidden model reasoning. Limited knowledge is prompted, not erased from the underlying model.</div><main className="tb-grid"><section className="tb-chat"><div className="tb-messages">{session.messages.length === 0 && <div className="tb-empty"><span>YOUR LESSON STARTS HERE</span><h2>What will you teach first?</h2><p>Explain one idea clearly, then check how your learner understood it.</p></div>}{session.messages.map(m => <article key={m.id} className={`tb-message tb-${m.role}`}><small>{m.role === 'user' ? 'You · Teacher' : 'TeachBot · Learner'}</small><p>{m.content}</p>{m.leakage_flags?.map((f, i) => <em key={i}>⚑ Heuristic leakage review: {f.claim}</em>)}</article>)}</div><div className="tb-compose"><textarea value={text} onChange={e => setText(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }} placeholder="Teach TeachBot something…" /><button disabled={busy || !text.trim()} onClick={send}>{busy ? 'Learning…' : 'Teach'}</button></div>{error && <p className="tb-error">{error}</p>}</section><aside className="tb-side"><section><div className="tb-panel-title"><div><p>SIMULATED LEARNER STATE</p><h2>What TeachBot believes</h2></div><span>{session.beliefs.length}</span></div>{session.beliefs.length ? session.beliefs.map(b => <article key={b.id} className={changed.includes(b.id) ? 'tb-belief changed' : 'tb-belief'}><p>{b.statement}</p><div><span style={{ width: `${b.confidence * 100}%` }} /><small>{Math.round(b.confidence * 100)}% conviction</small></div><small>Sources: {b.sources.join(', ')}</small></article>) : <p className="tb-muted">Nothing taught yet. Ask a question to test the blank slate.</p>}</section><section><p className="tb-section-label">OBSERVER DASHBOARD · EVALUATOR JUDGMENTS</p><small>Separate from learner beliefs · results may be uncertain</small><div className="tb-eval">{evalCards.map(([title, items]) => <div key={title}><b>{title}</b><span>{items.length}</span>{items.map(item => <p key={item}>{item}</p>)}</div>)}</div></section><details><summary>Belief change history ({session.history.length})</summary>{[...session.history].reverse().map(event => <article className="tb-history" key={event.turn_id}><b>{new Date(event.at).toLocaleString()}</b>{event.changes.length === 0 ? <p>No belief changes accepted.</p> : event.changes.map(c => <p key={c.belief_id}><strong>{c.operation}</strong> {c.belief_id}: {c.explanation}<br/><small>Evidence: {c.evidence.join(', ')}</small></p>)}</article>)}</details><details><summary>Run configuration</summary><pre>{JSON.stringify(session.run_config, null, 2)}</pre></details><p className="tb-heuristic">Leakage flags are heuristic review aids, not proof that leakage is absent.</p></aside></main></div>;
}
