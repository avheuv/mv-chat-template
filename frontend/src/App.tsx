import { useState, useEffect } from 'react';

// API Base URL - hardcoded for dev, normally from env
const API_BASE = 'http://localhost:8000/api';

type Prototype = {
  id: string;
  name: string;
  description: string;
  ui: {
    title: string;
    subtitle: string;
    placeholder: string;
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
  const [selectedPrototype, setSelectedPrototype] = useState<string>('');
  const [studentCode, setStudentCode] = useState<string>('');
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
          setSelectedPrototype(urlPrototype);
        } else if (data.length > 0) {
          setSelectedPrototype(data[0].id);
        }
      })
      .catch(e => setError('Failed to load prototypes. Ensure backend is running.'));
  }, []);

  const handleStart = async () => {
    if (!studentCode.trim()) {
      setError('Please enter a Student Code.');
      return;
    }
    setError('');
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/chat/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prototype_id: selectedPrototype, user_id: studentCode })
      });
      if (!res.ok) throw new Error('Failed to start session');
      const data = await res.json();
      setSession(data);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
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

  const activePrototypeUI = prototypes.find(p => p.id === session?.prototype_id)?.ui;

  if (!session) {
    return (
      <div className="act-app-shell">
        <div className="act-app-header">
          <div className="act-brand">AI Prototype Starter</div>
        </div>
        <main className="act-main">
          <section className="act-welcome-card">
            <h1>Welcome</h1>
            <p>Select a prototype and enter your Student Code to begin.</p>

            <div className="act-form-row">
              <label>Prototype</label>
              <select
                value={selectedPrototype}
                onChange={e => setSelectedPrototype(e.target.value)}
              >
                {prototypes.map(p => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
            </div>

            <div className="act-form-row">
              <label>Student Code</label>
              <input
                type="text"
                placeholder="Enter your Student Code (e.g. student-123)"
                value={studentCode}
                onChange={e => setStudentCode(e.target.value)}
              />
            </div>

            {error && <div className="act-error-message">{error}</div>}

            <button
              className="act-primary-btn"
              onClick={handleStart}
              disabled={loading || prototypes.length === 0}
            >
              {loading ? 'Starting...' : 'Start'}
            </button>
          </section>
        </main>
      </div>
    );
  }

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
