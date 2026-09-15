import { useMemo, useRef, useState } from 'react';

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api';
const EVALUATION_MIN_WORDS = 50;

const TURNING_TEST_PROMPTS = [
  { id: 'astronomy-seasons', subject: 'Astronomy', question: "How does Earth's tilt cause the seasons?" },
  { id: 'biology-photosynthesis', subject: 'Biology', question: 'How do plants use sunlight to grow?' },
  { id: 'ecology-bees', subject: 'Ecology', question: 'Why are bees important to an ecosystem?' },
  { id: 'physics-rolling-ball', subject: 'Physics', question: 'Why does a rolling ball eventually stop?' },
  { id: 'chemistry-changes', subject: 'Chemistry', question: 'How is melting ice different from burning wood?' },
  { id: 'earth-science-water-cycle', subject: 'Earth science', question: 'How does the water cycle move water around Earth?' },
  { id: 'geography-mountains-rainfall', subject: 'Geography', question: 'How can mountains affect rainfall?' },
  { id: 'mathematics-fractions', subject: 'Mathematics', question: 'What does a fraction represent, and when might you use one?' },
  { id: 'statistics-averages', subject: 'Statistics', question: 'How can an average give a misleading impression of a group?' },
  { id: 'history-river-civilizations', subject: 'History', question: 'Why did early civilizations often develop near rivers?' },
  { id: 'civics-branches', subject: 'Civics', question: 'Why do governments divide power among different branches?' },
  { id: 'economics-supply-demand', subject: 'Economics', question: 'How do supply and demand affect prices?' },
  { id: 'literature-theme-plot', subject: 'Literature', question: "How is a story's theme different from its plot?" },
  { id: 'media-literacy-sources', subject: 'Media literacy', question: 'How can you judge whether an online source is trustworthy?' },
  { id: 'computer-science-algorithms', subject: 'Computer science', question: 'What is an algorithm? Give an everyday example.' },
] as const;

const countWords = (text: string) => text.trim() ? text.trim().split(/\s+/).length : 0;
type Json = Record<string, unknown>;
type WindowResult = Json & { text?: unknown; label?: unknown; start_index?: unknown; end_index?: unknown };
type EvalRun = { run: number; timestamp: string; promptId: string; question: string; text: string; wordCount: number; requestedModel: string; taskId: string; response: Json; result: Json; actions: string[] };

const resultObject = (response: Json): Json => {
  for (const key of ['result', 'output', 'data']) {
    const value = response[key];
    if (value && typeof value === 'object' && !Array.isArray(value)) return value as Json;
  }
  return response;
};
const present = (value: unknown) => value !== undefined && value !== null;
const display = (value: unknown) => present(value) ? String(value) : 'Unavailable';
const fraction = (result: Json, key: string) => typeof result[key] === 'number' ? result[key] as number : undefined;
const percent = (value: number | undefined) => value === undefined ? 'Unavailable' : `${(value * 100).toFixed(1)}%`;
const windowsOf = (result: Json) => Array.isArray(result.windows) ? result.windows.filter(item => item && typeof item === 'object') as WindowResult[] : [];
const stageOf = (response: Json) => String(response.stage ?? response.status ?? '').toUpperCase();

function HighlightedPassage({ result }: { result: Json }) {
  const text = typeof result.text === 'string' ? result.text : '';
  const windows = windowsOf(result);
  const ranges = windows.map((window, index) => ({
    index, label: String(window.label ?? 'unavailable'), start: window.start_index, end: window.end_index,
  })).filter((range): range is { index: number; label: string; start: number; end: number } => (
    typeof range.start === 'number' && typeof range.end === 'number' && range.start >= 0 && range.end > range.start && range.end <= text.length
  )).sort((a, b) => a.start - b.start);
  const valid = Boolean(text) && ranges.length === windows.length && ranges.every((range, i) => i === 0 || range.start >= ranges[i - 1].end);
  if (!valid) return <div className="tt-segment-fallback">{windows.length ? windows.map((window, i) => <p key={i}><strong>Segment {i + 1} ({display(window.label)}):</strong> {display(window.text)}</p>) : <p>Highlighted passage unavailable.</p>}</div>;
  const pieces: React.ReactNode[] = []; let cursor = 0;
  ranges.forEach(range => { if (range.start > cursor) pieces.push(text.slice(cursor, range.start)); pieces.push(<mark key={range.index} className={`tt-mark tt-${range.label.toLowerCase().replace(/[^a-z]+/g, '-')}`}>{text.slice(range.start, range.end)}</mark>); cursor = range.end; });
  if (cursor < text.length) pieces.push(text.slice(cursor));
  return <p className="tt-highlighted">{pieces}</p>;
}

function Report({ run, stale }: { run: EvalRun; stale: boolean }) {
  const result = run.result; const windows = windowsOf(result);
  return <section className="tt-report" aria-labelledby={`report-${run.run}`}>
    <div className="tt-report-heading"><div><p className="tt-eyebrow">Pangram Report</p><h2 id={`report-${run.run}`}>Evaluation #{run.run}</h2></div>{stale && <span className="tt-stale">Text or prompt changed since this evaluation.</span>}</div>
    <div className="tt-snapshot"><strong>Evaluated snapshot · {run.wordCount} words</strong><p>{run.text}</p></div>
    <section><h3>Overall result</h3><p><strong>Pangram headline:</strong> {display(result.headline)}</p><p><strong>Pangram classification:</strong> {display(result.prediction_short)}</p><p><strong>Pangram explanation:</strong> {display(result.prediction)}</p></section>
    <section><h3>Text breakdown</h3><p className="tt-context">These are proportions of text classified into categories, not probabilities of cheating.</p><div className="tt-percentages"><span><i className="tt-swatch tt-ai" />AI-written <strong>{percent(fraction(result, 'fraction_ai'))}</strong></span><span><i className="tt-swatch tt-assisted" />AI-assisted <strong>{percent(fraction(result, 'fraction_ai_assisted'))}</strong></span><span><i className="tt-swatch tt-human" />Human-written <strong>{percent(fraction(result, 'fraction_human'))}</strong></span></div></section>
    <section><h3>Highlighted passage</h3><div className="tt-legend" aria-label="Passage classification legend"><span><i className="tt-swatch tt-ai" />AI-written</span><span><i className="tt-swatch tt-assisted" />AI-assisted</span><span><i className="tt-swatch tt-human" />Human-written</span></div><HighlightedPassage result={result} /></section>
    <section><h3>Segment details</h3>{windows.length ? windows.map((window, i) => <details className="tt-window" key={i}><summary>Segment {i + 1}: {display(window.label)}</summary><p>{display(window.text)}</p><dl>{[['Confidence', window.confidence], ['AI-assistance score', window.ai_assistance_score], ['Humanizer flag (detector estimate)', window.is_humanized], ['Humanizer score (detector estimate)', window.humanizer_score], ['Word count', window.word_count], ['Token length', window.token_length]].map(([label, value]) => <div key={String(label)}><dt>{String(label)}</dt><dd>{display(value)}</dd></div>)}</dl></details>) : <p>Segment details unavailable.</p>}<p className="tt-context">Humanizer fields are detector estimates, not proof of a particular tool or process. Undocumented scores are shown as returned, not as calibrated probabilities.</p></section>
    <section className="tt-technical"><h3>Technical details</h3><p>Requested model: {run.requestedModel} · Detector version: {display(result.version)} · Task ID: {run.taskId}</p><details><summary>Complete detector response (JSON)</summary><pre tabIndex={0}>{JSON.stringify(run.response, null, 2)}</pre></details></section>
  </section>;
}

async function jsonRequest(url: string, init?: RequestInit) {
  const response = await fetch(url, init); let body: Json = {};
  try { body = await response.json() as Json; } catch { /* retain generic error */ }
  if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : `Request failed (HTTP ${response.status}).`);
  return body;
}

export default function TurningTest() {
  const [promptId, setPromptId] = useState(''); const [answer, setAnswer] = useState(''); const [undo, setUndo] = useState<string | null>(null);
  const [rewritePrompt, setRewritePrompt] = useState('Make this passage sound more natural while preserving its meaning.');
  const [selection, setSelection] = useState({ start: 0, end: 0 }); const answerRef = useRef<HTMLTextAreaElement>(null); const promptRequest = useRef(0);
  const [running, setRunning] = useState<string | null>(null); const [error, setError] = useState(''); const [notice, setNotice] = useState('');
  const [history, setHistory] = useState<EvalRun[]>([]); const [actions, setActions] = useState<string[]>([]); const manualLogged = useRef(false);
  const selected = TURNING_TEST_PROMPTS.find(prompt => prompt.id === promptId); const wordCount = countWords(answer); const latest = history.at(-1);
  const stale = Boolean(latest && (latest.text !== answer || latest.promptId !== promptId));
  const log = (action: string) => setActions(current => [...current, action]);
  const edit = (value: string, pasted = false) => { setAnswer(value); setUndo(null); setSelection({ start: 0, end: 0 }); if (!manualLogged.current) { log(pasted ? 'Pasted text' : 'Manual edit'); manualLogged.current = true; } };
  const captureSelection = () => { const field = answerRef.current; if (field) setSelection({ start: field.selectionStart, end: field.selectionEnd }); };
  const changePrompt = async (value: string) => {
    const requestId = ++promptRequest.current; setPromptId(value); setAnswer(''); setUndo(null); setSelection({ start: 0, end: 0 }); setError(''); setNotice(''); setHistory([]); setActions([]); manualLogged.current = false;
    const nextPrompt = TURNING_TEST_PROMPTS.find(prompt => prompt.id === value); if (!nextPrompt) return;
    setRunning('generate'); setNotice('Generating your 300-word starting text…');
    try { const data = await jsonRequest(`${API_BASE}/turning-test/ai`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: 'generate', prompt_id: nextPrompt.id, question: nextPrompt.question, answer: '' }) }); if (requestId !== promptRequest.current) return; const next = String(data.answer ?? ''); if (!next.trim()) throw new Error('The AI returned an empty answer.'); setAnswer(next); setNotice('Starting text: AI-generated.'); setActions(['AI-generated starting text']); }
    catch (reason) { if (requestId === promptRequest.current) { setError(reason instanceof Error ? reason.message : 'Starting text could not be generated.'); setNotice(''); } }
    finally { if (requestId === promptRequest.current) setRunning(null); }
  };
  const rewriteSelection = async () => {
    if (running || !selected) return setError('Choose a prompt first.'); const { start, end } = selection;
    if (start === end) { setError('Highlight the text you want to rewrite.'); answerRef.current?.focus(); return; }
    const highlighted = answer.slice(start, end); const previous = answer; setRunning('rewrite'); setError('');
    try { const data = await jsonRequest(`${API_BASE}/turning-test/ai`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: 'rewrite', prompt_id: selected.id, question: selected.question, answer: highlighted, custom_prompt: rewritePrompt }) }); const replacement = String(data.answer ?? ''); if (!replacement.trim()) throw new Error('The AI returned an empty rewrite.'); const next = previous.slice(0, start) + replacement + previous.slice(end); setAnswer(next); setUndo(previous); setSelection({ start, end: start + replacement.length }); manualLogged.current = false; log('Rewrote highlighted text'); window.setTimeout(() => { const field = answerRef.current; field?.focus(); field?.setSelectionRange(start, start + replacement.length); }, 0); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Rewrite failed. Your draft was preserved.'); } finally { setRunning(null); }
  };
  const undoAI = () => { if (undo === null || running) return; setAnswer(undo); setUndo(null); manualLogged.current = false; log('Undo'); };
  const evaluate = async () => {
    if (running || !selected || wordCount < EVALUATION_MIN_WORDS) return; setRunning('evaluation'); setError(''); const snapshot = { promptId: selected.id, question: selected.question, text: answer, wordCount, actions: [...actions] };
    try { const submitted = await jsonRequest(`${API_BASE}/turning-test/pangram`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: snapshot.text }) }); const taskId = String(submitted.task_id); const requestedModel = String(submitted.requested_model); let response = submitted.response as Json; let stage = stageOf(response);
      for (let attempt = 0; !['STAGE_SUCCESS', 'STAGE_FAILED'].includes(stage) && attempt < 30; attempt++) { await new Promise(resolve => window.setTimeout(resolve, 2000)); const status = await jsonRequest(`${API_BASE}/turning-test/pangram/${encodeURIComponent(taskId)}`); response = status.response as Json; stage = stageOf(response); }
      if (stage === 'STAGE_FAILED') throw new Error('Pangram reported a failed task. No result was recorded.'); if (stage !== 'STAGE_SUCCESS') throw new Error('Pangram did not finish within one minute. Try again; no result was recorded.');
      const run: EvalRun = { run: history.length + 1, timestamp: new Date().toISOString(), ...snapshot, requestedModel, taskId, response, result: resultObject(response) }; setHistory(current => [...current, run]); setActions([]); manualLogged.current = false;
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Pangram evaluation failed.'); } finally { setRunning(null); }
  };
  const deltas = useMemo(() => (run: EvalRun, index: number) => { const previous = history[index - 1]; if (!previous || previous.promptId !== run.promptId || previous.requestedModel !== run.requestedModel || previous.result.version !== run.result.version) return null; return ['fraction_ai', 'fraction_ai_assisted', 'fraction_human'].map(key => { const a = fraction(run.result, key), b = fraction(previous.result, key); return a === undefined || b === undefined ? 'n/a' : `${((a - b) * 100) >= 0 ? '+' : ''}${((a - b) * 100).toFixed(1)} pp`; }).join(' · '); }, [history]);
  return <div className="tt-shell"><main className="tt-main">
    <header className="tt-intro"><h1>Turning Test</h1><p>Can you make AI-written text pass as human?</p></header>
    <section className="tt-card tt-compose"><label htmlFor="tt-prompt"><strong>Select a prompt</strong></label><select id="tt-prompt" value={promptId} onChange={event => changePrompt(event.target.value)} disabled={Boolean(running)}><option value="">Choose a prompt</option>{TURNING_TEST_PROMPTS.map(prompt => <option key={prompt.id} value={prompt.id}>{prompt.subject}: {prompt.question}</option>)}</select>{notice && <p className="tt-notice" role="status">{notice}</p>}
      <p className="tt-instructions">Edit it yourself or highlight a passage and use the AI Rewrite tool. When you’re ready, see what Pangram thinks.</p>
      <label htmlFor="tt-answer"><strong>Your answer</strong></label><textarea ref={answerRef} id="tt-answer" value={answer} onChange={event => edit(event.target.value)} onSelect={captureSelection} onKeyUp={captureSelection} onMouseUp={captureSelection} onPaste={() => { if (!manualLogged.current) { log('Pasted text'); manualLogged.current = true; } }} disabled={Boolean(running)} placeholder={selected ? 'Your AI-generated starting text will appear here…' : 'Choose a prompt to generate starting text…'} />
      <p className={`tt-count ${wordCount < EVALUATION_MIN_WORDS ? 'short' : ''}`}>{wordCount} words · Starting target: 300 · Pangram minimum: {EVALUATION_MIN_WORDS}</p>
      <div className="tt-tools-heading"><h2>AI Tool: Rewrite</h2><button type="button" className="tt-link" onClick={undoAI} disabled={undo === null || Boolean(running)}>Undo AI edit</button></div>
      <p className="tt-tool-help">Highlight only the passage you want to change, then tell the AI how to rewrite it. Rewrite never changes the whole document unless you select the whole document.</p>
      <label htmlFor="tt-rewrite-prompt"><strong>Rewrite instructions</strong></label><textarea className="tt-rewrite-prompt" id="tt-rewrite-prompt" value={rewritePrompt} onChange={event => setRewritePrompt(event.target.value)} disabled={Boolean(running)} />
      <div className="tt-tools"><button type="button" onMouseDown={event => event.preventDefault()} onClick={rewriteSelection} disabled={Boolean(running) || !selected}>{running === 'rewrite' ? 'Rewriting selection…' : 'Rewrite highlighted text'}</button></div>
      <button type="button" className="tt-evaluate" onClick={evaluate} disabled={Boolean(running) || !selected || wordCount < EVALUATION_MIN_WORDS}>{running === 'evaluation' ? 'Pangram is evaluating…' : 'Run Pangram Eval'}</button>{wordCount < EVALUATION_MIN_WORDS && <p className="tt-guidance">Add {EVALUATION_MIN_WORDS - wordCount} more {EVALUATION_MIN_WORDS - wordCount === 1 ? 'word' : 'words'} to enable evaluation. Text is never padded automatically.</p>}{error && <p className="tt-error" role="alert">{error}</p>}
    </section>
    {latest ? <Report run={latest} stale={stale} /> : <section className="tt-report tt-empty"><p className="tt-eyebrow">Pangram Report</p><h2>No evaluation yet</h2><p>Choose a prompt, write at least {EVALUATION_MIN_WORDS} words, then run the evaluation.</p></section>}
    <section className="tt-history"><h2>Evaluation history</h2><p>This session log records interactions in this app, not verified authorship of pasted or typed text.</p>{history.length ? [...history].reverse().map((run, reverseIndex) => { const index = history.length - 1 - reverseIndex; const delta = deltas(run, index); return <details key={run.run}><summary><span><strong>Run {run.run}</strong> · {new Date(run.timestamp).toLocaleTimeString()} · {run.actions.join(' → ') || 'No actions logged'}</span><span>{display(run.result.prediction_short)} · {percent(fraction(run.result, 'fraction_ai'))} / {percent(fraction(run.result, 'fraction_ai_assisted'))} / {percent(fraction(run.result, 'fraction_human'))}</span>{delta && <small>Change (AI / assisted / human): {delta}</small>}</summary><Report run={run} stale={false} /></details>; }) : <p>No successful evaluations in this session.</p>}</section>
  </main></div>;
}
