import { useState, useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';

// Use environment variable for production, fallback to local dev server
const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api';

type UIInputConfig = {
  id: string;
  label: string;
  type: 'text' | 'select';
  placeholder?: string;
  options?: { label: string; value: string }[];
};

type Prototype = {
  id: string;
  name: string;
  description: string;
  ui: {
    title: string;
    subtitle: string;
    placeholder: string;
    readonly: boolean;
    inputs: UIInputConfig[];
  }
};

type Message = {
  id: string;
  role: 'system' | 'user' | 'assistant';
  content: string;
};

type ChatSession = {
  id: string;
  prototype_id: string;
  user_id: string;
  messages: Message[];
};

type AssessmentData = {
  score: number;
  engagement_score: number;
  summary: string;
  tip?: string;
};

function App() {
  const [prototypes, setPrototypes] = useState<Prototype[]>([]);
  const [selectedPrototypeId, setSelectedPrototypeId] = useState<string>('');

  // inputValues stores the dynamic form inputs keyed by input id
  const [inputValues, setInputValues] = useState<Record<string, string>>({});

  // The state machine for our 3 pages
  const [view, setView] = useState<'landing' | 'splash' | 'chat'>('landing');

  const [session, setSession] = useState<ChatSession | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [inputValue, setInputValue] = useState('');

  // Ref for auto-scrolling
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // State for the assessment prototype specific UI
  const [assessmentData, setAssessmentData] = useState<AssessmentData | null>(null);
  const [savingScore, setSavingScore] = useState(false);

  const composerWrapRef = useRef<HTMLDivElement>(null);
  const [composerHeight, setComposerHeight] = useState(120);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    if (view === 'chat') {
      scrollToBottom();
    }
  }, [session?.messages, loading, view]);

  useEffect(() => {
    if (view === 'chat' && composerWrapRef.current) {
      const resizeObserver = new ResizeObserver((entries) => {
        for (let entry of entries) {
          if (entry.target === composerWrapRef.current) {
             setComposerHeight(entry.contentRect.height);
             scrollToBottom(); // Re-scroll if height changes to maintain visibility
          }
        }
      });
      resizeObserver.observe(composerWrapRef.current);
      return () => resizeObserver.disconnect();
    }
  }, [view, assessmentData]); // Dependency on assessmentData to ensure ref is checked when UI changes

  useEffect(() => {
    fetch(`${API_BASE}/prototypes`)
      .then(r => r.json())
      .then(data => {
        setPrototypes(data);

        // Check URL for prototype query param (e.g. ?prototype=profile_builder)
        const params = new URLSearchParams(window.location.search);
        const urlPrototype = params.get('prototype');

        if (urlPrototype && data.find((p: Prototype) => p.id === urlPrototype)) {
          setSelectedPrototypeId(urlPrototype);
          setView('splash');
        } else if (data.length > 0) {
          setSelectedPrototypeId(data[0].id);
          setView('landing');
        }
      })
      .catch(() => setError('Failed to load prototypes. Ensure backend is running.'));
  }, []);

  const handleOpenSplash = () => {
    // Navigate via query param so the user has a shareable link
    const newUrl = new URL(window.location.href);
    newUrl.searchParams.set('prototype', selectedPrototypeId);
    window.history.pushState({}, '', newUrl);

    setError('');
    setView('splash');
  };

  const handleStartSession = async () => {
    // Validation: make sure all required fields defined in YAML have some value
    const prototype = prototypes.find(p => p.id === selectedPrototypeId);
    if (!prototype) return;

    for (const input of prototype.ui.inputs) {
      if (!inputValues[input.id]?.trim()) {
        setError(`Please enter a value for ${input.label}.`);
        return;
      }
    }

    setError('');
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/chat/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          prototype_id: selectedPrototypeId,
          inputs: inputValues
        })
      });
      if (!res.ok) throw new Error('Failed to start session');
      const data = await res.json();
      setSession(data);
      setView('chat');
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const updateInputValue = (id: string, value: string) => {
    setInputValues(prev => ({ ...prev, [id]: value }));
  };

  const handleSend = async () => {
    if (!inputValue.trim() || !session || loading) return;

    const userContent = inputValue;
    setInputValue('');
    setLoading(true);

    // Optimistically update UI
    const tempId = `temp-${Date.now()}`;
    setSession({
      ...session,
      messages: [...session.messages, { id: tempId, role: 'user', content: userContent }]
    });

    try {
      const res = await fetch(`${API_BASE}/chat/send`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: session.id, content: userContent })
      });
      if (!res.ok) throw new Error('Failed to send message');

      const chatResponse = await res.json();

      // If this is the assessment prototype, the backend will return the score in structured_data
      if (chatResponse.structured_data && chatResponse.structured_data.score !== undefined) {
         // Calculate engagement score based on user messages word count
         const userMessages = session.messages.filter(m => m.role === 'user');
         const newUserMessages = [...userMessages, { id: tempId, role: 'user', content: userContent }];
         let totalWords = 0;
         for (const msg of newUserMessages) {
            // Very simple word count
            const words = msg.content.trim().split(/\s+/).filter(w => w.length > 0);
            totalWords += words.length;
         }
         const engagementScore = Math.min(100, totalWords);

         setAssessmentData({
           score: chatResponse.structured_data.score,
           engagement_score: engagementScore,
           summary: chatResponse.structured_data.summary || '',
           tip: chatResponse.structured_data.tip
         });
      }

      const sessionRes = await fetch(`${API_BASE}/chat/session/${session.id}`);
      const sessionData = await sessionRes.json();
      setSession(sessionData);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const activePrototype = prototypes.find(p => p.id === selectedPrototypeId);
  const activePrototypeUI = activePrototype?.ui;

  const handleSaveScore = async () => {
    if (!session || !assessmentData || savingScore) return;
    setSavingScore(true);
    try {
      const res = await fetch(`${API_BASE}/chat/save-score`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: inputValues['user_id'] || 'unknown',
          lesson_topic: inputValues['lesson_code'] || 'unknown',
          score: assessmentData.score,
          engagement_score: assessmentData.engagement_score,
          summary: assessmentData.summary
        })
      });
      if (!res.ok) throw new Error('Failed to save score');
      alert('Score saved successfully!');
    } catch (e: any) {
      alert(`Error saving score: ${e.message}`);
    } finally {
      setSavingScore(false);
    }
  };

  if (view === 'landing') {
    return (
      <div className="act-app-shell">
        <div className="act-app-header">
          <div className="act-brand">AI Prototype Starter</div>
        </div>
        <main className="act-main">
          <section className="act-welcome-card">
            <h1>Developer Landing Page</h1>
            <p>Select a prototype to open its user-facing splash screen.</p>

            <div className="act-form-row">
              <label>Prototype</label>
              <select
                value={selectedPrototypeId}
                onChange={e => setSelectedPrototypeId(e.target.value)}
              >
                {prototypes.map(p => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
            </div>

            <button
              className="act-primary-btn"
              onClick={handleOpenSplash}
              disabled={prototypes.length === 0}
            >
              Open
            </button>
          </section>
        </main>
      </div>
    );
  }

  if (view === 'splash' && activePrototypeUI) {
    return (
      <div className="act-app-shell">
        <div className="act-app-header">
          <div className="act-brand">{activePrototypeUI.title}</div>
        </div>
        <main className="act-main">
          <section className="act-welcome-card">
            <h1>Welcome</h1>
            <p>{activePrototypeUI.subtitle || 'Please fill out the information below to begin.'}</p>

            {activePrototypeUI.inputs.map(input => (
               <div key={input.id} className="act-form-row">
                 <label>{input.label}</label>
                 {input.type === 'select' && input.options ? (
                   <select
                     value={inputValues[input.id] || ''}
                     onChange={e => updateInputValue(input.id, e.target.value)}
                   >
                     <option value="" disabled>Select {input.label}</option>
                     {input.options.map(opt => (
                       <option key={opt.value} value={opt.value}>{opt.label}</option>
                     ))}
                   </select>
                 ) : (
                   <input
                     type="text"
                     placeholder={input.placeholder || ''}
                     value={inputValues[input.id] || ''}
                     onChange={e => updateInputValue(input.id, e.target.value)}
                   />
                 )}
               </div>
            ))}

            {error && <div className="act-error-message">{error}</div>}

            <button
              className="act-primary-btn"
              onClick={handleStartSession}
              disabled={loading}
            >
              {loading ? 'Starting...' : 'Start'}
            </button>
          </section>
        </main>
      </div>
    );
  }

  // Chat View
  if (!session) return null;

  // Helper to convert OpenAI's default LaTeX delimiters to standard Markdown ones for remark-math
  const processMathDelimiters = (text: string) => {
    if (!text) return text;
    return text
      .replace(/\\\[/g, '$$$$')
      .replace(/\\\]/g, '$$$$')
      .replace(/\\\(/g, '$')
      .replace(/\\\)/g, '$');
  };

  return (
    <div className="act-app-shell">
      <div className="act-app-header">
        <div className="act-brand">{activePrototypeUI?.title || 'Chat'}</div>
      </div>
      <main className="act-main relative">
        <div className="act-chat-messages" style={{ paddingBottom: `${composerHeight + 20}px` }}>
          {session.messages.filter(m => m.role !== 'system').map(m => (
            <div key={m.id} className={`act-message-row act-message-row-${m.role}`}>
              <div className={`act-bubble act-bubble-${m.role} markdown-content`}>
                <ReactMarkdown
                  remarkPlugins={[remarkGfm, remarkMath]}
                  rehypePlugins={[rehypeKatex]}
                  components={{
                    a: ({ node, ...props }) => (
                      <a {...props} target="_blank" rel="noopener noreferrer" />
                    )
                  }}
                >
                  {processMathDelimiters(m.content)}
                </ReactMarkdown>
              </div>
            </div>
          ))}
          {loading && (
             <div className="act-message-row act-message-row-assistant">
             <div className="act-bubble act-bubble-assistant opacity-50">
               Thinking...
             </div>
           </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        {!activePrototypeUI?.readonly && (
          <div className="act-composer-wrap" ref={composerWrapRef}>
            <div className="act-composer">
              <textarea
                placeholder={activePrototypeUI?.placeholder || 'Type your message...'}
                value={inputValue}
                onChange={e => setInputValue(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    handleSend();
                  }
                }}
                rows={1}
              />
              <button
                className="act-send-btn"
                onClick={handleSend}
                disabled={loading || !inputValue.trim()}
              >
                Send
              </button>
            </div>
            {assessmentData && (
              <div className="act-score-bar-container" style={{
                marginTop: '12px',
                display: 'flex',
                flexDirection: 'column',
                gap: '12px',
                width: '100%',
                backgroundColor: 'var(--surface)',
                padding: '12px 16px',
                borderRadius: '8px',
                border: '1px solid var(--border)'
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontWeight: 'bold', color: '#333' }}>Score</span>
                  <button
                    style={{
                      padding: '6px 12px',
                      fontSize: '14px',
                      width: 'auto',
                      backgroundColor: '#1E3A8A',
                      color: 'white',
                      border: 'none',
                      borderRadius: '6px',
                      cursor: savingScore ? 'not-allowed' : 'pointer',
                      opacity: savingScore ? 0.7 : 1
                    }}
                    onClick={handleSaveScore}
                    disabled={savingScore}
                  >
                    {savingScore ? 'Saving...' : 'Save Score'}
                  </button>
                </div>

                {/* Engagement Score Bar */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                  <span style={{ width: '100px', fontSize: '14px', color: '#666' }}>Engagement</span>
                  <div style={{
                    flex: 1,
                    height: '10px',
                    backgroundColor: 'var(--bg-main)',
                    borderRadius: '5px',
                    overflow: 'hidden'
                  }}>
                    <div style={{
                      width: `${assessmentData.engagement_score}%`,
                      height: '100%',
                      backgroundColor: '#DC2626', // Red
                      transition: 'width 0.3s ease'
                    }}></div>
                  </div>
                  <span style={{ width: '45px', textAlign: 'right', fontSize: '14px', fontWeight: 'bold', color: '#DC2626' }}>
                    {assessmentData.engagement_score}/100
                  </span>
                </div>

                {/* Understanding Score Bar */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                  <span style={{ width: '100px', fontSize: '14px', color: '#666' }}>Understanding</span>
                  <div style={{
                    flex: 1,
                    height: '10px',
                    backgroundColor: 'var(--bg-main)',
                    borderRadius: '5px',
                    overflow: 'hidden'
                  }}>
                    <div style={{
                      width: `${assessmentData.score}%`,
                      height: '100%',
                      backgroundColor: '#1E3A8A', // Blue
                      transition: 'width 0.3s ease'
                    }}></div>
                  </div>
                  <span style={{ width: '45px', textAlign: 'right', fontSize: '14px', fontWeight: 'bold', color: '#1E3A8A' }}>
                    {assessmentData.score}/100
                  </span>
                </div>

                {assessmentData.tip && (
                  <div style={{ fontSize: '12px', color: '#888', marginTop: '4px' }}>
                    <span style={{ fontWeight: 'bold' }}>Tip:</span> {assessmentData.tip}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  );
}

export default App;
