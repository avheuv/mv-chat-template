import { useState, useEffect } from 'react';

// API Base URL - hardcoded for dev, normally from env
const API_BASE = 'http://localhost:8000/api';

type UIInputConfig = {
  id: string;
  label: string;
  placeholder: string;
};

type Prototype = {
  id: string;
  name: string;
  description: string;
  ui: {
    title: string;
    subtitle: string;
    placeholder: string;
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
      .catch(e => setError('Failed to load prototypes. Ensure backend is running.'));
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

      const sessionRes = await fetch(`${API_BASE}/chat/session/${session.id}`);
      const sessionData = await sessionRes.json();
      setSession(sessionData);

      // Auto-scroll logic could go here
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const activePrototypeUI = prototypes.find(p => p.id === selectedPrototypeId)?.ui;

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
                 <input
                   type="text"
                   placeholder={input.placeholder || ''}
                   value={inputValues[input.id] || ''}
                   onChange={e => updateInputValue(input.id, e.target.value)}
                 />
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

  return (
    <div className="act-app-shell">
      <div className="act-app-header">
        <div className="act-brand">{activePrototypeUI?.title || 'Chat'}</div>
      </div>
      <main className="act-main relative">
        <div className="act-chat-messages">
          {session.messages.filter(m => m.role !== 'system').map(m => (
            <div key={m.id} className={`act-message-row act-message-row-${m.role}`}>
              <div className={`act-bubble act-bubble-${m.role}`}>
                {m.content}
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
        </div>

        <div className="act-composer-wrap">
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
        </div>
      </main>
    </div>
  );
}

export default App;
