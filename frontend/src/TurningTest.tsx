import { useMemo, useRef, useState } from 'react';

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api';
const EVALUATION_MIN_WORDS = 50;

const TURNING_TEST_PROMPT = { id: 'astronomy-seasons', question: "How does Earth's tilt cause the season's?" } as const;

const HUMAN_GENERATED_PASSAGE = `Many people have believed that the seasons were the result of the changing distance between Earth and the Sun. This sounds reasonable at first: it should be colder when Earth is farther from the Sun. But the facts don’t bear out this hypothesis. Although Earth’s orbit around the Sun is an ellipse, its distance from the Sun varies by only about 3%. That’s not enough to cause significant variations in the Sun’s heating. To make matters worse for people in North America who hold this hypothesis, Earth is actually closest to the Sun in January, when the Northern Hemisphere is in the middle of winter. And if distance were the governing factor, why would the two hemispheres have opposite seasons? As we shall show, the seasons are actually caused by the 23.5° tilt of the Earth's axis.

As Earth travels around the Sun, in June the Northern Hemisphere “leans into” the Sun and is more directly illuminated. In December, the situation is reversed: the Southern Hemisphere leans into the Sun, and the Northern Hemisphere leans away. In September and March, Earth leans “sideways”—neither into the Sun nor away from it—so the two hemispheres are equally favored with sunshine.

How does the Sun’s favoring one hemisphere translate into making it warmer for us down on the surface of Earth? There are two effects we need to consider. When we lean into the Sun, sunlight hits us at a more direct angle and is more effective at heating Earth’s surface. You can get a similar effect by shining a flashlight onto a wall. If you shine the flashlight straight on, you get an intense spot of light on the wall. But if you hold the flashlight at an angle (if the wall “leans out” of the beam), then the spot of light is more spread out. Like the straight-on light, the sunlight in June is more direct and intense in the Northern Hemisphere, and hence more effective at heating.

The second effect has to do with the length of time the Sun spends above the horizon. Even if you’ve never thought about astronomy before, we’re sure you have observed that the hours of daylight increase in summer and decrease in winter.

In June, the Sun is more north in the sky and spends more time with those who live in the Northern Hemisphere. It rises high in the sky and is above the horizon in the United States for as long as 15 hours. Thus, the Sun not only heats us with more direct rays, but it also has more time to do it each day. In December, when the Sun is farther south in the sky, the situation is reversed.`;

const REWRITE_ACTIONS = [
  { id: 'light_polish', label: 'Light Polish' },
  { id: 'improve_clarity', label: 'Improve Clarity' },
  { id: 'major_rewrite', label: 'Major Rewrite' },
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
  const [answer, setAnswer] = useState('');
  const [selection, setSelection] = useState({ start: 0, end: 0 });
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [running, setRunning] = useState<string | null>(null); const [error, setError] = useState(''); const [notice, setNotice] = useState('');
  const [history, setHistory] = useState<EvalRun[]>([]); const [actions, setActions] = useState<string[]>([]); const manualLogged = useRef(false);
  const wordCount = countWords(answer); const latest = history.at(-1);
  const stale = Boolean(latest && latest.text !== answer);
  const log = (action: string) => setActions(current => [...current, action]);
  const edit = (value: string) => { setAnswer(value); if (!manualLogged.current) { log('Manual edit'); manualLogged.current = true; } };
  const replacePassage = (value: string, source: string) => {
    setAnswer(value); setSelection({ start: 0, end: 0 }); setError(''); setNotice(`Passage loaded: ${source}.`); setHistory([]); setActions([`${source} passage`]); manualLogged.current = false;
  };
  const generate = async () => {
    setRunning('generate'); setError(''); setNotice('Generating an approximately 450-word passage…');
    try { const data = await jsonRequest(`${API_BASE}/turning-test/ai`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ prompt_id: TURNING_TEST_PROMPT.id, question: TURNING_TEST_PROMPT.question }) }); const next = String(data.answer ?? ''); if (!next.trim()) throw new Error('The AI returned an empty answer.'); replacePassage(next, 'AI-generated'); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'The passage could not be generated.'); setNotice(''); }
    finally { setRunning(null); }
  };
  const rewrite = async (action: typeof REWRITE_ACTIONS[number]) => {
    const { start, end } = selection; const selectedText = answer.slice(start, end);
    if (running || !selectedText) return;
    setRunning(action.id); setError(''); setNotice(`${action.label} is revising the highlighted text…`);
    try { const data = await jsonRequest(`${API_BASE}/turning-test/rewrite`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: action.id, selected_text: selectedText }) }); const replacement = String(data.rewritten_text ?? ''); if (!replacement.trim()) throw new Error('The AI returned an empty revision.'); setAnswer(current => current.slice(0, start) + replacement + current.slice(end)); const nextEnd = start + replacement.length; setSelection({ start, end: nextEnd }); setNotice(`${action.label} applied to the highlighted text.`); log(action.label); window.setTimeout(() => { textareaRef.current?.focus(); textareaRef.current?.setSelectionRange(start, nextEnd); }, 0); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'The selected text could not be revised.'); setNotice(''); }
    finally { setRunning(null); }
  };
  const evaluate = async () => {
    if (running || wordCount < EVALUATION_MIN_WORDS) return; setRunning('evaluation'); setError(''); const snapshot = { promptId: TURNING_TEST_PROMPT.id, question: TURNING_TEST_PROMPT.question, text: answer, wordCount, actions: [...actions] };
    try { const submitted = await jsonRequest(`${API_BASE}/turning-test/pangram`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: snapshot.text }) }); const taskId = String(submitted.task_id); const requestedModel = String(submitted.requested_model); let response = submitted.response as Json; let stage = stageOf(response);
      for (let attempt = 0; !['STAGE_SUCCESS', 'STAGE_FAILED'].includes(stage) && attempt < 30; attempt++) { await new Promise(resolve => window.setTimeout(resolve, 2000)); const status = await jsonRequest(`${API_BASE}/turning-test/pangram/${encodeURIComponent(taskId)}`); response = status.response as Json; stage = stageOf(response); }
      if (stage === 'STAGE_FAILED') throw new Error('Pangram reported a failed task. No result was recorded.'); if (stage !== 'STAGE_SUCCESS') throw new Error('Pangram did not finish within one minute. Try again; no result was recorded.');
      const run: EvalRun = { run: history.length + 1, timestamp: new Date().toISOString(), ...snapshot, requestedModel, taskId, response, result: resultObject(response) }; setHistory(current => [...current, run]); setActions([]); manualLogged.current = false;
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Pangram evaluation failed.'); } finally { setRunning(null); }
  };
  const deltas = useMemo(() => (run: EvalRun, index: number) => { const previous = history[index - 1]; if (!previous || previous.promptId !== run.promptId || previous.requestedModel !== run.requestedModel || previous.result.version !== run.result.version) return null; return ['fraction_ai', 'fraction_ai_assisted', 'fraction_human'].map(key => { const a = fraction(run.result, key), b = fraction(previous.result, key); return a === undefined || b === undefined ? 'n/a' : `${((a - b) * 100) >= 0 ? '+' : ''}${((a - b) * 100).toFixed(1)} pp`; }).join(' · '); }, [history]);
  return <div className="tt-shell"><main className="tt-main">
    <header className="tt-intro"><h1>Turning Test</h1><p>Can you make AI-written text pass as human?</p></header>
    <section className="tt-card tt-compose">
      <div className="tt-prompt"><span>Prompt</span><strong>{TURNING_TEST_PROMPT.question}</strong></div>
      <div className="tt-source-actions" aria-label="Choose passage source">
        <button type="button" onClick={generate} disabled={Boolean(running)}>{running === 'generate' ? 'Generating…' : 'AI-Generated'}</button>
        <button type="button" onClick={() => replacePassage(HUMAN_GENERATED_PASSAGE, 'Human-generated')} disabled={Boolean(running)}>Human-Generated</button>
      </div>
      {notice && <p className="tt-notice" role="status">{notice}</p>}
      <label htmlFor="tt-answer"><strong>Your answer</strong></label>
      <textarea ref={textareaRef} id="tt-answer" value={answer} onChange={event => edit(event.target.value)} onSelect={event => setSelection({ start: event.currentTarget.selectionStart, end: event.currentTarget.selectionEnd })} disabled={Boolean(running)} placeholder="Choose a passage source, then edit it here…" />
      <div className="tt-editor-footer"><p className="tt-count">{wordCount} words</p><p className="tt-selection-guidance">{selection.start === selection.end ? 'Highlight text to enable AI editing.' : `${countWords(answer.slice(selection.start, selection.end))} words selected`}</p></div>
      <div className="tt-rewrite-actions" aria-label="AI editing tools">{REWRITE_ACTIONS.map(action => <button key={action.id} type="button" onMouseDown={event => event.preventDefault()} onClick={() => rewrite(action)} disabled={Boolean(running) || selection.start === selection.end}>{running === action.id ? 'Revising…' : action.label}</button>)}</div>
      <button type="button" className="tt-evaluate" onClick={evaluate} disabled={Boolean(running) || wordCount < EVALUATION_MIN_WORDS}>{running === 'evaluation' ? 'Pangram is evaluating…' : 'Run Pangram Eval'}</button>{wordCount < EVALUATION_MIN_WORDS && <p className="tt-guidance">Add {EVALUATION_MIN_WORDS - wordCount} more {EVALUATION_MIN_WORDS - wordCount === 1 ? 'word' : 'words'} to enable evaluation. Text is never padded automatically.</p>}{error && <p className="tt-error" role="alert">{error}</p>}
    </section>
    {latest ? <Report run={latest} stale={stale} /> : <section className="tt-report tt-empty"><p className="tt-eyebrow">Pangram Report</p><h2>No evaluation yet</h2><p>Choose a passage, write at least {EVALUATION_MIN_WORDS} words, then run the evaluation.</p></section>}
    <section className="tt-history"><h2>Evaluation history</h2><p>This session log records interactions in this app, not verified authorship of pasted or typed text.</p>{history.length ? [...history].reverse().map((run, reverseIndex) => { const index = history.length - 1 - reverseIndex; const delta = deltas(run, index); return <details key={run.run}><summary><span><strong>Run {run.run}</strong> · {new Date(run.timestamp).toLocaleTimeString()} · {run.actions.join(' → ') || 'No actions logged'}</span><span>{display(run.result.prediction_short)} · {percent(fraction(run.result, 'fraction_ai'))} / {percent(fraction(run.result, 'fraction_ai_assisted'))} / {percent(fraction(run.result, 'fraction_human'))}</span>{delta && <small>Change (AI / assisted / human): {delta}</small>}</summary><Report run={run} stale={false} /></details>; }) : <p>No successful evaluations in this session.</p>}</section>
  </main></div>;
}
