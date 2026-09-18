import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';

type Phase = 'assessment' | 'building' | 'learning' | 'complete';
type Message = { id: number; role: 'coach' | 'user'; text: string; label?: string };
type Objective = { title: string; summary: string; prompt: (role: string) => string; keywords: string[] };

const questions = [
  "To make this useful for your day-to-day work, what is your role at the company, and where do you usually work?",
  "Imagine you notice blood on a shared surface. What would you do first, and what would you avoid doing?",
  "If blood or another potentially infectious material splashes into your eye, what steps would you take?",
];

const objectiveBank: Objective[] = [
  {
    title: 'Recognize exposure risks',
    summary: 'Identify blood, potentially infectious materials, and the tasks where exposure could happen.',
    prompt: role => `Let’s connect this to your work as ${role}. Which task or location in your work could create contact with blood or another potentially infectious material—even if that contact is uncommon?`,
    keywords: ['blood', 'sharp', 'needle', 'first aid', 'cleanup', 'customer', 'patient', 'spill', 'waste'],
  },
  {
    title: 'Respond safely to blood',
    summary: 'Use universal precautions, PPE, and safe cleanup and disposal practices.',
    prompt: role => `For someone working as ${role}, picture a small blood spill in your work area. Talk me through how you would secure the area, choose protection, and get the spill cleaned up safely.`,
    keywords: ['glove', 'ppe', 'block', 'isolate', 'disinfect', 'trained', 'kit', 'report', 'sharps'],
  },
  {
    title: 'Act after an exposure',
    summary: 'Perform immediate first aid, report promptly, and access confidential follow-up care.',
    prompt: role => `Now imagine you have a needlestick or a splash to your eyes while working as ${role}. What would you do in the first few minutes, and who would you contact next?`,
    keywords: ['wash', 'flush', 'rinse', 'report', 'supervisor', 'medical', 'evaluation', 'follow-up', 'immediately'],
  },
];

const uid = () => Date.now() + Math.floor(Math.random() * 1000);

export default function BloodborneLearning({ onExit }: { onExit: () => void }) {
  const [phase, setPhase] = useState<Phase>('assessment');
  const [question, setQuestion] = useState(0);
  const [answers, setAnswers] = useState<string[]>([]);
  const [messages, setMessages] = useState<Message[]>([{ id: 1, role: 'coach', label: 'Quick check · 1 of 3', text: questions[0] }]);
  const [objectives, setObjectives] = useState<Objective[]>([]);
  const [active, setActive] = useState(0);
  const [completed, setCompleted] = useState<number[]>([]);
  const [attempts, setAttempts] = useState(0);
  const [text, setText] = useState('');
  const endRef = useRef<HTMLDivElement>(null);

  const role = answers[0]?.trim() || 'your role';
  useEffect(() => endRef.current?.scrollIntoView({ behavior: 'smooth' }), [messages, phase]);

  const buildPlan = (responses: string[]) => {
    const safety = responses.slice(1).join(' ').toLowerCase();
    const selected = objectiveBank.filter((objective, index) => index === 0 || !objective.keywords.some(word => safety.includes(word)));
    const plan = selected.slice(0, Math.max(1, Math.min(3, selected.length)));
    setPhase('building');
    window.setTimeout(() => {
      setObjectives(plan);
      setPhase('learning');
      setMessages(previous => [...previous, {
        id: uid(), role: 'coach', label: 'Your learning plan',
        text: `You already recognize that a blood spill requires a deliberate response rather than casual cleanup. I’ve tailored ${plan.length === 1 ? 'one focus area' : `${plan.length} focus areas`} to strengthen the parts of your response that were less specific. We’ll apply each one to your work as ${responses[0].trim() || 'an employee'}.`,
      }, { id: uid(), role: 'coach', label: 'Objective 1', text: plan[0].prompt(responses[0].trim() || 'an employee') }]);
    }, 1100);
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const response = text.trim();
    if (!response || phase === 'building' || phase === 'complete') return;
    setText('');
    setMessages(previous => [...previous, { id: uid(), role: 'user', text: response }]);

    if (phase === 'assessment') {
      const nextAnswers = [...answers, response];
      setAnswers(nextAnswers);
      if (question < 2) {
        const next = question + 1;
        setQuestion(next);
        window.setTimeout(() => setMessages(previous => [...previous, { id: uid(), role: 'coach', label: `Quick check · ${next + 1} of 3`, text: questions[next] }]), 250);
      } else buildPlan(nextAnswers);
      return;
    }

    const objective = objectives[active];
    const matches = objective.keywords.filter(keyword => response.toLowerCase().includes(keyword)).length;
    if (matches >= 2 || attempts >= 1) {
      const nextCompleted = [...completed, active];
      setCompleted(nextCompleted);
      setAttempts(0);
      const next = active + 1;
      if (next < objectives.length) {
        setActive(next);
        window.setTimeout(() => setMessages(previous => [...previous,
          { id: uid(), role: 'coach', label: 'Objective complete', text: `That’s it. You connected the safety principle to your role and named concrete actions you can take. Let’s build on that.` },
          { id: uid(), role: 'coach', label: `Objective ${next + 1}`, text: objectives[next].prompt(role) },
        ]), 300);
      } else {
        setPhase('complete');
        window.setTimeout(() => setMessages(previous => [...previous, { id: uid(), role: 'coach', label: 'Training complete', text: `Well done. You’ve demonstrated the key decisions for your role: recognize the risk, avoid direct contact, use your company’s response procedures, and report any exposure immediately. Follow your organization’s exposure control plan whenever an incident occurs.` }]), 300);
      }
    } else {
      setAttempts(value => value + 1);
      window.setTimeout(() => setMessages(previous => [...previous, { id: uid(), role: 'coach', label: 'Let’s make it more specific', text: `You’re on the right track. Add two concrete actions you would take. Think about protecting people, the right PPE or supplies, and who you would notify under your company’s procedure.` }]), 300);
    }
  };

  const progress = phase === 'assessment' ? ((question + 1) / 3) * 22 : phase === 'building' ? 28 : phase === 'complete' ? 100 : 30 + (completed.length / Math.max(objectives.length, 1)) * 70;

  return <div className="bbp-shell">
    <header className="bbp-header">
      <button className="bbp-back" onClick={onExit} aria-label="Back to prototypes">←</button>
      <div className="bbp-brand"><span className="bbp-mark">MV</span><div><strong>SafeWork Coach</strong><small>Bloodborne Pathogens</small></div></div>
      <div className="bbp-status"><span className="bbp-status-dot" /> {phase === 'complete' ? 'Complete' : 'In progress'}</div>
    </header>
    <div className="bbp-progress"><span style={{ width: `${progress}%` }} /></div>
    <main className="bbp-layout">
      <aside className="bbp-plan">
        <p className="bbp-eyebrow">YOUR LEARNING PLAN</p>
        <h2>{phase === 'assessment' ? 'First, a quick check' : phase === 'building' ? 'Personalizing your plan' : `${objectives.length} learning ${objectives.length === 1 ? 'objective' : 'objectives'}`}</h2>
        {phase === 'assessment' && <div className="bbp-check-list">{questions.map((_, index) => <div className={index < question ? 'done' : index === question ? 'current' : ''} key={index}><span>{index < question ? '✓' : index + 1}</span><p>{index === 0 ? 'Your role' : index === 1 ? 'Safe response' : 'Exposure response'}</p></div>)}</div>}
        {phase === 'building' && <div className="bbp-building-card"><i /><p>Reviewing your responses</p><small>Finding the most useful focus areas for your role…</small></div>}
        {(phase === 'learning' || phase === 'complete') && <div className="bbp-objectives">{objectives.map((objective, index) => <article key={objective.title} className={completed.includes(index) ? 'done' : index === active && phase !== 'complete' ? 'current' : ''}><span>{completed.includes(index) ? '✓' : index + 1}</span><div><h3>{objective.title}</h3><p>{objective.summary}</p></div></article>)}</div>}
        <div className="bbp-time"><span>◷</span><div><strong>{phase === 'complete' ? 'Completed' : 'About 5–8 minutes'}</strong><small>Personalized to your role</small></div></div>
      </aside>
      <section className="bbp-chat" aria-label="Training conversation">
        <div className="bbp-chat-title"><div className="bbp-avatar">SC</div><div><strong>Safety Coach</strong><small>AI learning guide</small></div></div>
        <div className="bbp-messages" aria-live="polite">
          <div className="bbp-welcome"><p>WELCOME</p><h1>Let’s make safety<br/>relevant to your work.</h1><span>I’ll start with three quick questions—this isn’t a test. Your answers help me focus on what will be most useful to you.</span></div>
          {messages.map(message => <div key={message.id} className={`bbp-message-row ${message.role}`}><div className="bbp-message">{message.label && <small>{message.label}</small>}<p>{message.text}</p></div></div>)}
          {phase === 'building' && <div className="bbp-thinking"><span /><span /><span /> Building custom learning plan</div>}
          <div ref={endRef} />
        </div>
        <form className="bbp-compose" onSubmit={submit}>
          <textarea aria-label="Your response" value={text} onChange={event => setText(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} disabled={phase === 'building' || phase === 'complete'} placeholder={phase === 'complete' ? 'Training complete' : phase === 'building' ? 'Building your plan…' : 'Type your response…'} />
          <button disabled={!text.trim() || phase === 'building' || phase === 'complete'} aria-label="Send response">↑</button>
          <small>Press Enter to send · Shift + Enter for a new line</small>
        </form>
      </section>
    </main>
  </div>;
}
